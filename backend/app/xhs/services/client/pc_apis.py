# encoding: utf-8
import json
import random
import re
import time
import urllib
import requests
from app.xhs.services.utils.xhs_util import splice_str, generate_request_params, generate_x_b3_traceid, generate_search_id, generate_search_request_id, generate_x_rap_param, get_common_headers
from app.xhs.services.utils.http_util import REQUEST_TIMEOUT
from loguru import logger

"""
    获小红书的api（遗留实现）。
    :param cookies_str: 你的cookies

    说明：搜索/笔记详情/评论/用户主页等"数据爬取链路"方法已迁移到
    xhs_crawler_client.XhsCrawlerClient（统一请求层 + 异常分类 + 限流重试），
    本类中这些方法改为委托，避免同一套逻辑两份实现后漂移；
    其余方法（首页 feed/消息/互动等）保留原实现。
"""

# 小红书风控/限流响应码：接口层 success 仍为 true，但 data 为空，需当作失败处理并退避重试
RATE_LIMIT_CODES = {300013}
RATE_LIMIT_MAX_RETRIES = 3
RATE_LIMIT_BACKOFF_SECONDS = 3
# 评论翻页 / 逐条展开二级评论时的默认请求间隔（秒），可通过 interval_seconds 参数覆盖，实现限速
COMMENT_PAGE_INTERVAL_SECONDS = 1.0
# 一级评论没有二级互动时，正文短于该长度视为无意义评论（"沙发"、表情等），直接丢弃；文字较多则保留
TRIVIAL_COMMENT_MIN_LENGTH = 20


def _log_api_error(error):
    logger.exception(f'XHS PC API request failed: {error}')
    return str(error)


def _is_rate_limited(msg: str) -> bool:
    return bool(msg) and '频繁' in msg


def _paced_sleep(interval: float) -> None:
    # 固定间隔的请求节奏本身就是风控识别爬虫的特征之一，加随机抖动让节奏更像真人操作
    if interval > 0:
        time.sleep(interval + random.uniform(0, interval * 0.5))


def _comment_text(comment: dict) -> str:
    return str(comment.get('content') or comment.get('text') or comment.get('desc') or '')


def _is_trivial_top_comment(comment: dict) -> bool:
    try:
        sub_count = int(comment.get('sub_comment_count') or 0)
    except (TypeError, ValueError):
        sub_count = 0
    if sub_count > 0:
        return False
    return len(_comment_text(comment).strip()) < TRIVIAL_COMMENT_MIN_LENGTH


def _request_with_rate_limit_retry(request_fn):
    """
        执行 request_fn，命中限流时按指数退避 + 抖动重试
        request_fn: () -> (success, msg, res_json)
    """
    retries = 0
    while True:
        success, msg, res_json = request_fn()
        if success or not _is_rate_limited(msg) or retries >= RATE_LIMIT_MAX_RETRIES:
            return success, msg, res_json
        retries += 1
        backoff = RATE_LIMIT_BACKOFF_SECONDS * (2 ** (retries - 1)) + random.uniform(0, 1)
        logger.warning(f"XHS API 触发限流（{msg}），{backoff:.1f}s 后重试（{retries}/{RATE_LIMIT_MAX_RETRIES}）")
        time.sleep(backoff)


def _get_query_params(parsed_url):
    return {
        key: values[-1] if values else ''
        for key, values in urllib.parse.parse_qs(parsed_url.query, keep_blank_values=True).items()
    }


