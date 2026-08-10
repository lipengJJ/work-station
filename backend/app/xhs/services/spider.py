import json
import os
import time
from loguru import logger
from app.xhs.services.client.pc_apis import XHS_Apis
from app.xhs.services.utils.common_util import init
from app.xhs.services.utils.data_util import handle_note_info, handle_comment_info, download_note, save_to_xlsx


class Data_Spider():
    def __init__(self):
        self.xhs_apis = XHS_Apis()

    def spider_note(self, note_url: str, cookies_str: str, proxies=None):
        """
        爬取一个笔记的信息
        :param note_url:
        :param cookies_str:
        :return:
        """
        note_info = None
        try:
            success, msg, note_info = self.xhs_apis.get_note_info(note_url, cookies_str, proxies)
            if success:
                note_info = note_info['data']['items'][0]
                note_info['url'] = note_url
                note_info = handle_note_info(note_info)
        except Exception as e:
            success = False
            msg = e
        logger.info(f'爬取笔记信息 {note_url}: {success}, msg: {msg}')
        return success, msg, note_info

    def _flatten_comments(self, comments: list, note_id: str, note_url: str) -> list:
        flattened = []
        for comment in comments:
            tagged = dict(comment)
            tagged['note_id'] = note_id
            tagged['note_url'] = note_url
            try:
                flattened.append(handle_comment_info(tagged))
            except (KeyError, TypeError) as e:
                logger.warning(f'评论格式化失败，跳过: {e}')
                continue
            sub_comments = comment.get('sub_comments') or []
            if sub_comments:
                flattened.extend(self._flatten_comments(sub_comments, note_id, note_url))
        return flattened

    def spider_note_comments(self, note_info: dict, cookies_str: str, proxies=None, interval_seconds=None, max_comments=None):
        """
        爬取一篇笔记的评论（一级 + 二级），已按无二级互动的短评论过滤规则清洗
        :param note_info: 经 handle_note_info 处理过的笔记信息，需要 note_id / note_url
        :param interval_seconds: 评论翻页/展开请求的间隔（秒），用于限速
        :param max_comments: 最多保留的一级评论数量，None 表示不限制（抓取全部，请求量会明显更大更容易被限流）
        :return: success, msg, comment_list（已格式化，可直接用于 save_to_xlsx(type='comment')）
        """
        note_id = note_info['note_id']
        note_url = note_info['note_url']
        comment_list = []
        try:
            success, msg, comments = self.xhs_apis.get_note_all_comment(note_url, cookies_str, proxies, interval_seconds=interval_seconds, max_comments=max_comments)
            if success:
                comment_list = self._flatten_comments(comments, note_id, note_url)
        except Exception as e:
            success = False
            msg = e
        logger.info(f'爬取笔记评论 {note_url}: {success}, msg: {msg}, 评论数: {len(comment_list)}')
        return success, msg, comment_list

    def spider_some_note(self, notes: list, cookies_str: str, base_path: dict, save_choice: str, excel_name: str = '', proxies=None, fetch_comments: bool = False, comment_interval_seconds: float = None, max_comments_per_note: int = None):
        """
        爬取一些笔记的信息
        :param notes:
        :param cookies_str:
        :param base_path:
        :param fetch_comments: 是否同时抓取每篇笔记的评论
        :param comment_interval_seconds: 抓评论时的请求间隔（秒），用于限速
        :param max_comments_per_note: 每篇笔记最多保留的一级评论数量，None 表示不限制
        :return:
        """
        if (save_choice == 'all' or save_choice == 'excel') and excel_name == '':
            raise ValueError('excel_name 不能为空')
        note_list = []
        for note_url in notes:
            success, msg, note_info = self.spider_note(note_url, cookies_str, proxies)
            if note_info is not None and success:
                note_list.append(note_info)
        for note_info in note_list:
            if save_choice == 'all' or 'media' in save_choice:
                try:
                    download_note(note_info, base_path['media'], save_choice)
                except Exception as e:
                    logger.error(f"笔记 {note_info.get('note_id')} 素材下载失败，跳过: {e}")
        all_comments = []
        if fetch_comments:
            for note_info in note_list:
                try:
                    _, _, comment_list = self.spider_note_comments(note_info, cookies_str, proxies, interval_seconds=comment_interval_seconds, max_comments=max_comments_per_note)
                    all_comments.extend(comment_list)
                except Exception as e:
                    logger.error(f"笔记 {note_info.get('note_id')} 评论抓取失败，跳过: {e}")
                time.sleep(comment_interval_seconds if comment_interval_seconds is not None else 1.0)
        if save_choice == 'all' or save_choice == 'excel':
            file_path = os.path.abspath(os.path.join(base_path['excel'], f'{excel_name}.xlsx'))
            save_to_xlsx(note_list, file_path)
            if fetch_comments:
                comments_file_path = os.path.abspath(os.path.join(base_path['excel'], f'{excel_name}_comments.xlsx'))
                save_to_xlsx(all_comments, comments_file_path, 'comment')


    def spider_user_all_note(self, user_url: str, cookies_str: str, base_path: dict, save_choice: str, excel_name: str = '', proxies=None):
        """
        爬取一个用户的所有笔记
        :param user_url:
        :param cookies_str:
        :param base_path:
        :return:
        """
        note_list = []
        try:
            success, msg, all_note_info = self.xhs_apis.get_user_all_notes(user_url, cookies_str, proxies)
            if success:
                logger.info(f'用户 {user_url} 作品数量: {len(all_note_info)}')
                for simple_note_info in all_note_info:
                    note_url = f"https://www.xiaohongshu.com/explore/{simple_note_info['note_id']}?xsec_token={simple_note_info['xsec_token']}"
                    note_list.append(note_url)
            if save_choice == 'all' or save_choice == 'excel':
                excel_name = user_url.split('/')[-1].split('?')[0]
            self.spider_some_note(note_list, cookies_str, base_path, save_choice, excel_name, proxies)
        except Exception as e:
            success = False
            msg = e
        logger.info(f'爬取用户所有视频 {user_url}: {success}, msg: {msg}')
        return note_list, success, msg

    def spider_some_search_note(self, query: str, require_num: int, cookies_str: str, base_path: dict, save_choice: str, sort_type_choice=0, note_type=0, note_time=0, note_range=0, pos_distance=0, geo: dict = None,  excel_name: str = '', proxies=None, fetch_comments: bool = False, comment_interval_seconds: float = None, max_comments_per_note: int = None):
        """
            指定数量搜索笔记，设置排序方式和笔记类型和笔记数量
            :param query 搜索的关键词
            :param require_num 搜索的数量
            :param cookies_str 你的cookies
            :param base_path 保存路径
            :param sort_type_choice 排序方式 0 综合排序, 1 最新, 2 最多点赞, 3 最多评论, 4 最多收藏
            :param note_type 笔记类型 0 不限, 1 视频笔记, 2 普通笔记
            :param note_time 笔记时间 0 不限, 1 一天内, 2 一周内天, 3 半年内
            :param note_range 笔记范围 0 不限, 1 已看过, 2 未看过, 3 已关注
            :param pos_distance 位置距离 0 不限, 1 同城, 2 附近 指定这个必须要指定 geo
            :param fetch_comments 是否同时抓取每篇笔记的评论
            :param comment_interval_seconds 抓评论时的请求间隔（秒），用于限速
            :param max_comments_per_note 每篇笔记最多保留的一级评论数量，None 表示不限制
            返回搜索的结果
        """
        note_list = []
        try:
            success, msg, notes = self.xhs_apis.search_some_note(query, require_num, cookies_str, sort_type_choice, note_type, note_time, note_range, pos_distance, geo, proxies)
            if success:
                notes = list(filter(lambda x: x['model_type'] == "note", notes))
                logger.info(f'搜索关键词 {query} 笔记数量: {len(notes)}')
                for note in notes:
                    note_url = f"https://www.xiaohongshu.com/explore/{note['id']}?xsec_token={note['xsec_token']}"
                    note_list.append(note_url)
            if save_choice == 'all' or save_choice == 'excel':
                excel_name = query
            self.spider_some_note(note_list, cookies_str, base_path, save_choice, excel_name, proxies, fetch_comments=fetch_comments, comment_interval_seconds=comment_interval_seconds, max_comments_per_note=max_comments_per_note)
        except Exception as e:
            success = False
            msg = e
        logger.info(f'搜索关键词 {query} 笔记: {success}, msg: {msg}')
        return note_list, success, msg

