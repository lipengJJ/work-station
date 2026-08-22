"""Hotlist 语义检索服务：集中管理文本预处理、hash、向量编解码、补算与召回。

抓取服务与报告服务都从这里走，避免各写一套。SQLite 第一版用 float32 BLOB +
NumPy 批量点积做相似度；达到规模阈值后再评估迁移 PostgreSQL + pgvector。
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from loguru import logger
from sqlalchemy.orm import Session

from app.common.services.embedding_config import (
    get_embedding_api_key,
    get_embedding_dimension,
    get_embedding_model,
    get_embedding_provider,
)
from app.common.services.embedding_gateway.base import (
    EmbeddingGatewayError,
    EmbeddingRequest,
    TASK_DOCUMENT,
    TASK_QUERY,
)
from app.common.services.embedding_gateway.service import build_model_key, embed
from app.common.utils.text import strip_html
from app.hotlist.models import (
    HotItem,
    HotItemEmbedding,
    HotTopic,
    HotTopicEmbedding,
)

ITEM_PREPROCESS_VERSION = "item-v1"
QUERY_PREPROCESS_VERSION = "query-v1"
EMBED_BATCH_SIZE = 32
FRESHNESS_HALF_LIFE_HOURS = 48.0

_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class RetrievedCandidate:
    item: HotItem
    semantic_score: float
    hot_score: float
    freshness_score: float
    final_score: float


# ---------------------------------------------------------------- 文本预处理 ----


def _normalize_text(text: str | None) -> str:
    return _WHITESPACE_RE.sub(" ", text or "").strip()


def build_item_text(title: str, summary: str, source_name: str = "") -> str:
    """文章第一版输入：标题 + 摘要 + 来源。不放 URL/榜位/时间/metrics（会污染语义）。"""
    t = _normalize_text(title)[:512]
    s = _normalize_text(strip_html(summary))[:3000]
    # 摘要与标题完全重复时不重复拼接
    body = t if (not s or s == t) else f"{t}\n摘要：{s}"
    if source_name:
        body = f"{body}\n来源：{_normalize_text(source_name)[:128]}"
    return body


def build_query_text(interest_query: str) -> str:
    """主题查询向量输入：清理后的 interest_query + 固定短前缀。

    不要把 extra_question、Skill Prompt、报告周期拼入查询向量。
    """
    q = _normalize_text(interest_query)[:4000]
    return f"需要检索的主题需求：{q}"


def content_hash(preprocess_version: str, text: str) -> str:
    return hashlib.sha256(f"{preprocess_version}\0{text}".encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 向量编解码 ----


def encode_vector(values: list[float]) -> bytes:
    """float32 little-endian BLOB，约为 JSON 数组体积的 20%~30%。"""
    return np.asarray(values, dtype=np.float32).tobytes()


def decode_vector(raw: bytes) -> np.ndarray:
    return np.frombuffer(raw, dtype=np.float32)


def normalize_vector(vector: np.ndarray) -> np.ndarray:
    """L2 归一化；召回时矩阵点积即余弦相似度。零向量保护。"""
    norm = float(np.linalg.norm(vector))
    if norm == 0 or not np.isfinite(norm):
        return vector
    return vector / norm


# ---------------------------------------------------------------- 内部工具 ----


def _current_model_key(db: Session) -> tuple[str, str, int]:
    provider = get_embedding_provider(db)
    model = get_embedding_model(db)
    dimension = get_embedding_dimension(db)
    return provider, model, dimension


def _call_embed(db: Session, texts: list[str], task_type: str) -> list[list[float]]:
    provider, model, dimension = _current_model_key(db)
    api_key = get_embedding_api_key(db)
    if not api_key:
        raise EmbeddingGatewayError("Embedding 未配置 API Key")
    result = embed(
        EmbeddingRequest(provider=provider, model=model, texts=texts, task_type=task_type),
        api_key,
    )
    if result.dimension != dimension:
        raise EmbeddingGatewayError(
            f"Embedding 维度不匹配：配置 {dimension}，实际 {result.dimension}"
        )
    return result.vectors


def _upsert_item_embedding(
    db: Session,
    item_id: int,
    model_key: str,
    item_hash: str,
    dimension: int,
    status: str,
    error: str = "",
    vector: bytes | None = None,
) -> None:
    row = db.get(HotItemEmbedding, item_id)
    if row is None:
        row = HotItemEmbedding(item_id=item_id)
        db.add(row)
    row.model_key = model_key
    row.preprocess_version = ITEM_PREPROCESS_VERSION
    row.dimension = dimension
    row.content_hash = item_hash
    row.status = status
    row.error = error
    if vector is not None:
        row.vector = vector
    if status == "failed":
        row.retry_count = (row.retry_count or 0) + 1
    else:
        row.retry_count = 0


def _upsert_topic_embedding(
    db: Session,
    topic_id: int,
    model_key: str,
    query_hash: str,
    dimension: int,
    status: str,
    error: str = "",
    vector: bytes | None = None,
) -> None:
    row = db.get(HotTopicEmbedding, topic_id)
    if row is None:
        row = HotTopicEmbedding(topic_id=topic_id)
        db.add(row)
    row.model_key = model_key
    row.preprocess_version = QUERY_PREPROCESS_VERSION
    row.dimension = dimension
    row.query_hash = query_hash
    row.status = status
    row.error = error
    if vector is not None:
        row.vector = vector


# ---------------------------------------------------------------- 补算 ----


def ensure_item_embeddings(
    db: Session, items: list[HotItem], best_effort: bool = True
) -> dict:
    """为文章补算向量。独立事务，失败只记状态，不影响文章业务事务。

    返回统计 {generated, skipped, failed, missing_config}。
    """
    stat = {"generated": 0, "skipped": 0, "failed": 0, "missing_config": 0}
    if not items:
        return stat
    if not get_embedding_api_key(db):
        stat["missing_config"] = len(items)
        return stat
    provider, model, dimension = _current_model_key(db)
    model_key = build_model_key(provider, model, dimension)

    pending: list[tuple[HotItem, str]] = []
    for item in items:
        text = build_item_text(item.title, item.summary or "", item.source_id)
        row = db.get(HotItemEmbedding, item.id)
        h = content_hash(ITEM_PREPROCESS_VERSION, text)
        if row is not None and row.model_key == model_key:
            if row.status == "success" and row.content_hash == h:
                stat["skipped"] += 1  # hash 相同且成功：跳过
                continue
            if row.status == "failed" and row.retry_count >= 1:
                stat["skipped"] += 1  # 失败过，交给低频补偿任务
                continue
        pending.append((item, text))

    for i in range(0, len(pending), EMBED_BATCH_SIZE):
        batch = pending[i : i + EMBED_BATCH_SIZE]
        texts = [t for _, t in batch]
        try:
            vectors = _call_embed(db, texts, TASK_DOCUMENT)
        except EmbeddingGatewayError as exc:
            for item, _ in batch:
                _upsert_item_embedding(
                    db, item.id, model_key, "", dimension, "failed", str(exc)[:500]
                )
                stat["failed"] += 1
            if not best_effort:
                db.commit()
                raise
            continue
        for (item, text), vec in zip(batch, vectors):
            h = content_hash(ITEM_PREPROCESS_VERSION, text)
            _upsert_item_embedding(
                db,
                item.id,
                model_key,
                h,
                dimension,
                "success",
                vector=encode_vector(normalize_vector(np.asarray(vec, dtype=np.float32))),
            )
            stat["generated"] += 1
    db.commit()
    return stat


def ensure_topic_embedding(db: Session, topic: HotTopic) -> bool:
    """补算主题查询向量（无兴趣需求直接返回 False）。返回是否 success。"""
    if not (topic.interest_query or "").strip():
        return False
    provider, model, dimension = _current_model_key(db)
    model_key = build_model_key(provider, model, dimension)
    query = build_query_text(topic.interest_query)
    qhash = content_hash(QUERY_PREPROCESS_VERSION, query)
    row = db.get(HotTopicEmbedding, topic.id)
    if row is not None and row.status == "success" and row.query_hash == qhash and row.model_key == model_key:
        return True
    if not get_embedding_api_key(db):
        return False
    try:
        vectors = _call_embed(db, [query], TASK_QUERY)
    except EmbeddingGatewayError as exc:
        _upsert_topic_embedding(db, topic.id, model_key, qhash, dimension, "failed", str(exc)[:500])
        db.commit()
        return False
    _upsert_topic_embedding(
        db,
        topic.id,
        model_key,
        qhash,
        dimension,
        "success",
        vector=encode_vector(normalize_vector(np.asarray(vectors[0], dtype=np.float32))),
    )
    db.commit()
    return True


# ---------------------------------------------------------------- 向量读取 ----


def get_item_vector(db: Session, item_id: int) -> np.ndarray | None:
    row = db.get(HotItemEmbedding, item_id)
    if row is not None and row.status == "success" and row.vector:
        return decode_vector(row.vector)
    return None


def get_topic_vector(db: Session, topic_id: int) -> np.ndarray | None:
    row = db.get(HotTopicEmbedding, topic_id)
    if row is not None and row.status == "success" and row.vector:
        return decode_vector(row.vector)
    return None


# ---------------------------------------------------------------- 语义召回 ----


def _minmax(values: np.ndarray) -> np.ndarray:
    lo = float(values.min())
    hi = float(values.max())
    if hi == lo:
        return np.zeros_like(values)
    return (values - lo) / (hi - lo)


def _freshness(item: HotItem) -> float:
    ts = item.published_at or item.last_crawl_time
    if ts is None:
        return 0.0
    age_hours = max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 3600)
    return math.exp(-age_hours / FRESHNESS_HALF_LIFE_HOURS)


def rank_with_query(
    db: Session,
    topic: HotTopic,
    candidate_items: list[HotItem],
    query_vec: np.ndarray,
    threshold: float | None = None,
    limit: int | None = None,
) -> tuple[list[RetrievedCandidate], int]:
    """用给定查询向量对候选文章排序（阈值门槛 → Top K 综合分）。

    threshold/limit 缺省时用主题配置；预览接口可临时覆盖（不落库）。
    返回 (召回列表(按 final_score 降序), 缺失向量文章数)。
    """
    sim_threshold = threshold if threshold is not None else topic.similarity_threshold
    top_k = limit if limit is not None else topic.retrieval_size
    vectors: list[np.ndarray] = []
    valid_items: list[HotItem] = []
    missing = 0
    for item in candidate_items:
        v = get_item_vector(db, item.id)
        if v is None:
            missing += 1
            continue
        vectors.append(v)
        valid_items.append(item)
    if not vectors:
        return [], missing

    matrix = np.vstack(vectors).astype(np.float32)
    query = query_vec.astype(np.float32)
    scores = matrix @ query  # 两侧已归一化

    hot_raw = np.asarray([it.weight for it in valid_items], dtype=np.float32)
    hot_norm = _minmax(hot_raw)
    freshness = np.asarray([_freshness(it) for it in valid_items], dtype=np.float32)
    final = 0.80 * scores + 0.15 * hot_norm + 0.05 * freshness

    eligible = np.flatnonzero(scores >= sim_threshold)
    top_idx = eligible[np.argsort(final[eligible])[::-1][:top_k]]

    results: list[RetrievedCandidate] = []
    for pos in top_idx:
        i = int(pos)
        results.append(
            RetrievedCandidate(
                item=valid_items[i],
                semantic_score=float(scores[i]),
                hot_score=float(hot_norm[i]),
                freshness_score=float(freshness[i]),
                final_score=float(final[i]),
            )
        )
    results.sort(key=lambda r: r.final_score, reverse=True)
    return results, missing


def retrieve_semantic_candidates(
    db: Session, topic: HotTopic, candidate_items: list[HotItem]
) -> tuple[list[RetrievedCandidate], int]:
    """语义召回：主题查询向量 × 文章向量矩阵点积 → 阈值门槛 → Top K 综合排序。"""
    topic_vec = get_topic_vector(db, topic.id)
    if topic_vec is None:
        return [], len(candidate_items)
    return rank_with_query(db, topic, candidate_items, topic_vec)
