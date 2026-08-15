"""
消息通知服务（企业微信机器人 / Server酱 双通道）。

- NotificationConfig 存通道配置/开关（单例配置，最多一行）；channel 决定走哪个通道：
  wecom_webhook（默认，企业微信机器人）或 serverchan（Server酱）；
- NotificationLog 记录每次发送结果，失败也记（status='failed' + error_msg）；
- notify_task_result() 是任务中心钩子入口：独立线程发送，发送失败只写日志，
  绝不影响任务本身的主流程（任务完成/失败的通知不能反过来让任务报错）。
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

import requests
from loguru import logger
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.common.models import NotificationConfig, NotificationLog, Task

# 企业微信机器人 webhook 发送地址：把配置里存的完整 webhook_url（含 key 参数）直接
# POST 到这个地址即可，不需要自己拼 key。
WECOM_WEBHOOK_BASE = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
# Server酱 发送地址前缀：实际请求 https://sctapi.ftqq.com/{sendkey}.send（form: title + desp）
SERVERCHAN_BASE = "https://sctapi.ftqq.com"
REQUEST_TIMEOUT = 8  # 秒：5-10s 区间内，既不让任务线程等太久，也给弱网留余量

# 模块 / 任务类型的中文展示名（通知正文可读性；没有注册的 fallback 用原始值）
_MODULE_LABELS = {
    "xhs": "小红书",
    "stock": "股票分析",
    "analysis": "分析任务",
    "resource": "资源中心",
    "skills": "技能中心",
}

_TASK_TYPE_LABELS = {
    "xhs_search": "笔记采集",
    "xhs_tracking": "追踪扫描",
    "analyze": "分析任务",
}


def _log_notification(
    db: Session,
    channel: str,
    title: str,
    content: Optional[str],
    status: str,
    error_msg: Optional[str],
) -> None:
    """写一条发送记录到 notification_log；落库失败只打日志，不影响主流程。"""
    try:
        db.add(
            NotificationLog(
                channel=channel or "wecom_webhook",
                title=title or "",
                content=content,
                status=status,
                error_msg=error_msg,
            )
        )
        db.commit()
    except Exception:
        logger.exception("通知发送记录落库失败")
        db.rollback()


def log_notification(
    db: Session,
    channel: str,
    title: str,
    content: Optional[str],
    status: str,
    error_msg: Optional[str],
) -> None:
    """供 controller（测试发送/手动发送）复用：写一条发送记录。"""
    _log_notification(db, channel, title, content, status, error_msg)


def send_wecom_message(
    webhook_url: str,
    content: str,
    msgtype: str = "text",
    mentioned_list: Optional[list[str]] = None,
) -> tuple[bool, str]:
    """
    向企业微信机器人 webhook 发送一条消息。

    支持 text / markdown 两种 msgtype；text 可带 mentioned_list（["@all"] 即 @所有人）。
    返回 (是否成功, 错误信息/成功提示)。任何异常都不向上抛——任务钩子不希望通知失败
    影响主流程。
    """
    webhook_url = (webhook_url or "").strip()
    if not webhook_url:
        return False, "未配置 webhook 地址"
    if msgtype not in ("text", "markdown"):
        return False, f"不支持的 msgtype: {msgtype}"

    payload: dict = {"msgtype": msgtype}
    if msgtype == "markdown":
        payload["markdown"] = {"content": content}
    else:
        text_body: dict = {"content": content}
        if mentioned_list:
            text_body["mentioned_list"] = mentioned_list
        payload["text"] = text_body

    try:
        resp = requests.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        return False, f"请求企业微信接口失败：{e}"

    try:
        data = resp.json()
    except Exception:
        return False, f"响应解析失败（HTTP {resp.status_code}）：{resp.text[:200]}"

    if data.get("errcode") == 0:
        return True, data.get("errmsg") or "发送成功"
    return False, f"企业微信返回错误：errcode={data.get('errcode')}, errmsg={data.get('errmsg')}"


def send_serverchan(sendkey: str, title: str, desp: str = "") -> tuple[bool, str]:
    """
    通过 Server酱（ServerChan）推送一条消息。

    POST https://sctapi.ftqq.com/{sendkey}.send，form 参数 title（标题）+ desp（markdown 正文）。
    返回 (是否成功, 错误信息/成功提示)。任何异常都不向上抛——与 send_wecom_message 同风格，
    通知失败不影响任务主流程。
    """
    sendkey = (sendkey or "").strip()
    title = (title or "").strip()
    if not sendkey:
        return False, "未配置 SendKey"
    if not title:
        return False, "消息标题为空"

    url = f"{SERVERCHAN_BASE}/{sendkey}.send"
    form_data: dict = {"title": title, "desp": desp or ""}
    try:
        resp = requests.post(url, data=form_data, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        return False, f"请求 Server酱 接口失败：{e}"

    try:
        data = resp.json()
    except Exception:
        return False, f"响应解析失败（HTTP {resp.status_code}）：{resp.text[:200]}"

    if data.get("code") == 0:
        return True, data.get("message") or "发送成功"
    return False, f"Server酱 返回错误：code={data.get('code')}, message={data.get('message')}"


def normalize_channel(channel: Optional[str]) -> str:
    """channel 归一化：空值/未知值一律回退 wecom_webhook，保持老库/旧前端兼容。"""
    return (channel or "").strip() or "wecom_webhook"


def config_missing_hint(config: Optional[NotificationConfig]) -> Optional[str]:
    """
    按 channel 检查配置是否齐全；缺关键参数时返回给用户看的提示，齐全返回 None。
    serverchan 通道检查 SendKey，其余（含空/未知 channel）一律按企业微信检查 webhook。
    """
    if config is None:
        return "尚未配置 webhook 地址，请先填写并保存"
    if normalize_channel(config.channel) == "serverchan":
        if not (config.sendkey or "").strip():
            return "尚未配置 Server酱 SendKey，请先填写并保存"
        return None
    if not (config.webhook_url or "").strip():
        return "尚未配置 webhook 地址，请先填写并保存"
    return None


def send_by_config(
    config: NotificationConfig,
    title: str,
    content: str,
    msgtype: str = "text",
    mentioned_list: Optional[list[str]] = None,
) -> tuple[bool, str]:
    """
    按配置的 channel 分发到对应通道：
    - serverchan：POST Server酱（title=消息标题，desp=markdown 正文）；
    - 其他（含空/未知 channel）：沿用企业微信机器人逻辑。
    """
    if normalize_channel(config.channel) == "serverchan":
        return send_serverchan(config.sendkey, title, content)
    return send_wecom_message(config.webhook_url, content, msgtype=msgtype, mentioned_list=mentioned_list)


def _build_task_message(task: Task) -> tuple[str, str]:
    """根据 Task 记录构建 (标题, 正文)。标题存 NotificationLog.title，正文作为消息内容（企业微信正文 / Server酱 desp）。"""
    module_label = _MODULE_LABELS.get(task.module, task.module or "未知模块")
    task_type_label = _TASK_TYPE_LABELS.get(task.task_type, task.task_type or "任务")
    is_success = task.status == "success"
    status_label = "完成" if is_success else "失败"

    title = f"任务{status_label}：{task_type_label}（{module_label}）"

    duration_text = ""
    if task.started_at and task.finished_at:
        seconds = max(0, int((task.finished_at - task.started_at).total_seconds()))
        if seconds < 60:
            duration_text = f"{seconds} 秒"
        else:
            duration_text = f"{seconds // 60} 分 {seconds % 60} 秒"

    content_lines = [
        f"【统一工作台】任务{status_label}通知",
        f"任务：{task_type_label}",
        f"模块：{module_label}",
        f"状态：{'成功' if is_success else '失败'}",
        f"耗时：{duration_text or '-'}",
    ]

    # 采集/追踪类任务的 params 里通常带 keyword，拼进正文方便一眼看出是哪个关键词
    params = task.params if isinstance(task.params, dict) else {}
    keyword = params.get("keyword")
    if keyword:
        content_lines.insert(1, f"关键词：{keyword}")

    if task.result_summary:
        content_lines.append(f"摘要：{task.result_summary}")
    content_lines.append(f"任务ID：{task.id}")

    return title, "\n".join(content_lines)


def _notify_task_result_sync(task_id: int) -> None:
    """在独立线程里执行：读配置 → 读任务 → 按 channel 分发发送 → 落发送记录。任何异常都不外抛。"""
    db = SessionLocal()
    try:
        config = (
            db.query(NotificationConfig).order_by(NotificationConfig.id.asc()).first()
        )
        # 未启用：静默跳过，不产生发送记录
        if not config or not config.enabled:
            return
        # 按 channel 检查关键配置缺失（企业微信缺 webhook / Server酱 缺 SendKey）：
        # 同样静默跳过，避免无意义的失败记录刷屏
        if config_missing_hint(config):
            return

        task = db.get(Task, task_id)
        if not task or task.status not in ("success", "failed"):
            return

        title, content = _build_task_message(task)
        mentioned = ["@all"] if config.mention_all else None
        ok, err_msg = send_by_config(config, title, content, mentioned_list=mentioned)
        if ok:
            _log_notification(db, config.channel, title, content, "success", None)
            logger.info(f"任务 {task_id} 通知发送成功：{title}")
        else:
            _log_notification(db, config.channel, title, content, "failed", err_msg)
            logger.warning(f"任务 {task_id} 通知发送失败：{err_msg}")
    except Exception:
        logger.exception(f"任务 {task_id} 通知处理异常")
    finally:
        db.close()


def notify_task_result(task_id: int) -> None:
    """
    任务到达终态（success/failed）后的通知入口：独立线程发送，不阻塞任务执行；
    内部所有异常都被吞掉并记日志，保证通知失败不影响任务本身。
    """
    try:
        threading.Thread(
            target=_notify_task_result_sync, args=(task_id,), daemon=True
        ).start()
    except Exception:
        logger.exception(f"任务 {task_id} 通知线程启动失败")
