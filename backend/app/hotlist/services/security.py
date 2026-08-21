"""域名安全校验：抓取返回的 url / mobile_url 必须匹配源配置的期望域名，
防第三方接口（尤其公共 NewsNow 实例）被劫持或篡改后返回钓鱼链接。

移植自 TrendRadar crawler/fetcher.py::_check_domain_safety
(https://github.com/sansan0/TrendRadar)，
改动：
  - 从单文件内联函数独立成模块，供 crawl_service 对所有 adapter 通用调用；
  - 校验前先过一遍 normalize_url——arXiv Atom feed 的 entry.id 是 http://，
    normalize_url 会把 HTTPS_ONLY_HOSTS 里的已知站点升级成 https，不这样做的话
    arxiv 这种源每次都会被「非 HTTPS」误杀（entries 本身没问题，只是原始链接带的 scheme 不对）。
"""
from __future__ import annotations

from urllib.parse import urlparse

from app.common.utils.url import normalize_url
from app.hotlist.services.adapters.base import RawEntry


def _check_one(url: str, expected_domain: str) -> str | None:
    if not url:
        return None
    url = normalize_url(url)
    if not url:
        return None
    parsed = urlparse(url)
    # 用 hostname 而不是字符串包含，否则 https://baidu.com@evil.com 能绕过校验
    if parsed.scheme != "https":
        return f"{url}（非 HTTPS 或格式异常）"
    hostname = (parsed.hostname or "").lower()
    if (
        hostname != expected_domain
        and not hostname.endswith("." + expected_domain)
    ):
        return f"{url}（域名不匹配 {expected_domain}）"
    return None


def check_domain_safety(
    entries: list[RawEntry], expected_domain: str
) -> str | None:
    """校验全部条目的 url 与 mobile_url；任一条目任一字段不过即返回错误信息
    （调用方据此整源丢弃本批数据）。expected_domain 为空表示不校验。"""
    expected_domain = (expected_domain or "").strip().lower()
    if not expected_domain:
        return None
    for entry in entries:
        for url in (entry.url, entry.mobile_url):
            err = _check_one(url, expected_domain)
            if err:
                return err
    return None
