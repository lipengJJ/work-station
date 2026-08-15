"""
消息通知服务（多通道：企业微信机器人 / Server酱 / PushPlus 预留）。

- NotificationConfig **每通道一行**（channel 唯一键），各通道独立 enabled；
- CHANNEL_REGISTRY 是通道注册表：label/icon/描述/能力/配置字段定义（数据驱动，
  前端配置弹窗按 fields 渲染，新通道=注册表加一行）；
- notify_task_result() 是任务中心钩子入口：扇出到所有启用通道，独立线程发送，
  单通道失败不影响其他通道，绝不影响任务本身的主流程。
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Optional

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

# ---------------------------------------------------------------------------
# 通道注册表（新通道扩展点：加一行即可，前端列表/配置弹窗/能力标签全部数据驱动）
# fields: 配置弹窗的字段定义（type: text/password/textarea/switch；mono=等宽字体）
# not_implemented: True 表示注册但暂未实现发送（占位展示）
# ---------------------------------------------------------------------------
CHANNEL_REGISTRY: dict[str, dict[str, Any]] = {
    "wecom_webhook": {
        "label": "企业微信群机器人",
        "icon": "message-circle",
        "description": "任务通知推送到企业微信群，可邀请个人微信入群接收",
        "capabilities": ["text", "markdown", "mention_all"],
        "fields": [
            {
                "key": "webhook_url",
                "label": "Webhook 地址",
                "type": "textarea",
                "mono": True,
                "placeholder": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key",
                "extra": "从企业微信群机器人复制完整地址（含 key 参数）",
            },
            {
                "key": "mention_all",
                "label": "@所有人",
                "type": "switch",
                "extra": "text 消息附带 @all，适合需要强提醒的群",
            },
        ],
    },
    "serverchan": {
        "label": "Server酱",
        "icon": "send",
        "description": "推送直达个人微信（方糖服务号），无需建群",
        "capabilities": ["markdown"],
        "fields": [
            {
                "key": "sendkey",
                "label": "SendKey",
                "type": "password",
                "mono": True,
                "placeholder": "SCTxxxxxxxxxxxxxxxxxxxxxxxx",
                "extra": "前往 https://sct.ftqq.com 微信扫码登录，在「SendKey」页面复制你的 Key",
            },
        ],
    },
    "pushplus": {
        "label": "PushPlus",
        "icon": "bell",
        "description": "微信公众号推送（预留通道，接入后一行注册即可用）",
        "capabilities": ["markdown"],
        "not_implemented": True,
        "fields": [
            {
                "key": "token",
                "label": "Token",
                "type": "password",
                "mono": True,
                "placeholder": "xxxxxxxxxxxxxxxx",
                "extra": "前往 https://www.pushplus.plus 微信扫码关注获取 Token",
            },
        ],
    },
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
    """channel 归一化：空值回退 wecom_webhook（保持老库/旧调用兼容）；未知值原样返回，由下游兜底。"""
    return (channel or "").strip() or "wecom_webhook"


def config_missing_hint(config: Optional[NotificationConfig]) -> Optional[str]:
    """
    按 channel 检查配置是否齐全；缺关键参数时返回给用户看的提示，齐全返回 None。
    serverchan 通道检查 SendKey；pushplus（未实现）提示未接入；其余按企业微信检查 webhook。
    """
    if config is None:
        return "尚未配置 webhook 地址，请先填写并保存"
    channel = normalize_channel(config.channel)
    if channel == "serverchan":
        if not (config.sendkey or "").strip():
            return "尚未配置 Server酱 SendKey，请先填写并保存"
        return None
    if channel == "pushplus":
        return "PushPlus 通道暂未接入，敬请期待"
    if not (config.webhook_url or "").strip():
        return "尚未配置 webhook 地址，请先填写并保存"
    return None


def _mask_value(value: str) -> str:
    """凭据脱敏摘要：保留头尾，中间打码，超长截断。"""
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= 12:
        return value[:4] + "****"
    return value[:10] + "…" + value[-6:]


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
    - pushplus：占位通道，暂未实现；
    - 其他（含空/未知 channel）：沿用企业微信机器人逻辑。
    """
    channel = normalize_channel(config.channel)
    if channel == "serverchan":
        return send_serverchan(config.sendkey, title, content)
    if channel == "pushplus":
        return False, "PushPlus 通道暂未接入"
    return send_wecom_message(config.webhook_url, content, msgtype=msgtype, mentioned_list=mentioned_list)


