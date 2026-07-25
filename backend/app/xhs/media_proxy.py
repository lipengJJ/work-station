"""
小红书图片 / 视频 CDN 反防盗链代理。

小红书 CDN 会校验 Referer / sec-fetch-* 请求头，浏览器 <img>/<video> 直接跨域请求
拿到的 Referer 是我们自己网站的地址而不是 xiaohongshu.com，会被直接拒绝（通常 403）。
这里在服务端用和 xhs_utils/data_util.py 下载素材时完全一样的请求头转发一次。

只允许转发小红书自己的 CDN 域名（xhscdn.com 及其子域），避免这个接口变成一个
可以访问任意地址的开放代理（SSRF）。注意小红书笔记里的图片地址经常是 http（不是
https），这里按域名白名单放行、不看协议——SSRF 风险来自目标主机而不是协议本身。
"""
from typing import Optional
from urllib.parse import urlparse

import requests

from xhs_utils.http_util import REQUEST_TIMEOUT
from xhs_utils.xhs_util import get_common_headers

_ALLOWED_HOST_SUFFIX = "xhscdn.com"


def is_allowed_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname or ""
    return host == _ALLOWED_HOST_SUFFIX or host.endswith("." + _ALLOWED_HOST_SUFFIX)


def _headers(range_header: Optional[str]):
    headers = dict(get_common_headers())
    headers["accept"] = "image/avif,image/webp,image/apng,image/svg+xml,image/*,video/*,*/*;q=0.8"
    headers["sec-fetch-dest"] = "image"
    headers["sec-fetch-mode"] = "no-cors"
    headers["sec-fetch-site"] = "cross-site"
    if range_header:
        headers["Range"] = range_header
    return headers


def fetch(url: str, range_header: Optional[str] = None) -> requests.Response:
    resp = requests.get(url, headers=_headers(range_header), timeout=REQUEST_TIMEOUT, stream=True)
    resp.raise_for_status()
    return resp
