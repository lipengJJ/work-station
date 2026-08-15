"""
xhs 爬取客户端：搜索 / 笔记详情 / 评论（一二级）等爬取链路 API。

从旧 pc_apis.py 迁移而来，方法签名完全兼容（cookies_str / proxies 等参数不变，
统一返回 (success, msg, res_json) 三元组），底层改用 XhsRequestClient 统一请求层：

- 网络错误 / 风控限流自动退避重试（次数见 xhs_request_client 常量）
- 登录态失效抛 XhsAuthError、内容不存在抛 XhsNotFoundError（不重试，向上传播，
  由 spider/tasks 按类型决策——单篇 NotFound 跳过、Auth 终止任务提示重新登录）
- 其他业务失败返回 (False, msg, res_json)

旧 pc_apis.py 保留为遗留实现（其余非爬取链路方法继续使用），爬取链方法已委托本类，
避免同一套逻辑出现两份实现后漂移。

注意：评论相关方法（get_note_out_comment / get_note_all_out_comment /
get_note_inner_comment / get_note_all_inner_comment / get_note_all_comment）已弃用——
评论获取已切换为 Playwright 页面级 DOM 爬取（services/client/page_crawler.py，
spider.spider_note_comments 不再调用 API 评论接口）。这些方法仅保留作历史参考。
"""

from __future__ import annotations

import random
import re
import time
import urllib.parse
from typing import Any, Optional

import requests

from app.xhs.services.utils.http_util import REQUEST_TIMEOUT
from app.xhs.services.utils.xhs_util import (
    generate_search_id,
    generate_x_rap_param,
    get_common_headers,
)

from ..xhs_errors import XhsError
from .xhs_request_client import XhsRequestClient, paced_sleep

# 以下常量仅服务于已弃用的评论 API 链路（get_note_all_comment 等），现保留作历史参考。
# 评论获取已改用 Playwright 页面级爬取（page_crawler.py），滚动延时由 page_crawler 的
# SCROLL_PAUSE + 随机抖动控制。
# 评论翻页 / 逐条展开二级评论时的默认请求间隔（秒），可通过 interval_seconds 参数覆盖，实现限速。
# 1.0s + 随机抖动：防封控与速度的中间档（1.2s 过保守，0.7s 实测偏激进）。
COMMENT_PAGE_INTERVAL_SECONDS = 1.0
# 二级评论并发展开的最大并发数：并发 >1 会明显提高评论接口的触发概率，保持 1（串行）。
SUB_COMMENT_CONCURRENCY = 1
# 一级评论没有二级互动时，正文短于该长度视为无意义评论（"沙发"、表情等），直接丢弃；文字较多则保留
TRIVIAL_COMMENT_MIN_LENGTH = 20


def _comment_text(comment: dict) -> str:
    return str(comment.get("content") or comment.get("text") or comment.get("desc") or "")


def _is_trivial_top_comment(comment: dict) -> bool:
    try:
        sub_count = int(comment.get("sub_comment_count") or 0)
    except (TypeError, ValueError):
        sub_count = 0
    if sub_count > 0:
        return False
    return len(_comment_text(comment).strip()) < TRIVIAL_COMMENT_MIN_LENGTH


def _get_query_params(parsed_url: urllib.parse.ParseResult) -> dict:
    return {
        key: values[-1] if values else ""
        for key, values in urllib.parse.parse_qs(parsed_url.query, keep_blank_values=True).items()
    }


