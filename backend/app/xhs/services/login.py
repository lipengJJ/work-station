"""
获取小红书 token（cookie）：扫码登录 / 手机号登录。

原样复用 client/pc_login_apis.py 里现成的 XHSLoginApi（终端交互版本），只是把它的
终端交互（打印二维码、input() 等待）改造成适合网页轮询的接口。和上次独立 webapp 版本
相比，唯一的区别是登录成功后把 cookie 存进 ApiConfig 表（token_store），而不是文件。
"""
import base64
import io
import time
from typing import Dict

import qrcode
from sqlalchemy.orm import Session

from app.xhs.services.client.pc_login_apis import XHSLoginApi
from app.xhs.services import token_store

_login_api = XHSLoginApi()

_pending_qrcode: Dict[str, dict] = {}
_pending_phone: Dict[str, dict] = {}

_TTL_SECONDS = 10 * 60


def _cleanup(store: dict) -> None:
    now = time.time()
    for key in [k for k, v in store.items() if now - v["ts"] > _TTL_SECONDS]:
        store.pop(key, None)


def _qrcode_to_data_uri(url: str) -> str:
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def start_qrcode_login() -> dict:
    _cleanup(_pending_qrcode)
    cookies = _login_api.generate_init_cookies()
    success, msg, qr_data = _login_api.generate_qrcode(cookies)
    if not success:
        return {"status": "error", "msg": msg}
    qr_id = qr_data["qr_id"]
    _pending_qrcode[qr_id] = {
        "cookies": qr_data["cookies"],
        "code": qr_data["code"],
        "ts": time.time(),
    }
    return {
        "status": "ok",
        "qr_id": qr_id,
        "qr_image": _qrcode_to_data_uri(qr_data["qr_url"]),
        "expires_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + 300)),
    }


def poll_qrcode_login(db: Session, qr_id: str) -> dict:
    entry = _pending_qrcode.get(qr_id)
    if not entry:
        return {"status": "expired", "msg": "二维码已失效，请重新获取"}

    success, msg, cookies = _login_api.check_qrcode_status(qr_id, entry["code"], entry["cookies"])
    entry["cookies"] = cookies

    if success:
        if "web_session" not in cookies:
            # check_qrcode_status 的 success 只代表"手机上已扫码确认"，真正的登录态 session
            # 是它内部另发的第二个请求拿的，那个请求偶尔会慢一拍/失败而不影响这里的 success。
            # 这时候不能把不完整的 cookie 存下来（后面采集任务会报"无登录信息"），继续等
            # 下一轮轮询——status 还是 2，会自然重试那个内部请求，通常一两次就好了。
            return {"status": "scanned", "msg": "已扫描，请在手机上确认"}
        _pending_qrcode.pop(qr_id, None)
        _, user_info, cookies = _login_api.get_user_info(cookies)
        cookies_str = _login_api.cookies_to_str(cookies)
        token_store.set_cookies_str(db, cookies_str)
        return {"status": "success", "nickname": user_info.get("nickname", "未知")}

    if msg == "二维码已过期":
        _pending_qrcode.pop(qr_id, None)
        return {"status": "expired", "msg": msg}

    return {"status": "pending", "msg": msg}


def cancel_qrcode_login(qr_id: str) -> dict:
    """关闭弹窗/切换 tab 时调用：释放该次扫码登录会话，避免堆积。"""
    if qr_id and qr_id in _pending_qrcode:
        _pending_qrcode.pop(qr_id, None)
    return {"success": True}


def send_phone_code(phone: str, zone: str = "86") -> dict:
    _cleanup(_pending_phone)
    cookies = _login_api.generate_init_cookies()
    success, msg, _ = _login_api.send_phone_code(phone, cookies, zone)
    if success:
        _pending_phone[phone] = {"cookies": cookies, "zone": zone, "ts": time.time()}
    return {"success": success, "msg": msg}


def verify_phone_login(db: Session, phone: str, code: str, zone: str = "86") -> dict:
    entry = _pending_phone.get(phone)
    if not entry:
        return {"success": False, "msg": "请先发送验证码"}

    success, msg, result = _login_api.login_by_phone(phone, code, entry["cookies"], entry["zone"])
    if not success:
        return {"success": False, "msg": msg}

    _pending_phone.pop(phone, None)
    _, user_info, cookies = _login_api.get_user_info(result["cookies"])
    cookies_str = _login_api.cookies_to_str(cookies)
    token_store.set_cookies_str(db, cookies_str)
    return {"success": True, "nickname": user_info.get("nickname", "未知")}
