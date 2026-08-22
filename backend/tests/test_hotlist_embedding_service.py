"""Hotlist 语义检索服务测试：Embedding 预处理、编解码、补算与召回。

测试不得调用真实模型——Embedding Gateway 使用固定向量 Fake Provider。
"""
from __future__ import annotations

import hashlib

import numpy as np
import pytest

from app.common.models import ApiConfig
from app.common.services.embedding_gateway.base import (
    EmbeddingRequest,
    EmbeddingResult,
)
from app.common.services.embedding_gateway.registry import register_provider
from app.common.services.embedding_gateway.service import EmbeddingProviderSpec
from app.hotlist.models import (
    HotItem,
    HotItemEmbedding,
    HotTopic,
    HotTopicEmbedding,
)  # noqa: F401  确保 hotlist 表注册到 Base.metadata
from app.hotlist.services import embedding_service

FAKE_DIM = 8


def fake_embed(request: EmbeddingRequest, api_key: str) -> EmbeddingResult:
    """确定性假向量：字符频率直方图 + 归一化，维度 FAKE_DIM。

    文本共享字符越多向量越接近，能体现「语义相似」关系（md5 是雪崩式的，不适合做假语义）。
    """
    vectors: list[list[float]] = []
    for text in request.texts:
        v = np.zeros(FAKE_DIM, dtype=np.float32)
        for ch in text:
            v[ord(ch) % FAKE_DIM] += 1.0
        norm = float(np.linalg.norm(v))
        if norm > 0:
            v = v / norm
        vectors.append(v.tolist())
    return EmbeddingResult(vectors=vectors, dimension=FAKE_DIM)


register_provider(
    EmbeddingProviderSpec(
        key="fake",
        label="Fake",
        description="test only",
        default_model="fake-model",
        default_dimension=FAKE_DIM,
        handler=fake_embed,
    )
)


@pytest.fixture()
def configured_db(db):
    """配置 fake embedding provider 并返回 db。"""
    rows = [
        ApiConfig(name="embedding_provider", value="fake"),
        ApiConfig(name="embedding_model", value="fake-model"),
        ApiConfig(name="embedding_dimension", value=str(FAKE_DIM)),
        ApiConfig(name="embedding_api_key", value="test-key"),
    ]
    for row in rows:
        db.add(row)
    db.commit()
    return db


# ---------------------------------------------------------------- 纯函数 ----


def test_build_item_text_normalizes_and_strips_html():
    text = embedding_service.build_item_text(
        "  AI  工具链  新闻 ", "<p>Agent runtime 与 MCP</p>", "github"
    )
    assert "Agent runtime 与 MCP" in text
    assert "<p>" not in text
    assert "  " not in text  # 连续空白已合并
    assert "来源：github" in text


def test_content_hash_stable():
    h1 = embedding_service.content_hash("item-v1", "abc")
    h2 = embedding_service.content_hash("item-v1", "abc")
    h3 = embedding_service.content_hash("item-v1", "abd")
    assert h1 == h2
    assert h1 != h3


def test_vector_codec_and_normalize():
    raw = embedding_service.encode_vector([3.0, 4.0])
    vec = embedding_service.decode_vector(raw)
    assert vec.shape == (2,)
    normalized = embedding_service.normalize_vector(vec)
    assert abs(float(np.linalg.norm(normalized)) - 1.0) < 1e-5
    # 零向量保护
    zero = embedding_service.normalize_vector(np.zeros(4, dtype=np.float32))
    assert np.linalg.norm(zero) == 0.0


# ---------------------------------------------------------------- 补算 ----


def test_ensure_item_embeddings_generates_and_skips(configured_db):
    item = HotItem(
        source_id="src1",
        title="AI 工具链新进展",
        summary="Agent runtime 与 MCP 集成",
        url="http://example.com/1",
        stat_date="2026-08-22",
    )
    configured_db.add(item)
    configured_db.commit()

    stat1 = embedding_service.ensure_item_embeddings(configured_db, [item])
    assert stat1["generated"] == 1
    row = configured_db.get(HotItemEmbedding, item.id)
    assert row is not None and row.status == "success"
    assert row.model_key.startswith("fake:")

    # 相同内容再次补算：跳过，不重复调用
    stat2 = embedding_service.ensure_item_embeddings(configured_db, [item])
    assert stat2["generated"] == 0 and stat2["skipped"] == 1


def test_ensure_topic_embedding_and_rank(configured_db):
    topic = HotTopic(
        name="AI 工具链",
        slug="ai-toolchain-test",
        interest_query="我想看 AI 工具链相关的新闻或知识",
    )
    configured_db.add(topic)
    configured_db.commit()
    assert embedding_service.ensure_topic_embedding(configured_db, topic) is True
    tv = embedding_service.get_topic_vector(configured_db, topic.id)
    assert tv is not None and tv.shape == (FAKE_DIM,)

    # 造两篇文章；手动注入受控向量：related ≈ 主题向量（高相关），unrelated 与主题向量正交（低相关）
    related = HotItem(
        source_id="src1", title="AI Agent 工具链", summary="MCP runtime",
        url="http://e.com/1", stat_date="2026-08-22", weight=1.0,
    )
    unrelated = HotItem(
        source_id="src1", title="某明星演唱会", summary="门票开售",
        url="http://e.com/2", stat_date="2026-08-22", weight=5.0,
    )
    configured_db.add_all([related, unrelated])
    configured_db.commit()

    related_vec = embedding_service.normalize_vector(
        tv * 0.95 + np.full(FAKE_DIM, 0.03, dtype=np.float32)
    )
    rng = np.random.default_rng(7)
    ortho = rng.normal(size=FAKE_DIM).astype(np.float32)
    ortho = ortho - (ortho @ tv) * tv
    unrelated_vec = embedding_service.normalize_vector(ortho)
    configured_db.add_all(
        [
            HotItemEmbedding(
                item_id=related.id, model_key="fake:fake-model:8",
                preprocess_version="item-v1", dimension=FAKE_DIM,
                content_hash="rel", vector=embedding_service.encode_vector(related_vec),
                status="success",
            ),
            HotItemEmbedding(
                item_id=unrelated.id, model_key="fake:fake-model:8",
                preprocess_version="item-v1", dimension=FAKE_DIM,
                content_hash="unrel", vector=embedding_service.encode_vector(unrelated_vec),
                status="success",
            ),
        ]
    )
    configured_db.commit()

    retrieved, missing = embedding_service.retrieve_semantic_candidates(
        configured_db, topic, [related, unrelated]
    )
    assert missing == 0
    assert len(retrieved) >= 1
    # 高相关文章应排在前面（final_score 降序），热点不能把无关文章救回来
    assert retrieved[0].item.id == related.id


def test_missing_embedding_counted(configured_db):
    topic = HotTopic(
        name="T", slug="t-missing-test", interest_query="需要检索的测试需求",
        similarity_threshold=-1.0,
    )
    configured_db.add(topic)
    configured_db.commit()
    embedding_service.ensure_topic_embedding(configured_db, topic)
    item = HotItem(
        source_id="s1", title="没有向量的文章", summary="x",
        url="http://e.com/x", stat_date="2026-08-22",
    )
    configured_db.add(item)
    configured_db.commit()
    # 不补向量，直接召回 → 缺失计数
    retrieved, missing = embedding_service.retrieve_semantic_candidates(
        configured_db, topic, [item]
    )
    assert missing == 1 and retrieved == []