# ---------------------------------------------------------------------------
# 配置查询 / 保存（多通道：每通道一行）
# ---------------------------------------------------------------------------

def get_config_by_channel(db: Session, channel: str) -> Optional[NotificationConfig]:
    """按 channel 读取单通道配置；不存在返回 None。"""
    return (
        db.query(NotificationConfig)
        .filter(NotificationConfig.channel == normalize_channel(channel))
        .first()
    )


def list_configs(db: Session) -> list[NotificationConfig]:
    """全部通道配置行（按 id 排序）。"""
    return db.query(NotificationConfig).order_by(NotificationConfig.id.asc()).all()


def upsert_config(
    db: Session,
    channel: str,
    *,
    webhook_url: str = "",
    sendkey: str = "",
    token: str = "",
    enabled: bool = False,
    mention_all: bool = False,
) -> NotificationConfig:
    """保存单通道配置（upsert：按 channel 覆盖）。"""
    channel = normalize_channel(channel)
    config = get_config_by_channel(db, channel)
    if not config:
        config = NotificationConfig(channel=channel)
        db.add(config)
    config.webhook_url = (webhook_url or "").strip()
    config.sendkey = (sendkey or "").strip()
    config.token = (token or "").strip()
    config.enabled = enabled
    config.mention_all = mention_all
    db.commit()
    db.refresh(config)
    return config


def list_channel_infos(db: Session) -> list[dict[str, Any]]:
    """
    通道目录（G4 公共入口）：注册表元信息 + 实时配置状态合并。
    供 GET /api/notify/channels 与前端通道列表/发送组件使用。
    """
    configs = {c.channel: c for c in list_configs(db)}
    infos: list[dict[str, Any]] = []
    for channel, meta in CHANNEL_REGISTRY.items():
        config = configs.get(channel)
        configured = config is not None and config_missing_hint(config) is None
        summary = ""
        if configured and config is not None:
            if channel == "serverchan":
                summary = _mask_value(config.sendkey)
            elif channel == "pushplus":
                summary = _mask_value(config.token)
            else:
                summary = (config.webhook_url or "")[:64] + ("…" if len(config.webhook_url or "") > 64 else "")
        infos.append(
            {
                "channel": channel,
                "label": meta["label"],
                "icon": meta.get("icon", "bell"),
                "description": meta.get("description", ""),
                "configured": configured,
                "enabled": bool(config and config.enabled),
                "summary": summary,
                "capabilities": meta.get("capabilities", []),
                "fields": meta.get("fields", []),
                "not_implemented": bool(meta.get("not_implemented", False)),
            }
        )
    return infos


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
    """在独立线程里执行：读任务 → 扇出到所有启用且配置齐全的通道 → 逐通道落发送记录。任何异常都不外抛。"""
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if not task or task.status not in ("success", "failed"):
            return

        # 多通道化：遍历所有启用且配置齐全的通道，逐通道发送（单通道失败不影响其他）
        configs = [c for c in list_configs(db) if c.enabled and not config_missing_hint(c)]
        if not configs:
            return

        title, content = _build_task_message(task)
        for config in configs:
            mentioned = ["@all"] if config.mention_all else None
            ok, err_msg = send_by_config(config, title, content, mentioned_list=mentioned)
            if ok:
                _log_notification(db, config.channel, title, content, "success", None)
                logger.info(f"任务 {task_id} 通知发送成功[{config.channel}]：{title}")
            else:
                _log_notification(db, config.channel, title, content, "failed", err_msg)
                logger.warning(f"任务 {task_id} 通知发送失败[{config.channel}]：{err_msg}")
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
