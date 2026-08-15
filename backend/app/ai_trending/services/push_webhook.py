"""企业微信机器人 webhook 推送客户端（本次为可插拔 Sender 协议 + Mock 实现）。

设计文档中的 PushWebhookClient 描述的是真实企微客户端；企微机器人模块当前由
其他团队并行开发，本次推送通道统一走 Sender 协议 + MockWebhookSender（不发真实
网络请求，便于联调与失败分支测试）。对接真实企微时实现 FutureWecomSender.send()
调 qyapi.weixin.qq.com webhook（加签公式见 build_sign 注释），其余设计不变。

企微协议要点：
- POST {webhook_url}，JSON body {"msgtype":"markdown","markdown":{"content": content}}，timeout=10；
- 响应 JSON {"errcode": 0, "errmsg": "ok"}；errcode==0 视为成功；
- 常见错误码：93000 无效 webhook 或关键词不匹配；93004 频繁发送；
- 可选加签：url += &timestamp={ts}&sign={sign}，sign = base64(hmac_sha256(secret, f"{timestamp}\\n{secret}"))。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import random
import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from loguru import logger

# 企微 markdown content 上限（字节）
MAX_CONTENT_BYTES = 4096

# webhook URL 校验正则（mock 阶段同样校验格式）
_WEBHOOK_URL_RE = re.compile(
    r"^https://qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key=[A-Za-z0-9_-]+$"
)


@dataclass
class SendResult:
    """发送结果：status 是否成功；errcode/errmsg 供记录与前端展示。"""

    status: bool
    errcode: int
    errmsg: str


@runtime_checkable
class WebhookSender(Protocol):
    """可插拔发送器协议：所有实现（Mock / 未来企微）必须提供 send(content)。"""

    def send(self, content: str) -> SendResult:
        """发送 markdown 内容，返回 SendResult；网络/协议异常由实现内部收敛。"""
        ...


class MockWebhookSender:
    """模拟发送器：不发真实网络请求，默认模拟成功（errcode=0）。

    - mock_fail=True：强制失败（测试失败分支）；
    - mock_fail_rate>0：按概率随机失败（如 0.3 = 30% 概率失败）；
    - 模拟发送时把 content 前 200 字打到 logger.info 留痕（绝不落 webhook_url/secret 到日志）。
    """

    def __init__(self, mock_fail: bool = False, mock_fail_rate: float = 0.0) -> None:
        self.mock_fail = mock_fail
        self.mock_fail_rate = max(0.0, min(1.0, float(mock_fail_rate)))

    def send(self, content: str) -> SendResult:
        preview = (content or "")[:200].replace("\n", " ")
        if self.mock_fail or (
            self.mock_fail_rate > 0 and random.random() < self.mock_fail_rate
        ):
            logger.info(f"[mock 推送] 模拟失败（未发网络请求）：{preview}")
            return SendResult(
                status=False,
                errcode=93000,
                errmsg="模拟失败：mock_fail / mock_fail_rate 触发（未接入真实企微）",
            )
        logger.info(f"[mock 推送] 模拟发送成功（未发网络请求）：{preview}")
        return SendResult(status=True, errcode=0, errmsg="ok")


class FutureWecomSender:
    """占位类：对接真实企微机器人模块时实现。

    真实实现要点（届时替换 MockWebhookSender，push_service 无需改动）：
      1. 若配置了 webhook_secret：url = webhook_url + f"&timestamp={ts}&sign={build_sign(secret, ts)}"
      2. requests.post(url, json={"msgtype": "markdown", "markdown": {"content": content}}, timeout=10)
      3. 响应 JSON errcode==0 → SendResult(True, 0, "ok")；
         否则 → SendResult(False, errcode, errmsg)（93000 关键词不匹配等）；
         网络/HTTP/超时异常 → SendResult(False, 0, str(exc))
      4. webhook_url / webhook_secret 绝不写入日志。
    """

    def __init__(self, webhook_url: str, secret: str | None = None) -> None:
        self.webhook_url = webhook_url
        self.secret = secret

    def send(self, content: str) -> SendResult:  # pragma: no cover - 占位，不实现网络逻辑
        raise NotImplementedError(
            "真实企微发送尚未实现：企微机器人模块并行开发中，请使用 MockWebhookSender"
        )


class PushWebhookError(Exception):
    """企微返回 errcode!=0 或网络/HTTP 异常时抛出。携带 errcode/errmsg。

    当前 mock 阶段不抛（MockWebhookSender 返回 SendResult）；FutureWecomSender
    对接真实企微时按此约定抛错，push_service._send_with_retry 已兼容捕获。
    """

    def __init__(self, errcode: int, errmsg: str) -> None:
        super().__init__(f"errcode={errcode} errmsg={errmsg}")
        self.errcode = errcode
        self.errmsg = errmsg


def build_sender(config) -> WebhookSender:
    """发送器工厂：默认返回 MockWebhookSender（不发真实网络请求）。

    mock_fail_rate 从环境变量 AI_TRENDING_MOCK_FAIL_RATE 读取（默认 0）；
    config 参数预留（webhook_url / webhook_secret），FutureWecomSender 对接时使用。
    """
    raw = os.environ.get("AI_TRENDING_MOCK_FAIL_RATE", "0") or "0"
    try:
        rate = float(raw)
    except ValueError:
        rate = 0.0
    return MockWebhookSender(mock_fail_rate=rate)


# ------------------------------------------------------------- 纯函数 ----
def validate_webhook_url(url: str) -> bool:
    r"""校验企微 webhook URL 格式：
    ^https://qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key=[A-Za-z0-9_-]+$
    """
    return bool(url and _WEBHOOK_URL_RE.match(url.strip()))


def mask_webhook_url(url: str) -> str:
    """把 key 参数替换为 ****{key 后 4 位}，如 ...webhook/send?key=****abcd。"""
    if not url:
        return ""

    def _mask(match: re.Match) -> str:
        key = match.group(2)
        tail = key[-4:] if len(key) >= 4 else key
        return f"{match.group(1)}****{tail}"

    return re.sub(r"([?&]key=)([^&]+)", _mask, url)


def build_sign(secret: str, timestamp: int) -> str:
    """企微加签：sign = base64(hmac_sha256(secret, f"{timestamp}\\n{secret}"))。

    供 FutureWecomSender 对接真实企微时使用：
      url = f"{webhook_url}&timestamp={ts}&sign={build_sign(secret, ts)}"
    """
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


# ------------------------------------------------------------- 截断管线 ----
_ITEM_HEAD_RE = re.compile(r"^\d+\. \*\*")
_TOP_SECTION_RE = re.compile(r"(?m)^## 🔥 Top .+ 热点\s*$")
_OVERVIEW_SECTION_RE = re.compile(r"(?m)^## 📊 今日趋势综述\s*$")


def _bytes_len(text: str) -> int:
    return len((text or "").encode("utf-8"))


def _truncate_summary_lines(content: str, limit: int = 60) -> str:
    """把所有 '   > {摘要}' 行截断到 limit 字符（中文按字符计）。"""

    def _replace(match: re.Match) -> str:
        prefix, text = match.group(1), match.group(2)
        if len(text) <= limit:
            return match.group(0)
        return f"{prefix}{text[:limit]}…"

    return re.sub(r"(?m)^(   > )(.*)$", _replace, content)


def _split_item_blocks(content: str) -> tuple[str, list[str]]:
    """把 markdown 拆成 (头部, 条目块列表)。条目块 = 标题行 + 摘要引用行 + 链接行。"""
    marker = _TOP_SECTION_RE.search(content)
    if not marker:
        return content, []
    header = content[: marker.end()]
    lines = content[marker.end() :].split("\n")
    blocks: list[str] = []
    current: list[str] = []
    for line in lines:
        if _ITEM_HEAD_RE.match(line):
            if current:
                blocks.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return header, blocks


def _renumber_blocks(blocks: list[str]) -> list[str]:
    """删除条目后重新编号（1..N）。"""
    out: list[str] = []
    for idx, block in enumerate(blocks, start=1):
        out.append(re.sub(r"^\d+\. ", f"{idx}. ", block, count=1))
    return out


def _drop_item_blocks(content: str, max_bytes: int) -> str:
    """从列表末尾逐条删除条目块，直到 ≤ max_bytes 或条数 == max(1, 初始条数//2)。"""
    header, blocks = _split_item_blocks(content)
    if not blocks:
        return content
    min_blocks = max(1, len(blocks) // 2)
    while len(blocks) > min_blocks and _bytes_len(header + "\n" + "\n".join(blocks)) > max_bytes:
        blocks = blocks[:-1]
    blocks = _renumber_blocks(blocks)
    header = re.sub(r"## 🔥 Top \d+ 热点", f"## 🔥 Top {len(blocks)} 热点", header)
    return header + "\n" + "\n".join(blocks)


def _truncate_overview_to_sentence(content: str) -> str:
    """把『今日趋势综述』段落截为第一句（按中文句号/感叹号/问号/换行切分）。"""
    marker = _OVERVIEW_SECTION_RE.search(content)
    if not marker:
        return content
    section_start = marker.end()
    next_marker = _TOP_SECTION_RE.search(content, section_start)
    section_end = next_marker.start() if next_marker else len(content)
    body = content[section_start:section_end].strip()
    for sep in ("。", "！", "？", "!", "?", "\n"):
        idx = body.find(sep)
        if idx != -1:
            body = body[: idx + 1]
            break
    if not body:
        return content
    return content[:section_start] + "\n" + body + "\n" + content[section_end:]


def _hard_cut_bytes(content: str, max_bytes: int) -> str:
    """按字节硬切到 max_bytes，并在最近换行符处收尾。"""
    data = content.encode("utf-8")
    if len(data) <= max_bytes:
        return content
    cut = data[:max_bytes].decode("utf-8", errors="ignore")
    newline = cut.rfind("\n")
    if newline > 0:
        cut = cut[:newline]
    return cut


def truncate_to_bytes(content: str, max_bytes: int = MAX_CONTENT_BYTES) -> str:
    """企微 markdown 4096 字节上限的逐级降级截断：

    1. 原样（≤ max_bytes 直接返回）；
    2. 超限 → 每条摘要截断到 60 字符重建；
    3. 仍超限 → 从列表末尾逐条删除条目（items_count 相应减少，不低于初始条数 50%）；
    4. 仍超限 → 综述段落截为一句；
    5. 仍超限 → 按字节硬切并在最近换行处收尾。
    """
    if _bytes_len(content) <= max_bytes:
        return content

    rebuilt = _truncate_summary_lines(content, 60)
    if _bytes_len(rebuilt) <= max_bytes:
        return rebuilt

    rebuilt = _drop_item_blocks(rebuilt, max_bytes)
    if _bytes_len(rebuilt) <= max_bytes:
        return rebuilt

    rebuilt = _truncate_overview_to_sentence(rebuilt)
    if _bytes_len(rebuilt) <= max_bytes:
        return rebuilt

    return _hard_cut_bytes(rebuilt, max_bytes)
