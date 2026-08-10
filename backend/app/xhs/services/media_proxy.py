"""
小红书图片 / 视频 CDN 反防盗链代理。

小红书 CDN 会校验 Referer / sec-fetch-* 请求头，浏览器 <img>/<video> 直接跨域请求
拿到的 Referer 是我们自己网站的地址而不是 xiaohongshu.com，会被直接拒绝（通常 403）。
这里在服务端用和 services/utils/data_util.py 下载素材时完全一样的请求头转发一次。

只允许转发小红书自己的 CDN 域名（xhscdn.com 及其子域），避免这个接口变成一个
可以访问任意地址的开放代理（SSRF）。注意小红书笔记里的图片地址经常是 http（不是
https），这里按域名白名单放行、不看协议——SSRF 风险来自目标主机而不是协议本身。

实测确认（2026-08-03）：小红书 CDN 的图片/视频 URL 是有时效性的签名链接，即使带上
和下载素材时完全一样的请求头，采集完约一天后原 URL 也会被 CDN 直接拒绝返回 403
（而不是过期跳到别的地址）——这就是 TODO.md"小红书笔记数据全局去重缓存"里当时
标注为"待验证"的风险点，现在验证结果是：确实会过期。真正的解法不是想办法刷新
签名（拿不到新签名），而是优先把本地已经下载好的素材文件直接发回去，只有真的没有
本地副本（比如采集时 save_choice 选的是纯 excel，没下载素材）才退回现场请求远程
CDN，那种情况下 URL 是否已经过期就只能听天由命了。

找本地文件不查全局笔记缓存（XhsNote）反推"这个 URL 是图集第几张"——这张表是后来
才加的，这个功能上线前采集的笔记（比如本来就在 XhsTaskExtra.result_json 里、从没
被读进过全局缓存的旧任务）会查不到，导致本地明明有文件却还是走了远程请求。改成
前端直接告诉后端"这是第几张图 / 封面 / 正文视频"（download_media() 本来就是按这个
位置信息命名文件的，不是按 URL 内容），不依赖任何数据库查询，新旧任务都能命中。
"""
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

from app.xhs.services.utils.http_util import REQUEST_TIMEOUT
from app.xhs.services.utils.xhs_util import get_common_headers

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


_VALID_KINDS = {"image": "jpg", "video": "mp4", "cover": "jpg"}

# 项目根目录下的 storage/xhs_tasks（早期目录结构留下的历史数据），见下方注释
_LEGACY_STORAGE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "storage" / "xhs_tasks"


def find_local_media_file(note_id: str, kind: str, index: Optional[int]) -> Optional[Path]:
    """
    给定 note_id + 素材种类（image 第几张图集图 / video 正文视频 / cover 视频封面），
    在本地已下载的素材目录里找对应文件。文件名是 download_media() 按这个位置信息
    命名的（image_{index}.jpg / cover.jpg / video.mp4），前端本来就知道自己是在渲染
    "第几张图/封面/视频"，不需要后端反查任何数据库就能算出预期文件名。

    笔记可能被多个采集任务各自下载过一份（媒体去重是以后阶段的事，见 TODO.md），
    这里按 note_id 全局搜索，命中第一份可用副本就返回。

    历史遗留：早期代码把 services 直接放在 app/ 下（现在挪进了 app/xhs/services/
    子包），STORAGE_DIR 是按 __file__ 相对路径算的，多套一层子包就导致这个路径
    默默往下多挪了一层——旧任务下载的素材还留在项目根目录的 storage/xhs_tasks/
    下，新代码只看 app/storage/xhs_tasks/，就找不到。而且这期间数据库还被重建过，
    task_id 也不是一一对应的（同一个数字在两处目录下对应的是完全不同的笔记），
    所以不能简单按 task_id 合并两个目录；但按 note_id（全局唯一）搜索不受影响，
    这里把旧目录也加进来兜底搜一遍。
    """
    from app.xhs.services.tasks import STORAGE_DIR

    ext = _VALID_KINDS.get(kind)
    if ext is None:
        return None
    if kind == "image":
        if index is None:
            return None
        stem = f"image_{index}"
    else:
        stem = kind

    # 目录结构：{task_id}/media/{nickname}_{user_id}/{title}_{note_id}/{stem}.{ext}
    for base in (STORAGE_DIR, _LEGACY_STORAGE_DIR):
        for candidate in base.glob(f"*/media/*/*_{note_id}/{stem}.{ext}"):
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
    return None
