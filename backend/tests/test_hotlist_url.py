"""URL 归一化单测，重点覆盖微博 band_rank 那类平台动态参数（不去掉就没法按 URL 去重）。"""
from __future__ import annotations

from app.common.utils.url import normalize_url, url_hash


def test_normalize_url_strips_utm_params():
    assert normalize_url("https://example.com/a?utm_source=x&id=1") == "https://example.com/a?id=1"


def test_normalize_url_lowercases_scheme_and_host():
    assert normalize_url("HTTPS://Example.COM/a") == "https://example.com/a"


def test_normalize_url_strips_trailing_slash():
    assert normalize_url("https://example.com/a/") == "https://example.com/a"
    assert normalize_url("https://example.com/") == "https://example.com/"


def test_normalize_url_weibo_band_rank_and_refer_dropped():
    a = normalize_url("https://s.weibo.com/weibo?q=%23test%23&band_rank=1&Refer=top")
    b = normalize_url("https://s.weibo.com/weibo?q=%23test%23&band_rank=7&Refer=realtimehot")
    assert a == b  # 同一条热搜抓 N 次，band_rank/Refer 不同不该产生 N 条不同 URL


def test_normalize_url_arxiv_strips_version():
    a = normalize_url("http://arxiv.org/abs/2401.12345v1")
    b = normalize_url("https://arxiv.org/abs/2401.12345v3")
    assert a == b == "https://arxiv.org/abs/2401.12345"


def test_normalize_url_arxiv_upgrades_http_to_https():
    assert normalize_url("http://arxiv.org/abs/2401.12345").startswith("https://")


def test_normalize_url_huggingface_collapses_to_model_id():
    a = normalize_url("https://huggingface.co/models/org/model-name")
    b = normalize_url("https://huggingface.co/org/model-name/blob/main/README.md")
    assert a == b == "https://huggingface.co/org/model-name"


def test_normalize_url_empty_input():
    assert normalize_url("") == ""
    assert normalize_url(None) == ""  # type: ignore[arg-type]


def test_url_hash_is_stable_for_equivalent_urls():
    a = "https://s.weibo.com/weibo?q=x&band_rank=1"
    b = "https://s.weibo.com/weibo?q=x&band_rank=99"
    assert url_hash(a) == url_hash(b)


def test_url_hash_differs_for_different_urls():
    assert url_hash("https://example.com/a") != url_hash("https://example.com/b")
