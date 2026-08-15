"""
多通道化新增功能测试（配套 NOTIFY_UI_REDESIGN_SPEC.md）：
1. GET /api/notify/channels 通道目录（configured/enabled/summary/fields/not_implemented）
2. 任务通知扇出：所有启用通道都收到；单通道失败不影响其他
3. 按指定 channel 发送/测试；未配置通道的友好提示
4. PushPlus 占位通道（注册可见、暂未实现）
"""
from __future__ import annotations

import pytest

import app.common.services.notify_service as notify_service
from app.common.services.notify_service import (
    config_missing_hint,
    notify_task_result,
    send_by_config,
)
from app.common.models import NotificationLog

from conftest import get_logs, seed_config, seed_task
from test_notify import FakeResponse, _SyncThread, sync_thread  # noqa: F401 复用工具


def make_post(monkeypatch, result=None, exc=None):
    """打桩 requests.post：同时兼容 data=（Server酱 form）与 json=（企业微信）。记录调用参数。"""
    calls = []

    def fake_post(url, data=None, json=None, timeout=None):
        calls.append({"url": url, "data": data, "json": json, "timeout": timeout})
        if exc is not None:
            raise exc
        return result

    monkeypatch.setattr(notify_service.requests, "post", fake_post)
    return calls


def seed_serverchan(db, *, enabled=True, sendkey="SCT123"):
    from app.common.models import NotificationConfig

    cfg = (
        db.query(NotificationConfig)
        .filter(NotificationConfig.channel == "serverchan")
        .first()
    )
    if cfg is None:
        cfg = NotificationConfig(channel="serverchan")
        db.add(cfg)
    cfg.sendkey = sendkey
    cfg.enabled = enabled
    db.commit()
    db.refresh(cfg)
    return cfg


# ============================================================ channels 目录 ==

class TestChannelsApi:
    def test_channels_default_all_unconfigured(self, client, auth_headers):
        resp = client.get("/api/notify/channels", headers=auth_headers)
        assert resp.status_code == 200
        channels = resp.json()["channels"]
        keys = [c["channel"] for c in channels]
        assert keys == ["wecom_webhook", "serverchan", "pushplus"]
        for c in channels:
            assert c["configured"] is False
            assert c["enabled"] is False
            assert c["fields"], f"{c['channel']} 应有字段定义"
            assert c["label"]
        pushplus = next(c for c in channels if c["channel"] == "pushplus")
        assert pushplus["not_implemented"] is True

    def test_channels_reflect_config_status(self, client, auth_headers, db):
        seed_config(db, enabled=True)
        seed_serverchan(db, enabled=False, sendkey="SCT1234567890abcdef")
        resp = client.get("/api/notify/channels", headers=auth_headers)
        channels = {c["channel"]: c for c in resp.json()["channels"]}
        assert channels["wecom_webhook"]["configured"] is True
        assert channels["wecom_webhook"]["enabled"] is True
        assert channels["serverchan"]["configured"] is True
        assert channels["serverchan"]["enabled"] is False
        # summary 脱敏：头尾保留、中间打码
        assert "SCT1234567" in channels["serverchan"]["summary"]
        assert "…" in channels["serverchan"]["summary"]


# ================================================================ 扇出 =======

