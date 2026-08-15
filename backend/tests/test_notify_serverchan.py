"""
Server酱（ServerChan）推送通道 —— QA 独立验证测试。

覆盖（对应验证要求 a~i）：
1. send_serverchan：成功（URL https://sctapi.ftqq.com/{key}.send、form title/desp、timeout=8、
   code==0 → ok=True）、业务错误码（code=1024）、超时/连接异常不上抛、空 SendKey 不发请求
2. send_by_config 分发：channel='serverchan' → Server酱（title 正确传递）；
   channel='wecom_webhook' → 企业微信（mentioned_list/@all 仍生效）；未知 channel 回退企业微信
3. notify_task_result：serverchan 启用+SendKey → 成功落 log(status=success, channel=serverchan)；
   缺 SendKey → 静默跳过不落 log；wecom 老逻辑回归
4. 配置 CRUD：PUT（channel=serverchan+sendkey）→ GET 一致；sendkey 超长 256 → 422；
   channel 空 → 回退 wecom_webhook；默认 GET 含 sendkey
5. API：POST /api/notify/test 在 serverchan 配置下按 serverchan 分发并落 log；
   无配置 → 友好错误；无 token → 401
6. 老库加列：旧版 notification_config 表（无 sendkey 列）→ init_db 补列、旧数据保留、
   再调一次幂等

所有真实 HTTP 一律 mock（monkeypatch notify_service.requests.post），绝不请求 Server酱。
数据库使用 conftest 提供的临时 SQLite；老库加列用例使用独立临时库 + 替换模块级 engine。
"""
from __future__ import annotations

import requests
import pytest

import app.common.services.notify_service as notify_service
from app.common.services.notify_service import (
    config_missing_hint,
    notify_task_result,
    send_by_config,
    send_serverchan,
)
from app.common.models import NotificationConfig

from conftest import get_logs, seed_config, seed_task


# ================================================================ 工具 ========

class FakeResponse:
    """模拟 requests.Response：只实现代码用到的 json()/status_code/text。"""

    def __init__(self, payload=None, status_code: int = 200, text: str = "", json_error: bool = False):
        self._payload = payload
        self.status_code = status_code
        self.text = text
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("Expecting value")
        return self._payload


