"""
xhs 统一请求层：签名 + cookie 注入 + 代理 + 分类重试。

替代原先分散在每个 API 方法里的 try/except + requests 直连模式，
把"重试策略"收敛到一处（参考 MediaCrawler 的 AbstractApiClient 设计）：

- 网络错误（连接失败/超时/响应非 JSON）→ 指数退避重试 NETWORK_RETRIES 次
- 风控/限流（code 300013 或 msg 含"频繁"）→ 指数退避重试 RATE_LIMIT_MAX_RETRIES 次
- 登录态失效 → 抛 XhsAuthError（不重试）
- 内容不存在 → 抛 XhsNotFoundError（不重试）
- 其他业务失败 → 原样返回 (success=False, msg, res_json)，由调用方自行处理

对外统一返回 (success, msg, res_json) 三元组，与旧 XHS_Apis 方法签名保持一致，
调用方无需改动。
"""

from __future__ import annotations

import random
import time
from typing import Any, Optional

import requests
from loguru import logger

from app.xhs.services.utils.http_util import REQUEST_TIMEOUT
from app.xhs.services.utils.xhs_util import generate_request_params, splice_str

from ..xhs_errors import XhsAuthError, XhsNetworkError, XhsNotFoundError, XhsRateLimitError

# ---------------------------------------------------------------- 判定常量 ----

# 小红书风控/限流响应码：接口层 success 仍为 true，但 data 为空，需当作失败处理并退避重试
RATE_LIMIT_CODES = {300013}
RATE_LIMIT_MAX_RETRIES = 3
RATE_LIMIT_BACKOFF_SECONDS = 3.0

NETWORK_RETRIES = 3
NETWORK_BACKOFF_SECONDS = 2.0

# msg 文本关键词 → 异常分类
_AUTH_KEYWORDS = ("登录", "未登录", "登录状态", "登录已过期", "auth")
_NOT_FOUND_KEYWORDS = ("不存在", "已删除", "找不到", "失效的")
_RATE_LIMIT_KEYWORDS = ("频繁",)


def _is_rate_limited(msg: str) -> bool:
    return bool(msg) and any(k in msg for k in _RATE_LIMIT_KEYWORDS)


def paced_sleep(interval: float) -> None:
    """固定间隔的请求节奏本身就是风控识别爬虫的特征之一，加随机抖动让节奏更像真人操作"""
    if interval > 0:
        time.sleep(interval + random.uniform(0, interval * 0.5))


def _log_api_error(error: Exception) -> str:
    logger.exception(f"XHS PC API request failed: {error}")
    return str(error)