class TestFanout:
    def test_task_notify_fans_out_to_all_enabled(self, db, sync_thread, monkeypatch):
        seed_config(db, enabled=True)
        seed_serverchan(db, enabled=True, sendkey="SCT_FANOUT")
        task = seed_task(db)

        def fake_post(url, data=None, json=None, timeout=None):
            # 按 URL 返回各通道的"成功"响应：企业微信 errcode==0，Server酱 code==0
            if url.startswith("https://qyapi"):
                return FakeResponse({"errcode": 0, "errmsg": "ok"})
            return FakeResponse({"code": 0, "message": "ok"})

        monkeypatch.setattr(notify_service.requests, "post", fake_post)
        notify_task_result(task.id)
        # 企业微信 json 载荷 + Server酱 form 载荷，各一次
        logs = get_logs(db)
        assert len(logs) == 2
        assert {log.channel for log in logs} == {"wecom_webhook", "serverchan"}
        assert all(log.status == "success" for log in logs)

    def test_task_notify_one_failure_others_succeed(self, db, sync_thread, monkeypatch):
        seed_config(db, enabled=True, webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=bad")
        seed_serverchan(db, enabled=True, sendkey="SCT_OK")
        task = seed_task(db)

        def fake_post(url, data=None, json=None, timeout=None):
            if url.startswith("https://qyapi"):
                return FakeResponse({"errcode": 93000, "errmsg": "bad key"})
            return FakeResponse({"code": 0, "message": "ok"})

        monkeypatch.setattr(notify_service.requests, "post", fake_post)
        notify_task_result(task.id)
        logs = get_logs(db)
        assert len(logs) == 2
        by_channel = {log.channel: log for log in logs}
        assert by_channel["wecom_webhook"].status == "failed"
        assert "93000" in by_channel["wecom_webhook"].error_msg
        assert by_channel["serverchan"].status == "success"

    def test_task_notify_only_enabled_channels(self, db, sync_thread, monkeypatch):
        seed_config(db, enabled=True)
        seed_serverchan(db, enabled=False, sendkey="SCT_OFF")
        task = seed_task(db)
        calls = make_post(monkeypatch, result=FakeResponse({"errcode": 0}))
        notify_task_result(task.id)
        assert len(calls) == 1  # 只发 wecom
        logs = get_logs(db)
        assert len(logs) == 1
        assert logs[0].channel == "wecom_webhook"

    def test_task_notify_disabled_only_noop(self, db, sync_thread, monkeypatch):
        seed_config(db, enabled=False)
        seed_serverchan(db, enabled=False, sendkey="SCT")
        task = seed_task(db)
        calls = make_post(monkeypatch, result=FakeResponse({"errcode": 0}))
        notify_task_result(task.id)
        assert calls == []
        assert get_logs(db) == []


# ========================================================= 指定通道发送 ======

class TestChannelSpecificSend:
    def test_test_send_specified_channel_not_enabled(self, client, auth_headers, monkeypatch):
        # 指定 serverchan 测试：即使该通道未启用，已配置即可测试（先测后开）
        client.put(
            "/api/notify/config/serverchan",
            headers=auth_headers,
            json={"sendkey": "SCT_SPEC", "enabled": False},
        )
        calls = make_post(monkeypatch, result=FakeResponse({"code": 0, "message": "ok"}))
        resp = client.post(
            "/api/notify/test",
            headers=auth_headers,
            json={"channel": "serverchan"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert calls[0]["url"] == "https://sctapi.ftqq.com/SCT_SPEC.send"

    def test_test_send_unconfigured_channel_friendly(self, client, auth_headers, monkeypatch):
        make_post(monkeypatch, result=FakeResponse({"code": 0}))
        resp = client.post(
            "/api/notify/test",
            headers=auth_headers,
            json={"channel": "serverchan"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "尚未配置" in data["message"]

    def test_manual_send_specified_channel(self, client, auth_headers, monkeypatch):
        client.put(
            "/api/notify/config/wecom_webhook",
            headers=auth_headers,
            json={"webhook_url": "https://x/webhook?key=abc", "enabled": False},
        )
        calls = make_post(monkeypatch, result=FakeResponse({"errcode": 0}))
        resp = client.post(
            "/api/notify/send",
            headers=auth_headers,
            json={"channel": "wecom_webhook", "title": "指定通道", "content": "hi"},
        )
        assert resp.json()["success"] is True
        assert calls[0]["url"] == "https://x/webhook?key=abc"  # 直接 POST 配置的 webhook 原文


# ========================================================= PushPlus 占位 ====

class TestPushplusPlaceholder:
    def test_pushplus_not_implemented(self, db):
        from app.common.models import NotificationConfig

        cfg = NotificationConfig(channel="pushplus", token="t", enabled=True)
        db.add(cfg)
        db.commit()
        ok, msg = send_by_config(cfg, "标题", "内容")
        assert ok is False
        assert "暂未接入" in msg

    def test_pushplus_missing_hint(self, db):
        from app.common.models import NotificationConfig

        cfg = NotificationConfig(channel="pushplus")
        db.add(cfg)
        db.commit()
        hint = config_missing_hint(cfg)
        assert hint is not None
        assert "暂未接入" in hint