class _SyncThread:
    """把 threading.Thread 换成同步执行：notify_task_result 立即跑完，便于断言。"""

    instances: list["_SyncThread"] = []

    def __init__(self, target=None, args=(), kwargs=None, *, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.daemon = daemon
        _SyncThread.instances.append(self)

    def start(self):
        self.target(*self.args, **self.kwargs)


@pytest.fixture()
def sync_thread(monkeypatch):
    """monkeypatch notify_service.threading.Thread 为同步 stub。"""
    _SyncThread.instances = []
    monkeypatch.setattr(notify_service.threading, "Thread", _SyncThread)
    return _SyncThread


def make_post(monkeypatch, result=None, exc=None):
    """打桩 requests.post：同时兼容 data=（Server酱 form）与 json=（企业微信）两种调用。记录调用参数。"""
    calls = []

    def fake_post(url, data=None, json=None, timeout=None):
        calls.append({"url": url, "data": data, "json": json, "timeout": timeout})
        if exc is not None:
            raise exc
        return result

    monkeypatch.setattr(notify_service.requests, "post", fake_post)
    return calls


def seed_serverchan_config(db, *, enabled: bool = True, sendkey: str = "SCT123", mention_all: bool = False) -> NotificationConfig:
    """写入/覆盖单例配置（id=1），channel='serverchan'。"""
    cfg = db.get(NotificationConfig, 1)
    if cfg is None:
        cfg = NotificationConfig(id=1)
        db.add(cfg)
    cfg.channel = "serverchan"
    cfg.webhook_url = ""
    cfg.sendkey = sendkey
    cfg.enabled = enabled
    cfg.mention_all = mention_all
    db.commit()
    db.refresh(cfg)
    return cfg


# ============================================================ send_serverchan ==

class TestSendServerchan:
    def test_success_url_form_timeout(self, monkeypatch):
        calls = make_post(monkeypatch, result=FakeResponse({"code": 0, "message": "ok"}))
        ok, msg = send_serverchan("SCT123", "标题", "正文")
        assert ok is True
        assert msg == "ok"
        assert len(calls) == 1
        assert calls[0]["url"] == "https://sctapi.ftqq.com/SCT123.send"
        assert calls[0]["data"] == {"title": "标题", "desp": "正文"}
        assert calls[0]["timeout"] == notify_service.REQUEST_TIMEOUT == 8

    def test_desp_omitted_defaults_empty(self, monkeypatch):
        calls = make_post(monkeypatch, result=FakeResponse({"code": 0}))
        ok, _ = send_serverchan("SCT123", "标题")
        assert ok is True
        assert calls[0]["data"] == {"title": "标题", "desp": ""}

    def test_code_nonzero(self, monkeypatch):
        make_post(monkeypatch, result=FakeResponse({"code": 1024, "message": "参数错误"}))
        ok, msg = send_serverchan("SCT123", "标题", "正文")
        assert ok is False
        assert "1024" in msg
        assert "参数错误" in msg

    def test_timeout_no_raise(self, monkeypatch):
        make_post(monkeypatch, exc=requests.Timeout("timed out"))
        ok, msg = send_serverchan("SCT123", "标题", "正文")
        assert ok is False
        assert "请求 Server酱 接口失败" in msg

    def test_connection_error_no_raise(self, monkeypatch):
        make_post(monkeypatch, exc=requests.ConnectionError("conn refused"))
        ok, msg = send_serverchan("SCT123", "标题", "正文")
        assert ok is False
        assert "请求 Server酱 接口失败" in msg

    def test_empty_sendkey_no_request(self, monkeypatch):
        calls = make_post(monkeypatch, result=FakeResponse({"code": 0}))
        ok, msg = send_serverchan("   ", "标题", "正文")
        assert ok is False
        assert "未配置 SendKey" in msg
        assert calls == []

    def test_empty_title_no_request(self, monkeypatch):
        calls = make_post(monkeypatch, result=FakeResponse({"code": 0}))
        ok, msg = send_serverchan("SCT123", "   ", "正文")
        assert ok is False
        assert "消息标题为空" in msg
        assert calls == []

    def test_non_json_response(self, monkeypatch):
        make_post(
            monkeypatch,
            result=FakeResponse(status_code=500, text="<html>bad gateway</html>", json_error=True),
        )
        ok, msg = send_serverchan("SCT123", "标题", "正文")
        assert ok is False
        assert "响应解析失败" in msg


# ============================================================ send_by_config ==

class TestSendByConfig:
    def test_serverchan_dispatch_title_passed(self, db, monkeypatch):
        cfg = seed_serverchan_config(db, sendkey="SCT456")
        calls = make_post(monkeypatch, result=FakeResponse({"code": 0, "message": "ok"}))
        ok, msg = send_by_config(cfg, "标题A", "正文B")
        assert ok is True
        assert len(calls) == 1
        assert calls[0]["url"] == "https://sctapi.ftqq.com/SCT456.send"
        # title 正确传递为 Server酱 的 title，content 作为 desp
        assert calls[0]["data"] == {"title": "标题A", "desp": "正文B"}
        assert calls[0]["json"] is None  # Server酱 走 form 而非 json

    def test_wecom_dispatch_keeps_mention(self, db, monkeypatch):
        cfg = seed_config(db, enabled=True, mention_all=True)
        calls = make_post(monkeypatch, result=FakeResponse({"errcode": 0, "errmsg": "ok"}))
        ok, _ = send_by_config(cfg, "标题", "内容", msgtype="text", mentioned_list=["@all"])
        assert ok is True
        assert calls[0]["url"].startswith("https://qyapi.weixin.qq.com")
        assert calls[0]["data"] is None  # 企业微信走 json
        assert calls[0]["json"] == {"msgtype": "text", "text": {"content": "内容", "mentioned_list": ["@all"]}}

    def test_unknown_channel_falls_back_to_wecom(self, db, monkeypatch):
        cfg = seed_config(db, enabled=True, channel="mystery")
        calls = make_post(monkeypatch, result=FakeResponse({"errcode": 0}))
        ok, _ = send_by_config(cfg, "标题", "内容")
        assert ok is True
        assert calls[0]["url"].startswith("https://qyapi.weixin.qq.com")


# ============================================================ notify_task_result ==

class TestNotifyTaskResultServerchan:
    """通过公开入口 notify_task_result(task_id) 触发（线程被替换为同步执行）。"""

    def test_serverchan_success_writes_log(self, db, sync_thread, monkeypatch):
        seed_serverchan_config(db, enabled=True, sendkey="SCT123")
        task = seed_task(db, result_summary="采集到 12 篇笔记")
        calls = make_post(monkeypatch, result=FakeResponse({"code": 0, "message": "ok"}))
        notify_task_result(task.id)
        assert len(calls) == 1
        assert calls[0]["url"] == "https://sctapi.ftqq.com/SCT123.send"
        logs = get_logs(db)
        assert len(logs) == 1
        log = logs[0]
        assert log.status == "success"
        assert log.error_msg is None
        assert log.channel == "serverchan"
        assert log.title == "任务完成：笔记采集（小红书）"
        assert "采集到 12 篇笔记" in (log.content or "")
        # mention_all=False -> 不传 @all（Server酱 无 @all 概念，发送不受影响）

    def test_serverchan_missing_sendkey_silent_skip(self, db, sync_thread, monkeypatch):
        seed_serverchan_config(db, enabled=True, sendkey="")
        task = seed_task(db)
        calls = make_post(monkeypatch, result=FakeResponse({"code": 0}))
        notify_task_result(task.id)
        assert calls == []
        assert get_logs(db) == []

    def test_serverchan_disabled_silent_skip(self, db, sync_thread, monkeypatch):
        seed_serverchan_config(db, enabled=False, sendkey="SCT123")
        task = seed_task(db)
        calls = make_post(monkeypatch, result=FakeResponse({"code": 0}))
        notify_task_result(task.id)
        assert calls == []
        assert get_logs(db) == []

    def test_serverchan_failure_writes_failed_log(self, db, sync_thread, monkeypatch):
        seed_serverchan_config(db, enabled=True, sendkey="SCT123")
        task = seed_task(db, status="failed")
        make_post(monkeypatch, result=FakeResponse({"code": 1024, "message": "参数错误"}))
        notify_task_result(task.id)
        logs = get_logs(db)
        assert len(logs) == 1
        assert logs[0].status == "failed"
        assert logs[0].error_msg and "1024" in logs[0].error_msg
        assert logs[0].title == "任务失败：笔记采集（小红书）"

    def test_wecom_regression_still_works(self, db, sync_thread, monkeypatch):
        seed_config(db, enabled=True, mention_all=True)
        task = seed_task(db, result_summary="采集到 12 篇笔记")
        calls = make_post(monkeypatch, result=FakeResponse({"errcode": 0, "errmsg": "ok"}))
        notify_task_result(task.id)
        assert len(calls) == 1
        logs = get_logs(db)
        assert len(logs) == 1
        assert logs[0].status == "success"
        assert logs[0].channel == "wecom_webhook"
        assert calls[0]["json"]["text"]["mentioned_list"] == ["@all"]


# ============================================================ 配置 CRUD / API ==

class TestServerchanConfigCrud:
    def test_default_get_contains_sendkey(self, client, auth_headers):
        resp = client.get("/api/notify/config", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["sendkey"] == ""
        assert data["channel"] == "wecom_webhook"

    def test_put_get_serverchan_roundtrip(self, client, auth_headers):
        put = client.put(
            "/api/notify/config",
            headers=auth_headers,
            json={"channel": "serverchan", "sendkey": "  SCT789  ", "enabled": True, "mention_all": False},
        )
        assert put.status_code == 200
        put_data = put.json()
        assert put_data["channel"] == "serverchan"
        assert put_data["sendkey"] == "SCT789"  # 已 strip
        assert put_data["enabled"] is True

        get = client.get("/api/notify/config", headers=auth_headers)
        assert get.status_code == 200
        get_data = get.json()
        assert get_data["channel"] == "serverchan"
        assert get_data["sendkey"] == "SCT789"

    def test_sendkey_too_long_422(self, client, auth_headers):
        resp = client.put(
            "/api/notify/config",
            headers=auth_headers,
            json={"channel": "serverchan", "sendkey": "x" * 257, "enabled": True},
        )
        assert resp.status_code == 422

    def test_sendkey_length_256_ok(self, client, auth_headers):
        resp = client.put(
            "/api/notify/config",
            headers=auth_headers,
            json={"channel": "serverchan", "sendkey": "x" * 256, "enabled": True},
        )
        assert resp.status_code == 200
        assert resp.json()["sendkey"] == "x" * 256

    def test_channel_empty_falls_back_wecom(self, client, auth_headers):
        resp = client.put(
            "/api/notify/config",
            headers=auth_headers,
            json={"channel": "", "sendkey": "SCT1", "enabled": True},
        )
        assert resp.status_code == 200
        assert resp.json()["channel"] == "wecom_webhook"


class TestServerchanApi:
    def test_test_send_no_token_401(self, client, db):
        resp = client.post("/api/notify/test")
        assert resp.status_code == 401

    def test_test_send_no_config_friendly_error(self, client, auth_headers, monkeypatch):
        make_post(monkeypatch, result=FakeResponse({"code": 0}))
        resp = client.post("/api/notify/test", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "webhook" in data["message"]

    def test_test_send_serverchan_missing_sendkey_friendly(self, client, auth_headers, monkeypatch):
        client.put(
            "/api/notify/config",
            headers=auth_headers,
            json={"channel": "serverchan", "sendkey": "", "enabled": True},
        )
        make_post(monkeypatch, result=FakeResponse({"code": 0}))
        resp = client.post("/api/notify/test", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "SendKey" in data["message"]

    def test_test_send_serverchan_dispatch_and_log(self, client, auth_headers, monkeypatch):
        client.put(
            "/api/notify/config",
            headers=auth_headers,
            json={"channel": "serverchan", "sendkey": "SCTABC", "enabled": False},
        )
        calls = make_post(monkeypatch, result=FakeResponse({"code": 0, "message": "ok"}))
        resp = client.post("/api/notify/test", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # 按 serverchan 分发：URL 指向 sctapi，form 含 title=测试消息
        assert len(calls) == 1
        assert calls[0]["url"] == "https://sctapi.ftqq.com/SCTABC.send"
        assert calls[0]["data"]["title"] == "测试消息"
        # 发送记录已写入，channel=serverchan
        resp_logs = client.get("/api/notify/logs", headers=auth_headers)
        items = resp_logs.json()["items"]
        assert len(items) == 1
        assert items[0]["status"] == "success"
        assert items[0]["channel"] == "serverchan"
        assert items[0]["title"] == "测试消息"

    def test_test_send_serverchan_failure_logs(self, client, auth_headers, monkeypatch):
        client.put(
            "/api/notify/config",
            headers=auth_headers,
            json={"channel": "serverchan", "sendkey": "SCTBAD", "enabled": False},
        )
        make_post(monkeypatch, result=FakeResponse({"code": 1024, "message": "参数错误"}))
        resp = client.post("/api/notify/test", headers=auth_headers)
        assert resp.json()["success"] is False
        resp_logs = client.get("/api/notify/logs", headers=auth_headers)
        items = resp_logs.json()["items"]
        assert items[0]["status"] == "failed"
        assert items[0]["channel"] == "serverchan"
        assert items[0]["error_msg"] and "1024" in items[0]["error_msg"]

    def test_manual_send_serverchan_dispatch(self, client, auth_headers, monkeypatch):
        client.put(
            "/api/notify/config",
            headers=auth_headers,
            json={"channel": "serverchan", "sendkey": "SCTXYZ", "enabled": False},
        )
        calls = make_post(monkeypatch, result=FakeResponse({"code": 0, "message": "ok"}))
        resp = client.post(
            "/api/notify/send",
            headers=auth_headers,
            json={"title": "联调通知", "content": "# 标题\n正文", "msgtype": "markdown"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert calls[0]["url"] == "https://sctapi.ftqq.com/SCTXYZ.send"
        assert calls[0]["data"]["title"] == "联调通知"
        assert calls[0]["data"]["desp"] == "# 标题\n正文"
        resp_logs = client.get("/api/notify/logs", headers=auth_headers)
        assert resp_logs.json()["items"][0]["title"] == "联调通知"


# ============================================================ config_missing_hint ==

class TestConfigMissingHint:
    def test_none_config(self):
        assert "webhook" in config_missing_hint(None)

    def test_serverchan_missing_sendkey(self, db):
        cfg = seed_serverchan_config(db, sendkey="")
        hint = config_missing_hint(cfg)
        assert hint is not None
        assert "SendKey" in hint

    def test_serverchan_with_sendkey_ok(self, db):
        cfg = seed_serverchan_config(db, sendkey="SCT1")
        assert config_missing_hint(cfg) is None

    def test_wecom_missing_webhook(self, db):
        cfg = seed_config(db, webhook_url="")
        hint = config_missing_hint(cfg)
        assert hint is not None
        assert "webhook" in hint


# ============================================================ 老库加列（迁移） ===

class TestOldDbMigration:
    def test_init_db_adds_sendkey_column_and_preserves_data(self, monkeypatch, tmp_path):
        from sqlalchemy import create_engine, inspect, text

        from app.core import database

        # 1) 独立临时库手工建「旧版」notification_config 表（无 sendkey 列）+ 旧数据
        legacy_path = tmp_path / "legacy.db"
        legacy_engine = create_engine(f"sqlite:///{legacy_path}")
        with legacy_engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE notification_config ("
                    "id INTEGER PRIMARY KEY, "
                    "channel VARCHAR(32) DEFAULT 'wecom_webhook', "
                    "webhook_url VARCHAR(512) DEFAULT '', "
                    "enabled BOOLEAN DEFAULT 0, "
                    "mention_all BOOLEAN DEFAULT 0, "
                    "created_at DATETIME, "
                    "updated_at DATETIME)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO notification_config "
                    "(id, channel, webhook_url, enabled, mention_all) "
                    "VALUES (1, 'wecom_webhook', 'https://old.example/webhook?key=legacy', 1, 0)"
                )
            )

        # 2) 替换模块级 engine 并复位进程内标记，模拟「老库 + 首次启动」
        orig_engine = database.engine
        orig_checked = database._schema_checked
        database.engine = legacy_engine
        database._schema_checked = False
        try:
            database.init_db()

            # 3) 断言：sendkey 列被 ALTER 添加，旧数据保留
            inspector = inspect(legacy_engine)
            cols = {c["name"] for c in inspector.get_columns("notification_config")}
            assert "sendkey" in cols, "init_db 后应补上 sendkey 列"
            with legacy_engine.connect() as conn:
                row = conn.execute(
                    text("SELECT id, channel, webhook_url, sendkey FROM notification_config")
                ).fetchone()
                assert row.id == 1
                assert row.channel == "wecom_webhook"
                assert row.webhook_url == "https://old.example/webhook?key=legacy"
                assert row.sendkey == ""  # DEFAULT '' 生效，旧行不因加列而丢数据

            # 4) 幂等：复位标记后再跑一次，不报错、列集合不变
            database._schema_checked = False
            database._ensure_notification_config_sendkey()
            cols_after = {c["name"] for c in inspect(legacy_engine).get_columns("notification_config")}
            assert cols_after == cols, "重复调用不应重复加列或报错"

            # 5) 新引擎下的 SQLAlchemy 模型也能正常读写 sendkey（模型与库结构对齐）
            LegacySession = database.sessionmaker(bind=legacy_engine)
            with LegacySession() as session:
                cfg = session.get(NotificationConfig, 1)
                assert cfg is not None
                assert cfg.sendkey == ""
                cfg.sendkey = "SCT_NEW"
                session.commit()
                session.refresh(cfg)
                assert cfg.sendkey == "SCT_NEW"
        finally:
            database.engine = orig_engine
            database._schema_checked = orig_checked