class XhsCrawlerClient:
    """小红书数据爬取客户端（搜索 / 详情 / 评论 / 媒体 URL）"""

    def __init__(self, base_url: str = "https://edith.xiaohongshu.com"):
        self.base_url = base_url
        self._request = XhsRequestClient(base_url=base_url)

    # ------------------------------------------------------------ 笔记详情 ----

    def get_note_info(self, url: str, cookies_str: str, proxies: dict = None):
        """
        获取笔记的详细
        :param url: 你想要获取的笔记的url
        :param cookies_str: 你的cookies
        :param xsec_source: 你的xsec_source 默认为pc_search pc_user pc_feed
        返回笔记的详细
        """
        res_json = None
        try:
            urlParse = urllib.parse.urlparse(url)
            note_id = urlParse.path.split("/")[-1]
            kv_dist = _get_query_params(urlParse)
            api = "/api/sns/web/v1/feed"
            data = {
                "source_note_id": note_id,
                "image_formats": ["jpg", "webp", "avif"],
                "extra": {"need_body_topic": "1"},
                "xsec_source": kv_dist.get("xsec_source", "pc_search"),
                "xsec_token": kv_dist.get("xsec_token", ""),
            }
            success, msg, res_json = self._request.request(
                "POST", api, cookies_str, data=data, proxies=proxies,
                extra_headers={"x-rap-param": generate_x_rap_param(api, data), "xy-direction": "13"},
            )
        except XhsError:
            raise
        except Exception as e:
            return False, str(e), res_json
        return success, msg, res_json

    # ------------------------------------------------------------ 搜索 ----

    def get_search_keyword(self, word: str, cookies_str: str, proxies: dict = None):
        """获取搜索关键词"""
        res_json = None
        try:
            api = "/api/sns/web/v1/search/recommend"
            params = {"keyword": urllib.parse.quote(word)}
            success, msg, res_json = self._request.request("GET", api, cookies_str, params=params, proxies=proxies)
        except XhsError:
            raise
        except Exception as e:
            return False, str(e), res_json
        return success, msg, res_json

    def search_note(self, query: str, cookies_str: str, page=1, sort_type_choice=0, note_type=0,
                    note_time=0, note_range=0, pos_distance=0, geo="", search_id=None, proxies: dict = None):
        """
        获取搜索笔记的结果
        :param query 搜索的关键词
        :param page 搜索的页数
        :param sort_type_choice 排序方式 0 综合排序, 1 最新, 2 最多点赞, 3 最多评论, 4 最多收藏
        :param note_type 笔记类型 0 不限, 1 视频笔记, 2 普通笔记
        :param note_time 笔记时间 0 不限, 1 一天内, 2 一周内天, 3 半年内
        :param note_range 笔记范围 0 不限, 1 已看过, 2 未看过, 3 已关注
        :param pos_distance 位置距离 0 不限, 1 同城, 2 附近 指定这个必须要指定 geo
        """
        res_json = None
        sort_type = "general"
        if sort_type_choice == 1:
            sort_type = "time_descending"
        elif sort_type_choice == 2:
            sort_type = "popularity_descending"
        elif sort_type_choice == 3:
            sort_type = "comment_descending"
        elif sort_type_choice == 4:
            sort_type = "collect_descending"
        filter_note_type = "不限"
        if note_type == 1:
            filter_note_type = "视频笔记"
        elif note_type == 2:
            filter_note_type = "普通笔记"
        filter_note_time = "不限"
        if note_time == 1:
            filter_note_time = "一天内"
        elif note_time == 2:
            filter_note_time = "一周内"
        elif note_time == 3:
            filter_note_time = "半年内"
        filter_note_range = "不限"
        if note_range == 1:
            filter_note_range = "已看过"
        elif note_range == 2:
            filter_note_range = "未看过"
        elif note_range == 3:
            filter_note_range = "已关注"
        filter_pos_distance = "不限"
        if pos_distance == 1:
            filter_pos_distance = "同城"
        elif pos_distance == 2:
            filter_pos_distance = "附近"
        if geo:
            import json
            geo = json.dumps(geo, separators=(",", ":"))

        try:
            api = "/api/sns/web/v1/search/notes"
            data = {
                "keyword": query,
                "page": page,
                "page_size": 20,
                "search_id": search_id or generate_search_id(),
                "sort": "general",
                "note_type": 0,
                "ext_flags": [],
                "filters": [
                    {"tags": [sort_type], "type": "sort_type"},
                    {"tags": [filter_note_type], "type": "filter_note_type"},
                    {"tags": [filter_note_time], "type": "filter_note_time"},
                    {"tags": [filter_note_range], "type": "filter_note_range"},
                    {"tags": [filter_pos_distance], "type": "filter_pos_distance"},
                ],
                "geo": geo,
                "image_formats": ["jpg", "webp", "avif"],
            }
            success, msg, res_json = self._request.request(
                "POST", api, cookies_str, data=data, proxies=proxies,
                extra_headers={"x-rap-param": generate_x_rap_param(api, data)},
            )
        except XhsError:
            raise
        except Exception as e:
            return False, str(e), res_json
        return success, msg, res_json

    def search_some_note(self, query: str, require_num: int, cookies_str: str, sort_type_choice=0,
                         note_type=0, note_time=0, note_range=0, pos_distance=0, geo="", proxies: dict = None):
        """
        指定数量搜索笔记，设置排序方式和笔记类型和笔记数量
        :param require_num 搜索的数量
        """
        page = 1
        note_list: list = []
        root_search_id = generate_search_id()
        try:
            while True:
                search_id = generate_search_id(root_search_id)
                success, msg, res_json = self.search_note(
                    query, cookies_str, page, sort_type_choice, note_type,
                    note_time, note_range, pos_distance, geo, search_id, proxies,
                )
                if not success:
                    raise RuntimeError(msg)
                if "items" not in res_json["data"]:
                    break
                notes = res_json["data"]["items"]
                note_list.extend(notes)
                page += 1
                if len(note_list) >= require_num or not res_json["data"]["has_more"]:
                    break
                # 搜索翻页也限速（防封控优先）：每页间隔带随机抖动
                paced_sleep(0.8)
        except XhsError:
            raise
        except Exception as e:
            return False, str(e), note_list
        if len(note_list) > require_num:
            note_list = note_list[:require_num]
        return True, "success", note_list

    # ------------------------------------------------------------ 评论 ----

    def get_note_out_comment(self, note_id: str, cursor: str, xsec_token: str, cookies_str: str, proxies: dict = None):
        # @deprecated 已改用 Playwright 页面级爬取（page_crawler.py），评论获取不再走 API 直连
        """获取指定位置的笔记一级评论"""
        res_json = None
        try:
            api = "/api/sns/web/v2/comment/page"
            params = {
                "note_id": note_id,
                "cursor": cursor,
                "top_comment_id": "",
                "image_formats": "jpg,webp,avif",
                "xsec_token": xsec_token,
            }
            success, msg, res_json = self._request.request("GET", api, cookies_str, params=params, proxies=proxies)
        except XhsError:
            raise
        except Exception as e:
            return False, str(e), res_json
        return success, msg, res_json

    def get_note_all_out_comment(self, note_id: str, xsec_token: str, cookies_str: str, proxies: dict = None,
                                 interval_seconds: float = None, max_comments: int = None,
                                 on_page: Optional[Any] = None):
        # @deprecated 已改用 Playwright 页面级爬取（page_crawler.py），评论获取不再走 API 直连
        """
        获取笔记的全部一级评论
        没有二级互动且正文很短的一级评论会被直接丢弃（视为无意义评论），正文较长的仍会保留
        :param interval_seconds 翻页请求间隔（秒），用于限速，默认 COMMENT_PAGE_INTERVAL_SECONDS
        :param max_comments 最多保留的一级评论数量，达到后停止翻页（None 表示不限制，抓取全部）
        :param on_page 可选回调 on_page(note_id, 本页过滤后的评论列表)，边翻页边通知（流式存储用）
        """
        interval = COMMENT_PAGE_INTERVAL_SECONDS if interval_seconds is None else interval_seconds
        cursor = ""
        note_out_comment_list: list = []
        try:
            first_page = True
            while True:
                if not first_page:
                    paced_sleep(interval)
                first_page = False
                success, msg, res_json = self.get_note_out_comment(note_id, cursor, xsec_token, cookies_str, proxies)
                if not success:
                    raise RuntimeError(msg)
                page_comments = res_json["data"]["comments"]
                kept = [c for c in page_comments if not _is_trivial_top_comment(c)]
                note_out_comment_list.extend(kept)
                if on_page is not None:
                    try:
                        on_page(note_id, kept)
                    except Exception:
                        pass  # 回调失败不影响主流程
                if max_comments is not None and len(note_out_comment_list) >= max_comments:
                    note_out_comment_list = note_out_comment_list[:max_comments]
                    break
                if "cursor" in res_json["data"]:
                    cursor = str(res_json["data"]["cursor"])
                else:
                    break
                if len(page_comments) == 0 or not res_json["data"]["has_more"]:
                    break
        except XhsError:
            raise
        except Exception as e:
            return False, str(e), note_out_comment_list
        return True, "success", note_out_comment_list

    def get_note_inner_comment(self, comment: dict, cursor: str, xsec_token: str, cookies_str: str, proxies: dict = None):
        # @deprecated 已改用 Playwright 页面级爬取（page_crawler.py），评论获取不再走 API 直连
        """获取指定位置的笔记二级评论"""
        res_json = None
        try:
            api = "/api/sns/web/v2/comment/sub/page"
            params = {
                "note_id": comment["note_id"],
                "root_comment_id": comment["id"],
                "num": "10",
                "cursor": cursor,
                "image_formats": "jpg,webp,avif",
                "top_comment_id": "",
                "xsec_token": xsec_token,
            }
            success, msg, res_json = self._request.request("GET", api, cookies_str, params=params, proxies=proxies)
        except XhsError:
            raise
        except Exception as e:
            return False, str(e), res_json
        return success, msg, res_json

    def get_note_all_inner_comment(self, comment: dict, xsec_token: str, cookies_str: str, proxies: dict = None,
                                   interval_seconds: float = None, on_page: Optional[Any] = None):
        # @deprecated 已改用 Playwright 页面级爬取（page_crawler.py），评论获取不再走 API 直连
        """获取笔记的全部二级评论"""
        interval = COMMENT_PAGE_INTERVAL_SECONDS if interval_seconds is None else interval_seconds
        try:
            if not comment.get("sub_comment_has_more"):
                return True, "success", comment
            cursor = comment.get("sub_comment_cursor", "")
            inner_comment_list: list = []
            first_page = True
            while True:
                if not first_page:
                    paced_sleep(interval)
                first_page = False
                success, msg, res_json = self.get_note_inner_comment(comment, cursor, xsec_token, cookies_str, proxies)
                if not success:
                    raise RuntimeError(msg)
                comments = res_json["data"]["comments"]
                inner_comment_list.extend(comments)
                if on_page is not None:
                    try:
                        on_page(comment.get("note_id"), comments)
                    except Exception:
                        pass
                if "cursor" in res_json["data"]:
                    cursor = str(res_json["data"]["cursor"])
                else:
                    break
                if not res_json["data"]["has_more"]:
                    break
            comment.setdefault("sub_comments", []).extend(inner_comment_list)
        except XhsError:
            raise
        except Exception as e:
            return False, str(e), comment
        return True, "success", comment

    def get_note_all_comment(self, url: str, cookies_str: str, proxies: dict = None,
                             interval_seconds: float = None, max_comments: int = None,
                             on_page: Optional[Any] = None):
        # @deprecated 已改用 Playwright 页面级爬取（page_crawler.py），评论获取不再走 API 直连。
        # spider.spider_note_comments 已完全替换为 XhsPageCrawler.crawl_note_comments，
        # 本方法仅保留作历史参考，不再被生产链路调用。
        """
        获取一篇文章的所有评论（一级 + 二级）
        :param interval_seconds 评论请求间隔（秒），用于限速，默认 COMMENT_PAGE_INTERVAL_SECONDS
        :param max_comments 最多保留的一级评论数量，达到后停止翻页也不再展开更多二级评论
        :param on_page 可选回调 on_page(note_id, 评论列表)，边翻页边通知（流式存储用）
        """
        interval = COMMENT_PAGE_INTERVAL_SECONDS if interval_seconds is None else interval_seconds
        out_comment_list: list = []
        try:
            url_parse = urllib.parse.urlparse(url)
            note_id = url_parse.path.split("/")[-1]
            kv_dist = _get_query_params(url_parse)
            xsec_token = kv_dist.get("xsec_token", "")
            success, msg, out_comment_list = self.get_note_all_out_comment(
                note_id, xsec_token, cookies_str, proxies,
                interval_seconds=interval, max_comments=max_comments, on_page=on_page,
            )
            if not success:
                raise RuntimeError(msg)
            # 一级评论已到手，并发展开二级评论（限流重试耗尽等单条失败跳过，不丢已抓数据）。
            # on_page 回调在 worker 线程里只做收集（线程安全 list），展开完由主线程按序统一
            # 触发，保证流式落库仍走调用方的线程（SQLAlchemy session 非线程安全）。
            from concurrent.futures import ThreadPoolExecutor
            pending_pages: list = []
            import threading
            _lock = threading.Lock()

            def _collect_pages(n_id: str, batch: list) -> None:
                with _lock:
                    pending_pages.append((n_id, batch))

            def _expand(comment_item: dict) -> None:
                if comment_item.get("sub_comment_has_more"):
                    paced_sleep(interval)
                inner_success, inner_msg, _ = self.get_note_all_inner_comment(
                    comment_item, xsec_token, cookies_str, proxies,
                    interval_seconds=interval, on_page=_collect_pages,
                )
                if not inner_success:
                    import logging
                    logging.getLogger(__name__).warning(
                        f"评论 {comment_item.get('id')} 展开二级评论失败，跳过: {inner_msg}"
                    )

            expandable = [c for c in out_comment_list if c.get("sub_comment_has_more")]
            if expandable:
                with ThreadPoolExecutor(max_workers=SUB_COMMENT_CONCURRENCY) as ex:
                    list(ex.map(_expand, expandable))
            if on_page is not None:
                for n_id, batch in pending_pages:
                    try:
                        on_page(n_id, batch)
                    except Exception:
                        pass
        except XhsError:
            raise
        except Exception as e:
            return False, str(e), out_comment_list
        return True, "success", out_comment_list

    # ------------------------------------------------------------ 用户 ----

    def get_user_self_info(self, cookies_str: str, proxies: dict = None):
        """获取用户自己的信息（也用作登录态心跳探测：返回 True 说明 cookie 有效）"""
        res_json = None
        try:
            api = "/api/sns/web/v1/user/selfinfo"
            success, msg, res_json = self._request.request("GET", api, cookies_str, proxies=proxies)
        except XhsError:
            raise
        except Exception as e:
            return False, str(e), res_json
        return success, msg, res_json

    def get_user_self_info2(self, cookies_str: str, proxies: dict = None):
        """获取用户自己的信息（v2）"""
        res_json = None
        try:
            api = "/api/sns/web/v2/user/me"
            success, msg, res_json = self._request.request("GET", api, cookies_str, proxies=proxies)
        except XhsError:
            raise
        except Exception as e:
            return False, str(e), res_json
        return success, msg, res_json

    def get_user_note_info(self, user_id: str, cursor: str, cookies_str: str, xsec_token="", xsec_source="", proxies: dict = None):
        """获取用户指定位置的笔记"""
        res_json = None
        try:
            api = "/api/sns/web/v1/user_posted"
            params = {
                "num": "30",
                "cursor": cursor,
                "user_id": user_id,
                "image_formats": "jpg,webp,avif",
                "xsec_token": xsec_token,
                "xsec_source": xsec_source,
            }
            success, msg, res_json = self._request.request("GET", api, cookies_str, params=params, proxies=proxies)
        except XhsError:
            raise
        except Exception as e:
            return False, str(e), res_json
        return success, msg, res_json

    def get_user_all_notes(self, user_url: str, cookies_str: str, proxies: dict = None):
        """获取用户所有笔记"""
        cursor = ""
        note_list: list = []
        try:
            url_parse = urllib.parse.urlparse(user_url)
            user_id = url_parse.path.split("/")[-1]
            kv_dist = _get_query_params(url_parse)
            xsec_token = kv_dist.get("xsec_token", "")
            xsec_source = kv_dist.get("xsec_source", "pc_search")
            while True:
                success, msg, res_json = self.get_user_note_info(
                    user_id, cursor, cookies_str, xsec_token, xsec_source, proxies,
                )
                if not success:
                    raise RuntimeError(msg)
                notes = res_json["data"]["notes"]
                if "cursor" in res_json["data"]:
                    cursor = str(res_json["data"]["cursor"])
                else:
                    break
                note_list.extend(notes)
                if len(notes) == 0 or not res_json["data"]["has_more"]:
                    break
        except XhsError:
            raise
        except Exception as e:
            return False, str(e), note_list
        return True, "success", note_list

    # ------------------------------------------------------------ 媒体 ----

    @staticmethod
    def get_note_no_water_video(note_id: str):
        """获取笔记无水印视频"""
        video_addr = None
        try:
            headers = get_common_headers()
            url = f"https://www.xiaohongshu.com/explore/{note_id}"
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            video_addr = re.findall(r'<meta name="og:video" content="(.*?)">', response.text)[0]
        except Exception as e:
            return False, str(e), video_addr
        return True, "成功", video_addr

    @staticmethod
    def get_note_no_water_img(img_url: str):
        """获取笔记无水印图片"""
        new_url = None
        try:
            # 新版图片资源优先保留 notes_pre_post token，使用 ci.xiaohongshu.com 输出 JPEG
            if "notes_pre_post/" in img_url:
                token = "notes_pre_post/" + img_url.split("notes_pre_post/", 1)[1].split("!", 1)[0].split("?", 1)[0]
                new_url = f"https://ci.xiaohongshu.com/{token}?imageView2/format/jpeg"
            elif "spectrum" in img_url:
                token = "/".join(img_url.split("/")[-2:]).split("!", 1)[0].split("?", 1)[0]
                new_url = f"https://ci.xiaohongshu.com/{token}?imageView2/format/jpeg"
            elif ".jpg" in img_url:
                token = "/".join(img_url.split("/")[-3:]).split("!", 1)[0].split("?", 1)[0]
                new_url = f"https://ci.xiaohongshu.com/{token}?imageView2/format/jpeg"
            else:
                token = img_url.split("/")[-1].split("!", 1)[0].split("?", 1)[0]
                new_url = f"https://ci.xiaohongshu.com/{token}?imageView2/format/jpeg"
        except Exception as e:
            return False, str(e), new_url
        return True, "成功", new_url