class XhsRequestClient:
    """统一请求客户端：签名 + 发送 + 分类重试 + 三元组返回"""

    def __init__(self, base_url: str = "https://edith.xiaohongshu.com"):
        self.base_url = base_url

    # ------------------------------------------------------------ 业务分类 ----

    @staticmethod
    def classify_business_error(msg: str, code: Any, res_json: Optional[dict]) -> Optional[Exception]:
        """把业务层失败翻译成分类异常；无法归类则返回 None（调用方按普通失败处理）"""
        text = msg or ""
        if code in RATE_LIMIT_CODES or _is_rate_limited(text):
            return XhsRateLimitError(msg or f"触发风控/限流, code={code}")
        if any(k in text for k in _AUTH_KEYWORDS):
            return XhsAuthError(msg or "登录态失效，请重新登录")
        if any(k in text for k in _NOT_FOUND_KEYWORDS):
            return XhsNotFoundError(msg or "内容不存在或已删除")
        return None

    # ------------------------------------------------------------ 发送 ----

    def _do_request(
        self,
        method: str,
        api: str,
        cookies_str: str,
        *,
        params: Optional[dict] = None,
        data: Any = None,
        proxies: Optional[dict] = None,
        extra_headers: Optional[dict] = None,
    ) -> tuple[bool, str, Optional[dict], Any]:
        """发一次请求，返回 (success, msg, res_json, code)。网络层异常直接抛出。"""
        if method == "POST":
            headers, cookies, body = generate_request_params(cookies_str, api, data, "POST")
            if isinstance(body, str):
                body = body.encode("utf-8")
            if extra_headers:
                headers.update(extra_headers)
            response = requests.post(
                self.base_url + api, headers=headers, data=body, cookies=cookies,
                proxies=proxies, timeout=REQUEST_TIMEOUT,
            )
        else:
            splice_api = api if params is None else splice_str(api, params)
            headers, cookies, _ = generate_request_params(cookies_str, splice_api, "", "GET")
            if extra_headers:
                headers.update(extra_headers)
            response = requests.get(
                self.base_url + splice_api, headers=headers, cookies=cookies,
                proxies=proxies, timeout=REQUEST_TIMEOUT,
            )

        try:
            res_json = response.json()
        except (ValueError, TypeError):
            # 非 JSON 响应：403/471 时很可能是滑块验证页/风控页，必须把响应头里的
            # 验证信息（Verifytype/Verifyuuid）和 body 片段记下来，否则无法定位风控
            if response.status_code in (401, 403, 471, 461):
                verify = (
                    f", Verifytype={response.headers.get('Verifytype')}, "
                    f"Verifyuuid={response.headers.get('Verifyuuid')}"
                    if response.headers.get("Verifytype")
                    else ""
                )
                logger.warning(
                    f"XHS 风控类响应（HTTP {response.status_code}{verify}），"
                    f"body 片段: {response.text[:300]}"
                )
            raise XhsNetworkError(
                f"响应非 JSON: status={response.status_code}, body={response.text[:200]}"
            ) from None

        if not isinstance(res_json, dict):
            raise XhsNetworkError(f"响应结构异常: {str(res_json)[:200]}")

        code = res_json.get("code")
        if response.status_code in (401, 403, 471, 461):
            # 风控/滑块/登录失效类响应：记录响应头验证信息与 body 片段，方便确认是否风控
            verify = (
                f", Verifytype={response.headers.get('Verifytype')}, "
                f"Verifyuuid={response.headers.get('Verifyuuid')}"
                if response.headers.get("Verifytype")
                else ""
            )
            logger.warning(
                f"XHS 风控类响应（HTTP {response.status_code}{verify}），"
                f"code={res_json.get('code')}, msg={res_json.get('msg')}, "
                f"data={str(res_json.get('data'))[:200]}"
            )
            return False, f"HTTP {response.status_code}", res_json, code
        success = bool(res_json.get("success", False))
        msg = res_json.get("msg", "")
        # 有些失败响应（滑块验证/风控校验）不带 msg 字段，只有 code——退回诊断信息，
        # 让调用方至少能看出是不是触发了风控校验
        if not success and not msg:
            msg = f"响应异常（可能触发小红书风控校验），code={res_json.get('code')}, data={res_json.get('data')}"
        return success, msg, res_json, code

    # ------------------------------------------------------------ 入口 ----

    def request(
        self,
        method: str,
        api: str,
        cookies_str: str,
        *,
        params: Optional[dict] = None,
        data: Any = None,
        proxies: Optional[dict] = None,
        extra_headers: Optional[dict] = None,
        network_retries: int = NETWORK_RETRIES,
    ) -> tuple[bool, str, Optional[dict]]:
        """
        统一请求入口：签名 → 分类重试 → (success, msg, res_json)。

        异常约定：
        - 网络重试耗尽 → 抛 XhsNetworkError
        - 风控重试耗尽 → 抛 XhsRateLimitError
        - 登录失效 / 内容不存在 → 直接抛 XhsAuthError / XhsNotFoundError
        - 其他业务失败 → 返回 (False, msg, res_json)，不抛
        """
        network_attempt = 0
        rate_attempt = 0
        while True:
            try:
                success, msg, res_json, code = self._do_request(
                    method, api, cookies_str,
                    params=params, data=data, proxies=proxies, extra_headers=extra_headers,
                )
            except requests.RequestException as e:
                cause_str = str(e.__cause__ or e)
                # DNS 解析失败/网络不可达是本机网络问题（日志里常见 "Failed to resolve"
                # / "nodename nor servname provided" / "Network is unreachable"），
                # 重试多少次都不会好，直接抛错省掉 3 次无意义的退避等待
                if any(k in cause_str for k in ("Failed to resolve", "nodename nor servname", "NameResolution", "Network is unreachable")):
                    raise XhsNetworkError(f"域名解析/网络不可达（本机网络问题，重试无意义）: {e}") from e
                if network_attempt >= network_retries:
                    raise XhsNetworkError(
                        f"网络请求失败（已重试 {network_attempt} 次）: {e}"
                    ) from e
                network_attempt += 1
                backoff = NETWORK_BACKOFF_SECONDS * (2 ** (network_attempt - 1)) + random.uniform(0, 0.5)
                logger.warning(
                    f"XHS 网络请求异常（{e}），{backoff:.1f}s 后重试（{network_attempt}/{network_retries}）"
                )
                time.sleep(backoff)
                continue

            if success:
                return True, msg, res_json

            err = self.classify_business_error(msg, code, res_json)
            if isinstance(err, XhsRateLimitError):
                if rate_attempt >= RATE_LIMIT_MAX_RETRIES:
                    raise err
                rate_attempt += 1
                backoff = RATE_LIMIT_BACKOFF_SECONDS * (2 ** (rate_attempt - 1)) + random.uniform(0, 1)
                logger.warning(
                    f"XHS API 触发限流（{msg}），{backoff:.1f}s 后重试（{rate_attempt}/{RATE_LIMIT_MAX_RETRIES}）"
                )
                time.sleep(backoff)
                continue
            if err is not None:
                raise err
            return False, msg, res_json