class XHS_Apis():
    def __init__(self):
        self.base_url = "https://edith.xiaohongshu.com"
        # 爬取链方法已迁移到 XhsCrawlerClient（统一请求层+异常分类），这里委托避免双实现漂移
        from app.xhs.services.client.xhs_crawler_client import XhsCrawlerClient
        self._crawler = XhsCrawlerClient(base_url=self.base_url)

    def get_homefeed_all_channel(self, cookies_str: str, proxies: dict = None):
        """
            获取主页的所有频道
            返回主页的所有频道
        """
        res_json = None
        try:
            api = "/api/sns/web/v1/homefeed/category"
            headers, cookies, data = generate_request_params(cookies_str, api, '', 'GET')
            response = requests.get(self.base_url + api, headers=headers, cookies=cookies, proxies=proxies, timeout=REQUEST_TIMEOUT)
            res_json = response.json()
            success, msg = res_json["success"], res_json["msg"]
        except Exception as e:
            success = False
            msg = _log_api_error(e)
        return success, msg, res_json

    def get_homefeed_recommend(self, category, cursor_score, refresh_type, note_index, cookies_str: str, proxies: dict = None):
        """
            获取主页推荐的笔记
            :param category: 你想要获取的频道
            :param cursor_score: 你想要获取的笔记的cursor
            :param refresh_type: 你想要获取的笔记的刷新类型
            :param note_index: 你想要获取的笔记的index
            :param cookies_str: 你的cookies
            返回主页推荐的笔记
        """
        res_json = None
        try:
            api = f"/api/sns/web/v1/homefeed"
            data = {
                "cursor_score": cursor_score,
                "num": 20,
                "refresh_type": refresh_type,
                "note_index": note_index,
                "unread_begin_note_id": "",
                "unread_end_note_id": "",
                "unread_note_count": 0,
                "category": category,
                "search_key": "",
                "need_num": 10,
                "image_formats": [
                    "jpg",
                    "webp",
                    "avif"
                ],
                "need_filter_image": False
            }
            headers, cookies, trans_data = generate_request_params(cookies_str, api, data, 'POST')
            response = requests.post(self.base_url + api, headers=headers, data=trans_data, cookies=cookies, proxies=proxies, timeout=REQUEST_TIMEOUT)
            res_json = response.json()
            success, msg = res_json["success"], res_json["msg"]
        except Exception as e:
            success = False
            msg = _log_api_error(e)
        return success, msg, res_json

    def get_homefeed_recommend_by_num(self, category, require_num, cookies_str: str, proxies: dict = None):
        """
            根据数量获取主页推荐的笔记
            :param category: 你想要获取的频道
            :param require_num: 你想要获取的笔记的数量
            :param cookies_str: 你的cookies
            根据数量返回主页推荐的笔记
        """
        cursor_score, refresh_type, note_index = "", 1, 0
        note_list = []
        try:
            while True:
                success, msg, res_json = self.get_homefeed_recommend(category, cursor_score, refresh_type, note_index, cookies_str, proxies)
                if not success:
                    raise Exception(msg)
                if "items" not in res_json["data"]:
                    break
                notes = res_json["data"]["items"]
                note_list.extend(notes)
                cursor_score = res_json["data"]["cursor_score"]
                refresh_type = 3
                note_index += 20
                if len(note_list) > require_num:
                    break
        except Exception as e:
            success = False
            msg = _log_api_error(e)
        if len(note_list) > require_num:
            note_list = note_list[:require_num]
        return success, msg, note_list

    def get_user_info(self, user_id: str, cookies_str: str, proxies: dict = None):
        """
            获取用户的信息
            :param user_id: 你想要获取的用户的id
            :param cookies_str: 你的cookies
            返回用户的信息
        """
        res_json = None
        try:
            api = f"/api/sns/web/v1/user/otherinfo"
            params = {
                "target_user_id": user_id
            }
            splice_api = splice_str(api, params)
            headers, cookies, data = generate_request_params(cookies_str, splice_api, '', 'GET')
            response = requests.get(self.base_url + splice_api, headers=headers, cookies=cookies, proxies=proxies, timeout=REQUEST_TIMEOUT)
            res_json = response.json()
            success, msg = res_json["success"], res_json["msg"]
        except Exception as e:
            success = False
            msg = _log_api_error(e)
        return success, msg, res_json

    def get_user_self_info(self, cookies_str: str, proxies: dict = None):
        """委托 XhsCrawlerClient.get_user_self_info（统一请求层+异常分类，见 xhs_crawler_client.py）"""
        return self._crawler.get_user_self_info(cookies_str, proxies)
    def get_user_self_info2(self, cookies_str: str, proxies: dict = None):
        """委托 XhsCrawlerClient.get_user_self_info2（统一请求层+异常分类，见 xhs_crawler_client.py）"""
        return self._crawler.get_user_self_info2(cookies_str, proxies)
    def get_user_note_info(self, user_id: str, cursor: str, cookies_str: str, xsec_token='', xsec_source='', proxies: dict = None):
        """委托 XhsCrawlerClient.get_user_note_info（统一请求层+异常分类，见 xhs_crawler_client.py）"""
        return self._crawler.get_user_note_info(user_id, cursor, cookies_str, xsec_token, xsec_source, proxies)
    def get_user_all_notes(self, user_url: str, cookies_str: str, proxies: dict = None):
        """委托 XhsCrawlerClient.get_user_all_notes（统一请求层+异常分类，见 xhs_crawler_client.py）"""
        return self._crawler.get_user_all_notes(user_url, cookies_str, proxies)
    def get_user_like_note_info(self, user_id: str, cursor: str, cookies_str: str, xsec_token='', xsec_source='', proxies: dict = None):
        """
            获取用户指定位置喜欢的笔记
            :param user_id: 你想要获取的用户的id
            :param cursor: 你想要获取的笔记的cursor
            :param cookies_str: 你的cookies
            返回用户指定位置喜欢的笔记
        """
        res_json = None
        try:
            api = f"/api/sns/web/v1/note/like/page"
            params = {
                "num": "30",
                "cursor": cursor,
                "user_id": user_id,
                "image_formats": "jpg,webp,avif",
                "xsec_token": xsec_token,
                "xsec_source": xsec_source,
            }
            splice_api = splice_str(api, params)
            headers, cookies, data = generate_request_params(cookies_str, splice_api, '', 'GET')
            response = requests.get(self.base_url + splice_api, headers=headers, cookies=cookies, proxies=proxies, timeout=REQUEST_TIMEOUT)
            res_json = response.json()
            success, msg = res_json["success"], res_json["msg"]
        except Exception as e:
            success = False
            msg = _log_api_error(e)
        return success, msg, res_json

    def get_user_all_like_note_info(self, user_url: str, cookies_str: str, proxies: dict = None):
        """
            获取用户所有喜欢笔记
            :param user_id: 你想要获取的用户的id
            :param cookies_str: 你的cookies
            返回用户的所有喜欢笔记
        """
        cursor = ''
        note_list = []
        try:
            urlParse = urllib.parse.urlparse(user_url)
            user_id = urlParse.path.split("/")[-1]
            kvDist = _get_query_params(urlParse)
            xsec_token = kvDist['xsec_token'] if 'xsec_token' in kvDist else ""
            xsec_source = kvDist['xsec_source'] if 'xsec_source' in kvDist else "pc_user"
            while True:
                success, msg, res_json = self.get_user_like_note_info(user_id, cursor, cookies_str, xsec_token,
                                                                      xsec_source, proxies)
                if not success:
                    raise Exception(msg)
                notes = res_json["data"]["notes"]
                if 'cursor' in res_json["data"]:
                    cursor = str(res_json["data"]["cursor"])
                else:
                    break
                note_list.extend(notes)
                if len(notes) == 0 or not res_json["data"]["has_more"]:
                    break
        except Exception as e:
            success = False
            msg = _log_api_error(e)
        return success, msg, note_list

    def get_user_collect_note_info(self, user_id: str, cursor: str, cookies_str: str, xsec_token='', xsec_source='', proxies: dict = None):
        """
            获取用户指定位置收藏的笔记
            :param user_id: 你想要获取的用户的id
            :param cursor: 你想要获取的笔记的cursor
            :param cookies_str: 你的cookies
            返回用户指定位置收藏的笔记
        """
        res_json = None
        try:
            api = f"/api/sns/web/v2/note/collect/page"
            params = {
                "num": "30",
                "cursor": cursor,
                "user_id": user_id,
                "image_formats": "jpg,webp,avif",
                "xsec_token": xsec_token,
                "xsec_source": xsec_source,
            }
            splice_api = splice_str(api, params)
            headers, cookies, data = generate_request_params(cookies_str, splice_api, '', 'GET')
            response = requests.get(self.base_url + splice_api, headers=headers, cookies=cookies, proxies=proxies, timeout=REQUEST_TIMEOUT)
            res_json = response.json()
            success, msg = res_json["success"], res_json["msg"]
        except Exception as e:
            success = False
            msg = _log_api_error(e)
        return success, msg, res_json

    def get_user_all_collect_note_info(self, user_url: str, cookies_str: str, proxies: dict = None):
        """
            获取用户所有收藏笔记
            :param user_id: 你想要获取的用户的id
            :param cookies_str: 你的cookies
            返回用户的所有收藏笔记
        """
        cursor = ''
        note_list = []
        try:
            urlParse = urllib.parse.urlparse(user_url)
            user_id = urlParse.path.split("/")[-1]
            kvDist = _get_query_params(urlParse)
            xsec_token = kvDist['xsec_token'] if 'xsec_token' in kvDist else ""
            xsec_source = kvDist['xsec_source'] if 'xsec_source' in kvDist else "pc_search"
            while True:
                success, msg, res_json = self.get_user_collect_note_info(user_id, cursor, cookies_str, xsec_token,
                                                                         xsec_source, proxies)
                if not success:
                    raise Exception(msg)
                notes = res_json["data"]["notes"]
                if 'cursor' in res_json["data"]:
                    cursor = str(res_json["data"]["cursor"])
                else:
                    break
                note_list.extend(notes)
                if len(notes) == 0 or not res_json["data"]["has_more"]:
                    break
        except Exception as e:
            success = False
            msg = _log_api_error(e)
        return success, msg, note_list

    def get_note_info(self, url: str, cookies_str: str, proxies: dict = None):
        """委托 XhsCrawlerClient.get_note_info（统一请求层+异常分类，见 xhs_crawler_client.py）"""
        return self._crawler.get_note_info(url, cookies_str, proxies)
    def get_search_keyword(self, word: str, cookies_str: str, proxies: dict = None):
        """委托 XhsCrawlerClient.get_search_keyword（统一请求层+异常分类，见 xhs_crawler_client.py）"""
        return self._crawler.get_search_keyword(word, cookies_str, proxies)
    def search_note(self, query: str, cookies_str: str, page=1, sort_type_choice=0, note_type=0, note_time=0, note_range=0, pos_distance=0, geo="", search_id=None, proxies: dict = None):
        """委托 XhsCrawlerClient.search_note（统一请求层+异常分类，见 xhs_crawler_client.py）"""
        return self._crawler.search_note(query, cookies_str, page, sort_type_choice, note_type, note_time, note_range, pos_distance, geo, search_id, proxies)
    def search_some_note(self, query: str, require_num: int, cookies_str: str, sort_type_choice=0, note_type=0, note_time=0, note_range=0, pos_distance=0, geo="", proxies: dict = None):
        """委托 XhsCrawlerClient.search_some_note（统一请求层+异常分类，见 xhs_crawler_client.py）"""
        return self._crawler.search_some_note(query, require_num, cookies_str, sort_type_choice, note_type, note_time, note_range, pos_distance, geo, proxies)
    def search_user(self, query: str, cookies_str: str, page=1, proxies: dict = None):
        """
            获取搜索用户的结果
            :param query 搜索的关键词
            :param cookies_str 你的cookies
            :param page 搜索的页数
            返回搜索的结果
        """
        res_json = None
        try:
            api = "/api/sns/web/v1/search/usersearch"
            data = {
                "search_user_request": {
                    "keyword": query,
                    "search_id": generate_search_id(),
                    "page": page,
                    "page_size": 15,
                    "biz_type": "web_search_user",
                    "request_id": generate_search_request_id()
                }
            }
            headers, cookies, data = generate_request_params(cookies_str, api, data, 'POST')
            response = requests.post(self.base_url + api, headers=headers, data=data.encode('utf-8'), cookies=cookies, proxies=proxies, timeout=REQUEST_TIMEOUT)
            res_json = response.json()
            success, msg = res_json["success"], res_json["msg"]
        except Exception as e:
            success = False
            msg = _log_api_error(e)
        return success, msg, res_json

    def search_some_user(self, query: str, require_num: int, cookies_str: str, proxies: dict = None):
        """
            指定数量搜索用户
            :param query 搜索的关键词
            :param require_num 搜索的数量
            :param cookies_str 你的cookies
            返回搜索的结果
        """
        page = 1
        user_list = []
        try:
            while True:
                success, msg, res_json = self.search_user(query, cookies_str, page, proxies)
                if not success:
                    raise Exception(msg)
                if "users" not in res_json["data"]:
                    break
                users = res_json["data"]["users"]
                user_list.extend(users)
                page += 1
                if len(user_list) >= require_num or not res_json["data"]["has_more"]:
                    break
        except Exception as e:
            success = False
            msg = _log_api_error(e)
        if len(user_list) > require_num:
            user_list = user_list[:require_num]
        return success, msg, user_list

    def get_note_out_comment(self, note_id: str, cursor: str, xsec_token: str, cookies_str: str, proxies: dict = None):
        """委托 XhsCrawlerClient.get_note_out_comment（统一请求层+异常分类，见 xhs_crawler_client.py）"""
        return self._crawler.get_note_out_comment(note_id, cursor, xsec_token, cookies_str, proxies)
    def get_note_all_out_comment(self, note_id: str, xsec_token: str, cookies_str: str, proxies: dict = None, interval_seconds: float = None, max_comments: int = None):
        """委托 XhsCrawlerClient.get_note_all_out_comment（统一请求层+异常分类，见 xhs_crawler_client.py）"""
        return self._crawler.get_note_all_out_comment(note_id, xsec_token, cookies_str, proxies, interval_seconds, max_comments)
    def get_note_inner_comment(self, comment: dict, cursor: str, xsec_token: str, cookies_str: str, proxies: dict = None):
        """委托 XhsCrawlerClient.get_note_inner_comment（统一请求层+异常分类，见 xhs_crawler_client.py）"""
        return self._crawler.get_note_inner_comment(comment, cursor, xsec_token, cookies_str, proxies)
    def get_note_all_inner_comment(self, comment: dict, xsec_token: str, cookies_str: str, proxies: dict = None, interval_seconds: float = None):
        """委托 XhsCrawlerClient.get_note_all_inner_comment（统一请求层+异常分类，见 xhs_crawler_client.py）"""
        return self._crawler.get_note_all_inner_comment(comment, xsec_token, cookies_str, proxies, interval_seconds)
    def get_note_all_comment(self, url: str, cookies_str: str, proxies: dict = None, interval_seconds: float = None, max_comments: int = None):
        """委托 XhsCrawlerClient.get_note_all_comment（统一请求层+异常分类，见 xhs_crawler_client.py）"""
        return self._crawler.get_note_all_comment(url, cookies_str, proxies, interval_seconds, max_comments)
    def get_unread_message(self, cookies_str: str, proxies: dict = None):
        """
            获取未读消息
            :param cookies_str: 你的cookies
            返回未读消息
        """
        res_json = None
        try:
            api = "/api/sns/web/unread_count"
            headers, cookies, data = generate_request_params(cookies_str, api, '', 'GET')
            response = requests.get(self.base_url + api, headers=headers, cookies=cookies, proxies=proxies, timeout=REQUEST_TIMEOUT)
            res_json = response.json()
            success, msg = res_json["success"], res_json["msg"]
        except Exception as e:
            success = False
            msg = _log_api_error(e)
        return success, msg, res_json

    def get_metions(self, cursor: str, cookies_str: str, proxies: dict = None):
        """
            获取评论和@提醒
            :param cursor: 你想要获取的评论和@提醒的cursor
            :param cookies_str: 你的cookies
            返回评论和@提醒
        """
        res_json = None
        try:
            api = "/api/sns/web/v1/you/mentions"
            params = {
                "num": "20",
                "cursor": cursor
            }
            splice_api = splice_str(api, params)
            headers, cookies, data = generate_request_params(cookies_str, splice_api, '', 'GET')
            response = requests.get(self.base_url + splice_api, headers=headers, cookies=cookies, proxies=proxies, timeout=REQUEST_TIMEOUT)
            res_json = response.json()
            success, msg = res_json["success"], res_json["msg"]
        except Exception as e:
            success = False
            msg = _log_api_error(e)
        return success, msg, res_json

    def get_all_metions(self, cookies_str: str, proxies: dict = None):
        """
            获取全部的评论和@提醒
            :param cookies_str: 你的cookies
            返回全部的评论和@提醒
        """
        cursor = ''
        metions_list = []
        try:
            while True:
                success, msg, res_json = self.get_metions(cursor, cookies_str, proxies)
                if not success:
                    raise Exception(msg)
                metions = res_json["data"]["message_list"]
                if 'cursor' in res_json["data"]:
                    cursor = str(res_json["data"]["cursor"])
                else:
                    break
                metions_list.extend(metions)
                if not res_json["data"]["has_more"]:
                    break
        except Exception as e:
            success = False
            msg = _log_api_error(e)
        return success, msg, metions_list

    def get_likesAndcollects(self, cursor: str, cookies_str: str, proxies: dict = None):
        """
            获取赞和收藏
            :param cursor: 你想要获取的赞和收藏的cursor
            :param cookies_str: 你的cookies
            返回赞和收藏
        """
        res_json = None
        try:
            api = "/api/sns/web/v1/you/likes"
            params = {
                "num": "20",
                "cursor": cursor
            }
            splice_api = splice_str(api, params)
            headers, cookies, data = generate_request_params(cookies_str, splice_api, '', 'GET')
            response = requests.get(self.base_url + splice_api, headers=headers, cookies=cookies, proxies=proxies, timeout=REQUEST_TIMEOUT)
            res_json = response.json()
            success, msg = res_json["success"], res_json["msg"]
        except Exception as e:
            success = False
            msg = _log_api_error(e)
        return success, msg, res_json

    def get_all_likesAndcollects(self, cookies_str: str, proxies: dict = None):
        """
            获取全部的赞和收藏
            :param cookies_str: 你的cookies
            返回全部的赞和收藏
        """
        cursor = ''
        likesAndcollects_list = []
        try:
            while True:
                success, msg, res_json = self.get_likesAndcollects(cursor, cookies_str, proxies)
                if not success:
                    raise Exception(msg)
                likesAndcollects = res_json["data"]["message_list"]
                if 'cursor' in res_json["data"]:
                    cursor = str(res_json["data"]["cursor"])
                else:
                    break
                likesAndcollects_list.extend(likesAndcollects)
                if not res_json["data"]["has_more"]:
                    break
        except Exception as e:
            success = False
            msg = _log_api_error(e)
        return success, msg, likesAndcollects_list

    def get_new_connections(self, cursor: str, cookies_str: str, proxies: dict = None):
        """
            获取新增关注
            :param cursor: 你想要获取的新增关注的cursor
            :param cookies_str: 你的cookies
            返回新增关注
        """
        res_json = None
        try:
            api = "/api/sns/web/v1/you/connections"
            params = {
                "num": "20",
                "cursor": cursor
            }
            splice_api = splice_str(api, params)
            headers, cookies, data = generate_request_params(cookies_str, splice_api, '', 'GET')
            response = requests.get(self.base_url + splice_api, headers=headers, cookies=cookies, proxies=proxies, timeout=REQUEST_TIMEOUT)
            res_json = response.json()
            success, msg = res_json["success"], res_json["msg"]
        except Exception as e:
            success = False
            msg = _log_api_error(e)
        return success, msg, res_json

    def get_all_new_connections(self, cookies_str: str, proxies: dict = None):
        """
            获取全部的新增关注
            :param cookies_str: 你的cookies
            返回全部的新增关注
        """
        cursor = ''
        connections_list = []
        try:
            while True:
                success, msg, res_json = self.get_new_connections(cursor, cookies_str, proxies)
                if not success:
                    raise Exception(msg)
                connections = res_json["data"]["message_list"]
                if 'cursor' in res_json["data"]:
                    cursor = str(res_json["data"]["cursor"])
                else:
                    break
                connections_list.extend(connections)
                if not res_json["data"]["has_more"]:
                    break
        except Exception as e:
            success = False
            msg = _log_api_error(e)
        return success, msg, connections_list

    @staticmethod
    def get_note_no_water_video(note_id):
        """委托 XhsCrawlerClient.get_note_no_water_video（统一请求层+异常分类，见 xhs_crawler_client.py）"""
        from app.xhs.services.client.xhs_crawler_client import XhsCrawlerClient
        return XhsCrawlerClient.get_note_no_water_video(note_id)
    @staticmethod
    def get_note_no_water_img(img_url):
        """
            获取笔记无水印图片
            :param img_url: 你想要获取的图片的url
            返回笔记无水印图片
        """
        success = True
        msg = '成功'
        new_url = None
        try:
            # 新版图片资源优先保留 notes_pre_post token，使用 ci.xiaohongshu.com 输出 JPEG。
            # 例：
            # https://sns-webpic-qc.xhscdn.com/<time>/<hash>/notes_pre_post/<img_id>!nd_dft_wlteh_webp_3
            # -> https://ci.xiaohongshu.com/notes_pre_post/<img_id>?imageView2/format/jpeg
            if 'notes_pre_post/' in img_url:
                token = 'notes_pre_post/' + img_url.split('notes_pre_post/', 1)[1].split('!', 1)[0].split('?', 1)[0]
                new_url = f'https://ci.xiaohongshu.com/{token}?imageView2/format/jpeg'
            elif 'spectrum' in img_url:
                token = '/'.join(img_url.split('/')[-2:]).split('!', 1)[0].split('?', 1)[0]
                new_url = f'https://ci.xiaohongshu.com/{token}?imageView2/format/jpeg'
            elif '.jpg' in img_url:
                token = '/'.join([split for split in img_url.split('/')[-3:]]).split('!', 1)[0].split('?', 1)[0]
                new_url = f'https://ci.xiaohongshu.com/{token}?imageView2/format/jpeg'
            else:
                token = img_url.split('/')[-1].split('!', 1)[0].split('?', 1)[0]
                new_url = f'https://ci.xiaohongshu.com/{token}?imageView2/format/jpeg'
        except Exception as e:
            success = False
            msg = _log_api_error(e)
        return success, msg, new_url