if __name__ == '__main__':
    """
        此文件为爬虫的入口文件，可以直接运行
        client/pc_apis.py 为爬虫的api文件，包含小红书的全部数据接口，可以继续封装
        client/creator_apis.py 为小红书创作者中心的api文件
        感谢star和follow
    """

    cookies_str, base_path = init()
    data_spider = Data_Spider()
    """
        save_choice: all: 保存所有的信息, media: 保存视频和图片（media-video只下载视频, media-image只下载图片，media都下载）, excel: 保存到excel
        save_choice 为 excel 或者 all 时，excel_name 不能为空
    """


    # 1 爬取列表的所有笔记信息 笔记链接 如下所示 注意此url会过期！
    # notes = [
    #     r'https://www.xiaohongshu.com/explore/683fe17f0000000023017c6a?xsec_token=ABBr_cMzallQeLyKSRdPk9fwzA0torkbT_ubuQP1ayvKA=&xsec_source=pc_user',
    # ]
    # data_spider.spider_some_note(notes, cookies_str, base_path, 'all', 'test')

    # 2 爬取用户的所有笔记信息 用户链接 如下所示 注意此url会过期！
    # user_url = 'https://www.xiaohongshu.com/user/profile/64c3f392000000002b009e45?xsec_token=AB-GhAToFu07JwNk_AMICHnp7bSTjVz2beVIDBwSyPwvM=&xsec_source=pc_feed'
    # data_spider.spider_user_all_note(user_url, cookies_str, base_path, 'all')

    # 3 搜索指定关键词的笔记：普吉岛酒店推荐，近半年，按时间排序，不抓评论
    query = "普吉岛酒店推荐"
    query_num = 200
    sort_type_choice = 1  # 0 综合排序, 1 最新, 2 最多点赞, 3 最多评论, 4 最多收藏
    note_type = 0 # 0 不限, 1 视频笔记, 2 普通笔记
    note_time = 3  # 0 不限, 1 一天内, 2 一周内天, 3 半年内
    note_range = 0  # 0 不限, 1 已看过, 2 未看过, 3 已关注
    pos_distance = 0  # 0 不限, 1 同城, 2 附近 指定这个1或2必须要指定 geo
    # geo = {
    #     # 经纬度
    #     "latitude": 39.9725,
    #     "longitude": 116.4207
    # }
    data_spider.spider_some_search_note(query, query_num, cookies_str, base_path, 'all', sort_type_choice, note_type, note_time, note_range, pos_distance, geo=None, fetch_comments=False)
