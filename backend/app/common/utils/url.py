"""URL 归一化与去重键。

原先住在 app/ai_trending/services/base.py，ai_trending 下线时提到这里——
hotlist 的跨批次去重、xhs 的链接比对都要用，放在某个业务域里会被重复实现。

归一化规则（顺序有意义）：
  1. strip 空白；
  2. scheme + host 转小写；
  3. 已知仅支持 https 的站点把 http 抬成 https（跨源同内容不能因 scheme 不同就去重失败，
     典型例子：arXiv Atom feed 的 entry.id 是 http://，而 HF daily_papers 拼的是 https://）；
  4. 丢弃跟踪参数（DROP_QUERY_PARAMS + 所有 utm_* 前缀）；
  5. 去掉末尾 '/'（根路径除外）；
  6. 站点特例：arXiv 去版本号、HF 收敛到 {model_id}、微博去 band_rank 这类动态参数。
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# 归一化时丢弃的跟踪参数（utm_* 另外按前缀匹配）
DROP_QUERY_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "ref",
    "source",
    "from",
    "mc_cid",
    "mc_eid",
}

# 已知仅支持 https 的站点：http/https 统一为 https
HTTPS_ONLY_HOSTS = {
    "arxiv.org",
    "www.arxiv.org",
    "huggingface.co",
    "www.huggingface.co",
    "hf.co",
    "github.com",
    "www.github.com",
    "news.ycombinator.com",
    "infoq.cn",
    "www.infoq.cn",
    "36kr.com",
    "www.36kr.com",
}

# 平台专属的动态查询参数：同一条内容每次抓取值都会变，不去掉就没法按 URL 去重。
# 微博热搜链接带 band_rank（榜位）和 Refer（来源标记），抓 10 次就是 10 条不同 URL。
PLATFORM_DROP_PARAMS: dict[str, set[str]] = {
    "s.weibo.com": {"band_rank", "Refer", "refer", "topnav", "wvr"},
    "weibo.com": {"band_rank", "Refer", "refer"},
    "www.zhihu.com": {"utm_psn", "utm_id"},
    "www.toutiao.com": {"wid", "timestamp"},
    "www.thepaper.cn": {"commTag"},
}


def normalize_url(url: str) -> str:
    """按上面的规则归一化 URL；空串进空串出，解析失败时原样返回 strip 后的输入。"""
    url = (url or "").strip()
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url

    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = parts.path or ""
    fragment = parts.fragment

    host = netloc.split(":")[0]
    if scheme == "http" and host in HTTPS_ONLY_HOSTS:
        scheme = "https"

    # 丢弃跟踪参数 + 平台动态参数
    query = ""
    if parts.query:
        platform_drops = PLATFORM_DROP_PARAMS.get(host, set())
        kept: list[tuple[str, str]] = []
        for k, v in parse_qsl(parts.query, keep_blank_values=True):
            kl = k.lower()
            if kl.startswith("utm_") or kl in DROP_QUERY_PARAMS:
                continue
            if k in platform_drops or kl in {p.lower() for p in platform_drops}:
                continue
            kept.append((k, v))
        query = urlencode(kept)

    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    # arXiv：/abs/2401.12345v3 → /abs/2401.12345（版本号不同不算两条）
    if host in ("arxiv.org", "www.arxiv.org"):
        m = re.search(r"/(abs|pdf)/([0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?)", path)
        if m:
            base_id = re.sub(r"v\d+$", "", m.group(2))
            return urlunsplit((scheme, netloc, f"/abs/{base_id}", query, fragment))

    # HF：收敛到 huggingface.co/{model_id}，去掉 /blob/ /tree/ 等后缀
    if host in ("huggingface.co", "www.huggingface.co", "hf.co"):
        segs = [s for s in path.split("/") if s]
        if segs and segs[0] == "models":
            segs = segs[1:]
        for cut in ("blob", "tree", "resolve", "raw", "commit"):
            if cut in segs:
                segs = segs[: segs.index(cut)]
        path = "/" + "/".join(segs) if segs else ""
        return urlunsplit((scheme, netloc, path, "", fragment))

    return urlunsplit((scheme, netloc, path, query, fragment))


def url_hash(url: str) -> str:
    """归一化 URL 的 MD5，作为去重键（仅用于去重，不用于安全场景）。"""
    return hashlib.md5(normalize_url(url).encode("utf-8")).hexdigest()