if __name__ == '__main__':
    """
        此文件为小红书api的使用示例
        所有涉及数据爬取的api都在此文件中
        数据注入的api违规请勿尝试
    """
    xhs_apis = XHS_Apis()
    cookies_str = r''
    # 获取用户信息
    user_url = 'https://www.xiaohongshu.com/user/profile/67a332a2000000000d008358?xsec_token=ABTf9yz4cLHhTycIlksF0jOi1yIZgfcaQ6IXNNGdKJ8xg=&xsec_source=pc_feed'
    success, msg, user_info = xhs_apis.get_user_info('67a332a2000000000d008358', cookies_str)
    logger.info(f'获取用户信息结果 {json.dumps(user_info, ensure_ascii=False)}: {success}, msg: {msg}')
    success, msg, note_list = xhs_apis.get_user_all_notes(user_url, cookies_str)
    logger.info(f'获取用户所有笔记结果 {json.dumps(note_list, ensure_ascii=False)}: {success}, msg: {msg}')
    # 获取笔记信息
    note_url = r'https://www.xiaohongshu.com/explore/67d7c713000000000900e391?xsec_token=AB1ACxbo5cevHxV_bWibTmK8R1DDz0NnAW1PbFZLABXtE=&xsec_source=pc_user'
    success, msg, note_info = xhs_apis.get_note_info(note_url, cookies_str)
    logger.info(f'获取笔记信息结果 {json.dumps(note_info, ensure_ascii=False)}: {success}, msg: {msg}')
    # 获取搜索关键词
    query = "榴莲"
    success, msg, search_keyword = xhs_apis.get_search_keyword(query, cookies_str)
    logger.info(f'获取搜索关键词结果 {json.dumps(search_keyword, ensure_ascii=False)}: {success}, msg: {msg}')
    # 搜索笔记
    query = "榴莲"
    query_num = 10
    sort = "general"
    note_type = 0
    success, msg, notes = xhs_apis.search_some_note(query, query_num, cookies_str, sort, note_type)
    logger.info(f'搜索笔记结果 {json.dumps(notes, ensure_ascii=False)}: {success}, msg: {msg}')
    # 获取笔记评论
    note_url = r'https://www.xiaohongshu.com/explore/67d7c713000000000900e391?xsec_token=AB1ACxbo5cevHxV_bWibTmK8R1DDz0NnAW1PbFZLABXtE=&xsec_source=pc_user'
    success, msg, note_all_comment = xhs_apis.get_note_all_comment(note_url, cookies_str)
    logger.info(f'获取笔记评论结果 {json.dumps(note_all_comment, ensure_ascii=False)}: {success}, msg: {msg}')




