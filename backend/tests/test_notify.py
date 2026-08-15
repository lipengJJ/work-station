"""
微信消息通知功能 —— QA 独立验证测试。

覆盖：
1. send_wecom_message 成功 / 企业微信错误码 / 网络异常 / 空地址 / 非法 msgtype /
   markdown 载荷 / mentioned_list / 非 JSON 响应
2. notify_task_result：未启用/无 webhook/无配置静默跳过；成功落 success；失败落 failed；
   任务不存在不崩溃；任务非终态不发；线程 daemon 属性；线程启动异常被吞
3. /api/notify 路由：JWT 401、配置 GET/PUT、测试发送、手动发送、日志分页、参数校验
4. _build_task_message 正文构建

所有真实 HTTP 一律 mock（monkeypatch notify_service.requests.post），绝不请求企业微信。
数据库使用 conftest 提供的临时 SQLite。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import app.common.services.notify_service as notify_service
from app.common.services.notify_service import (
    _build_task_message,
    notify_task_result,
    send_wecom_message,
)
from app.common.models import NotificationLog

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
    """打桩 requests.post：返回 FakeResponse(result) 或抛出 exc。记录调用参数。"""
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "json": json, "timeout": timeout})
        if exc is not None:
            raise exc
        return result

    monkeypatch.setattr(notify_service.requests, "post", fake_post)
    return calls


# ============================================================ send_wecom_message ==

class TestSendWecomMessage:
    def test_success_errcode_0(self, monkeypatch):
        calls = make_post(monkeypatch, result=FakeResponse({"errcode": 0, "errmsg": "ok"}))
        ok, msg = send_wecom_message("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k", "你好")
        assert ok is True
        assert msg == "ok"
        assert len(calls) == 1
        assert calls[0]["url"].startswith("https://qyapi.weixin.qq.com")
        assert calls[0]["json"] == {"msgtype": "text", "text": {"content": "你好"}}
        assert calls[0]["timeout"] == notify_service.REQUEST_TIMEOUT

    def test_errcode_93000(self, monkeypatch):
        make_post(monkeypatch, result=FakeResponse({"errcode": 93000, "errmsg": "invalid webhook"}))
        ok, msg = send_wecom_message("https://x/webhook?key=k", "你好")
        assert ok is False
        assert "93000" in msg
        assert "invalid webhook" in msg

    def test_timeout_no_raise(self, monkeypatch):
        make_post(monkeypatch, exc=__import__("requests").Timeout("timed out"))
        ok, msg = send_wecom_message("https://x/webhook?key=k", "你好")
        assert ok is False
        assert "请求企业微信接口失败" in msg

    def test_connection_error_no_raise(self, monkeypatch):
        make_post(monkeypatch, exc=__import__("requests").ConnectionError("conn refused"))
        ok, msg = send_wecom_message("https://x/webhook?key=k", "你好")
        assert ok is False
        assert "请求企业微信接口失败" in msg

    def test_empty_url(self, monkeypatch):
        calls = make_post(monkeypatch, result=FakeResponse({"errcode": 0}))
        ok, msg = send_wecom_message("   ", "你好")
        assert ok is False
        assert "未配置 webhook" in msg
        assert calls == []

    def test_invalid_msgtype(self, monkeypatch):
        calls = make_post(monkeypatch, result=FakeResponse({"errcode": 0}))
        ok, msg = send_wecom_message("https://x/webhook?key=k", "你好", msgtype="xml")
        assert ok is False
        assert "不支持的 msgtype" in msg
        assert calls == []

    def test_markdown_payload(self, monkeypatch):
        calls = make_post(monkeypatch, result=FakeResponse({"errcode": 0, "errmsg": "ok"}))
        ok, _ = send_wecom_message("https://x/webhook?key=k", "# 标题", msgtype="markdown")
        assert ok is True
        assert calls[0]["json"] == {"msgtype": "markdown", "markdown": {"content": "# 标题"}}

    def test_mentioned_list(self, monkeypatch):
        calls = make_post(monkeypatch, result=FakeResponse({"errcode": 0}))
        ok, _ = send_wecom_message("https://x/webhook?key=k", "你好", mentioned_list=["@all"])
        assert ok is True
        assert calls[0]["json"]["text"]["mentioned_list"] == ["@all"]

    def test_empty_mentioned_list_omitted(self, monkeypatch):
        calls = make_post(monkeypatch, result=FakeResponse({"errcode": 0}))
        ok, _ = send_wecom_message("https://x/webhook?key=k", "你好", mentioned_list=[])
        assert ok is True
        assert "mentioned_list" not in calls[0]["json"]["text"]

    def test_non_json_response(self, monkeypatch):
        make_post(
            monkeypatch,
            result=FakeResponse(status_code=500, text="<html>bad gateway</html>", json_error=True),
        )
        ok, msg = send_wecom_message("https://x/webhook?key=k", "你好")
        assert ok is False
        assert "响应解析失败" in msg


# ============================================================ notify_task_result ==

class TestNotifyTaskResult:
    """通过公开入口 notify_task_result(task_id) 触发（线程被替换为同步执行）。"""

    def test_disabled_config_noop(self, db, sync_thread, monkeypatch):
        seed_config(db, enabled=False)
        task = seed_task(db)
        calls = make_post(monkeypatch, result=FakeResponse({"errcode": 0}))
        notify_task_result(task.id)
        assert calls == []
        assert get_logs(db) == []

    def test_enabled_but_no_webhook_noop(self, db, sync_thread, monkeypatch):
        seed_config(db, enabled=True, webhook_url="   ")
        task = seed_task(db)
        calls = make_post(monkeypatch, result=FakeResponse({"errcode": 0}))
        notify_task_result(task.id)
        assert calls == []
        assert get_logs(db) == []

    def test_no_config_noop(self, db, sync_thread, monkeypatch):
        task = seed_task(db)
        calls = make_post(monkeypatch, result=FakeResponse({"errcode": 0}))
        notify_task_result(task.id)
        assert calls == []
        assert get_logs(db) == []

    def test_success_writes_log(self, db, sync_thread, monkeypatch):
        seed_config(db, enabled=True, mention_all=True)
        task = seed_task(db, result_summary="采集到 12 篇笔记")
        calls = make_post(monkeypatch, result=FakeResponse({"errcode": 0, "errmsg": "ok"}))
        notify_task_result(task.id)
        assert len(calls) == 1
        logs = get_logs(db)
        assert len(logs) == 1
        log = logs[0]
        assert log.status == "success"
        assert log.error_msg is None
        assert log.channel == "wecom_webhook"
        assert log.title == "任务完成：笔记采集（小红书）"
        assert "采集到 12 篇笔记" in (log.content or "")
        # mention_all=True -> mentioned_list=["@all"]
        assert calls[0]["json"]["text"]["mentioned_list"] == ["@all"]

    def test_failure_writes_failed_log(self, db, sync_thread, monkeypatch):
        seed_config(db, enabled=True)
        task = seed_task(db, status="failed")
        make_post(monkeypatch, result=FakeResponse({"errcode": 93000, "errmsg": "bad key"}))
        notify_task_result(task.id)
        logs = get_logs(db)
        assert len(logs) == 1
        assert logs[0].status == "failed"
        assert logs[0].error_msg and "93000" in logs[0].error_msg
        assert logs[0].title == "任务失败：笔记采集（小红书）"

    def test_task_not_found_no_crash(self, db, sync_thread, monkeypatch):
        seed_config(db, enabled=True)
        calls = make_post(monkeypatch, result=FakeResponse({"errcode": 0}))
        notify_task_result(999_999)  # 不存在的任务 id
        assert calls == []
        assert get_logs(db) == []

    def test_task_not_terminal_no_send(self, db, sync_thread, monkeypatch):
        seed_config(db, enabled=True)
        task = seed_task(db, status="running")
        calls = make_post(monkeypatch, result=FakeResponse({"errcode": 0}))
        notify_task_result(task.id)
        assert calls == []
        assert get_logs(db) == []

    def test_thread_is_daemon(self, db, monkeypatch):
        seed_config(db, enabled=False)
        task = seed_task(db)
        _SyncThread.instances = []
        monkeypatch.setattr(notify_service.threading, "Thread", _SyncThread)
        notify_task_result(task.id)
        assert len(_SyncThread.instances) == 1
        assert _SyncThread.instances[0].daemon is True
        assert _SyncThread.instances[0].args == (task.id,)

    def test_thread_start_exception_caught(self, db, monkeypatch):
        seed_config(db, enabled=False)
        seed_task(db)

        class _BoomThread:
            def __init__(self, **kwargs):
                pass

            def start(self):
                raise RuntimeError("cannot start thread")

        monkeypatch.setattr(notify_service.threading, "Thread", _BoomThread)
        # 不抛异常即通过
        notify_task_result(1)


# ============================================================== 消息正文构建 ====

class TestBuildTaskMessage:
    def test_keyword_and_summary_and_duration(self, db):
        start = datetime.now(timezone.utc) - timedelta(seconds=125)
        finish = datetime.now(timezone.utc)
        task = seed_task(
            db,
            params={"keyword": "护肤测评"},
            result_summary="新增命中 3 篇",
            started_at=start,
            finished_at=finish,
        )
        title, content = _build_task_message(task)
        assert title == "任务完成：笔记采集（小红书）"
        assert "关键词：护肤测评" in content
        assert "摘要：新增命中 3 篇" in content
        # 125 秒 -> "2 分 5 秒"
        assert "2 分 5 秒" in content

    def test_no_start_finish_no_crash(self, db):
        task = seed_task(db, started_at=None, finished_at=None)
        title, content = _build_task_message(task)
        assert "耗时：-" in content
        assert "任务ID：" in content

    def test_failed_status_label(self, db):
        task = seed_task(db, status="failed")
        title, _ = _build_task_message(task)
        assert title == "任务失败：笔记采集（小红书）"

    def test_unknown_module_fallback(self, db):
        task = seed_task(db, module="mystery", task_type="mystery_type", status="failed")
        title, content = _build_task_message(task)
        assert "mystery" in title
        assert "mystery" in content


# ================================================================== API 路由 ==

class TestNotifyApi:
    def test_config_without_token_401(self, client, db):
        for method, path in [
            ("get", "/api/notify/config"),
            ("put", "/api/notify/config"),
            ("post", "/api/notify/test"),
            ("post", "/api/notify/send"),
            ("get", "/api/notify/logs"),
        ]:
            kwargs = {"json": {}} if method in ("put", "post") else {}
            resp = getattr(client, method)(path, **kwargs)
            assert resp.status_code == 401, f"{method} {path} 应返回 401"

    def test_config_defaults(self, client, auth_headers):
        resp = client.get("/api/notify/config", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 1
        assert data["channel"] == "wecom_webhook"
        assert data["webhook_url"] == ""
        assert data["enabled"] is False
        assert data["mention_all"] is False

    def test_config_put_get_roundtrip(self, client, auth_headers):
        put = client.put(
            "/api/notify/config",
            headers=auth_headers,
            json={"webhook_url": "  https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc  ",
                  "enabled": True, "mention_all": True},
        )
        assert put.status_code == 200
        put_data = put.json()
        assert put_data["webhook_url"] == "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc"  # 已 strip
        assert put_data["enabled"] is True
        assert put_data["mention_all"] is True

        get = client.get("/api/notify/config", headers=auth_headers)
        assert get.status_code == 200
        get_data = get.json()
        assert get_data["webhook_url"] == "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc"
        assert get_data["enabled"] is True
        assert get_data["mention_all"] is True

    def test_test_send_no_webhook(self, client, auth_headers):
        resp = client.post("/api/notify/test", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "webhook" in data["message"]

    def test_test_send_success_logs(self, client, auth_headers, monkeypatch):
        client.put(
            "/api/notify/config",
            headers=auth_headers,
            json={"webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc", "enabled": False},
        )
        make_post(monkeypatch, result=FakeResponse({"errcode": 0, "errmsg": "ok"}))
        resp = client.post("/api/notify/test", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # 发送记录已写入
        resp_logs = client.get("/api/notify/logs", headers=auth_headers)
        items = resp_logs.json()["items"]
        assert len(items) == 1
        assert items[0]["status"] == "success"
        assert items[0]["title"] == "测试消息"

    def test_test_send_failure_logs(self, client, auth_headers, monkeypatch):
        client.put(
            "/api/notify/config",
            headers=auth_headers,
            json={"webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=bad", "enabled": False},
        )
        make_post(monkeypatch, result=FakeResponse({"errcode": 93000, "errmsg": "invalid key"}))
        resp = client.post("/api/notify/test", headers=auth_headers)
        assert resp.json()["success"] is False
        resp_logs = client.get("/api/notify/logs", headers=auth_headers)
        items = resp_logs.json()["items"]
        assert items[0]["status"] == "failed"
        assert items[0]["error_msg"] and "93000" in items[0]["error_msg"]

    def test_manual_send_markdown(self, client, auth_headers, monkeypatch):
        client.put(
            "/api/notify/config",
            headers=auth_headers,
            json={"webhook_url": "https://x/webhook?key=abc", "enabled": False},
        )
        calls = make_post(monkeypatch, result=FakeResponse({"errcode": 0, "errmsg": "ok"}))
        resp = client.post(
            "/api/notify/send",
            headers=auth_headers,
            json={"title": "联调通知", "content": "# 标题\n正文", "msgtype": "markdown"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert calls[0]["json"]["msgtype"] == "markdown"
        resp_logs = client.get("/api/notify/logs", headers=auth_headers)
        assert resp_logs.json()["items"][0]["title"] == "联调通知"

    def test_manual_send_without_webhook(self, client, auth_headers, monkeypatch):
        make_post(monkeypatch, result=FakeResponse({"errcode": 0}))
        resp = client.post("/api/notify/send", headers=auth_headers, json={"content": "hi"})
        assert resp.json()["success"] is False
        assert "webhook" in resp.json()["message"]

    def test_logs_pagination(self, client, auth_headers, db):
        # 直接造 3 条日志
        for i in range(3):
            db.add(NotificationLog(channel="wecom_webhook", title=f"log-{i}", content="c",
                                    status="success", error_msg=None))
        db.commit()
        resp = client.get("/api/notify/logs?page=1&page_size=2", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 2
        assert data["page"] == 1
        assert data["page_size"] == 2
        # 最近的在前面
        assert data["items"][0]["title"] == "log-2"

    def test_logs_page_size_validation(self, client, auth_headers):
        resp = client.get("/api/notify/logs?page_size=101", headers=auth_headers)
        assert resp.status_code == 422

    def test_config_save_channel_fallback(self, client, auth_headers):
        resp = client.put(
            "/api/notify/config",
            headers=auth_headers,
            json={"webhook_url": "", "channel": "", "enabled": True},
        )
        assert resp.status_code == 200
        assert resp.json()["channel"] == "wecom_webhook"
