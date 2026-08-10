"""
SEC EDGAR 原始数据客户端：股票代码/CIK 映射、公司提交历史（含 8-K/10-Q/10-K/Form 3-5/
13D/13G 等，实测过 AAPL 的 submissions 接口确实同时包含这些）、XBRL Company Facts
（营收/净利/EPS/资产负债等标准化财务字段）。全部免费、不需要 API Key，唯一要求是带上
规范的 User-Agent（SEC 官方要求格式 "AppName contact@email"，没配置时用一个明确标识
本项目的默认值，不用空 UA 去请求——那样很容易被 SEC 拒绝或封）。

不从浏览器直接请求 SEC——所有请求都从后端发出，前端只拿后端整理好的数据。
"""
from __future__ import annotations

import time
from typing import Optional

import requests
from loguru import logger
from sqlalchemy.orm import Session

from app.common.services.gemini_config import get_config_value

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_COMPANY_CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{concept}.json"
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

_TIMEOUT = 20
_MAX_RETRIES = 3
_USER_AGENT_CONFIG_NAME = "sec_user_agent"
_DEFAULT_USER_AGENT = "workbench-fundamentals-module (unconfigured-contact@example.com)"

_TICKER_INDEX_TTL_SECONDS = 24 * 3600
_ticker_index_cache: Optional[dict] = None
_ticker_index_cached_at: float = 0.0


class SecError(Exception):
    pass


class SecNotFoundError(SecError):
    pass


def _user_agent(db: Session) -> str:
    configured = get_config_value(db, _USER_AGENT_CONFIG_NAME)
    return configured or _DEFAULT_USER_AGENT


def _request_json(db: Session, url: str) -> dict:
    headers = {"User-Agent": _user_agent(db), "Accept-Encoding": "gzip, deflate"}
    last_error: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(url, headers=headers, timeout=_TIMEOUT)
        except requests.RequestException as e:
            last_error = e
            time.sleep(0.5 * (2**attempt))
            continue

        if resp.status_code == 404:
            raise SecNotFoundError(f"SEC 接口未找到该资源: {url}")
        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = SecError(f"SEC 接口返回 {resp.status_code}")
            time.sleep(0.5 * (2**attempt))
            continue
        if resp.status_code != 200:
            raise SecError(f"SEC 接口报错（状态码 {resp.status_code}）: {resp.text[:200]}")

        try:
            return resp.json()
        except ValueError as e:
            raise SecError(f"SEC 接口返回非 JSON: {e}") from e

    raise SecError(f"请求 SEC 接口重试 {_MAX_RETRIES} 次后仍失败: {last_error}")


def _load_ticker_index(db: Session) -> dict:
    """symbol(大写) -> {cik, cik_str(10位补零), title}，SEC 官方维护的全市场代码索引，
    进程内缓存 24 小时（这份数据本身更新很慢，没必要每次请求都拉一遍 800KB 的 JSON）。"""
    global _ticker_index_cache, _ticker_index_cached_at
    if _ticker_index_cache is not None and (time.time() - _ticker_index_cached_at) < _TICKER_INDEX_TTL_SECONDS:
        return _ticker_index_cache

    raw = _request_json(db, _TICKERS_URL)
    index: dict = {}
    for entry in raw.values():
        symbol = str(entry.get("ticker", "")).upper()
        if not symbol:
            continue
        cik_int = entry.get("cik_str")
        index[symbol] = {
            "symbol": symbol,
            "cik": cik_int,
            "cik_str": str(cik_int).zfill(10),
            "title": entry.get("title", ""),
        }
    _ticker_index_cache = index
    _ticker_index_cached_at = time.time()
    logger.info(f"已刷新 SEC ticker->CIK 索引，共 {len(index)} 条")
    return index


def search_companies(db: Session, query: str, limit: int = 10) -> list[dict]:
    """按代码前缀精确/公司名子串模糊搜索，供前端搜索框使用。"""
    index = _load_ticker_index(db)
    query = query.strip().upper()
    if not query:
        return []

    exact = [v for k, v in index.items() if k == query]
    prefix = [v for k, v in index.items() if k != query and k.startswith(query)]
    name_match = [v for v in index.values() if query.lower() in v["title"].lower() and v not in exact and v not in prefix]

    results = [*exact, *prefix, *name_match]
    return results[:limit]


def get_cik(db: Session, symbol: str) -> Optional[dict]:
    index = _load_ticker_index(db)
    return index.get(symbol.strip().upper())


def get_submissions(db: Session, cik_str: str) -> dict:
    return _request_json(db, _SUBMISSIONS_URL.format(cik=cik_str))


def get_company_facts(db: Session, cik_str: str) -> dict:
    return _request_json(db, _COMPANY_FACTS_URL.format(cik=cik_str))


def get_company_concept(db: Session, cik_str: str, concept: str) -> dict:
    return _request_json(db, _COMPANY_CONCEPT_URL.format(cik=cik_str, concept=concept))


def fetch_filing_document(db: Session, cik: int, accession_no: str, filename: str) -> str:
    """拉一份具体披露文件的原始内容（Form 4 的 XML、8-K 的 htm 正文等），
    路径规则是 SEC 固定的 /Archives/edgar/data/{cik}/{accession无横杠}/{filename}。"""
    accession_no_dashes = accession_no.replace("-", "")
    url = f"{_ARCHIVES_BASE}/{cik}/{accession_no_dashes}/{filename}"
    headers = {"User-Agent": _user_agent(db)}
    try:
        resp = requests.get(url, headers=headers, timeout=_TIMEOUT)
    except requests.RequestException as e:
        raise SecError(f"请求 SEC 文件失败: {e}") from e
    if resp.status_code != 200:
        raise SecError(f"SEC 文件请求报错（状态码 {resp.status_code}）: {url}")
    return resp.text


def filing_index_url(cik: int, accession_no: str) -> str:
    accession_no_dashes = accession_no.replace("-", "")
    return f"{_ARCHIVES_BASE}/{cik}/{accession_no_dashes}/{accession_no}-index.htm"
