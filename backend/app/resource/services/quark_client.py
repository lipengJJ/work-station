"""
夸克网盘官方接口客户端：负责分享链接解析、分享信息获取、提取码校验与转存。

接口均为 pan.quark.cn 网页版接口，需要登录态 Cookie（浏览器 F12 复制）。
核心链路（quark 网页版实际行为，已被开源社区验证）：
  1. GET /interface/share/shareinfo  取分享文件列表 + share_token
  2. 若需要提取码：POST /interface/share/share_password 校验后拿 share_token
  3. 可选：POST /interface/clouddrive/create 创建目标目录
  4. POST /interface/share/transfer  把文件 fid_list 转存到目标目录
"""
from __future__ import annotations

import re
from typing import Optional

import requests
from loguru import logger

from app.resource.services.base import ResourceSourceError

PAN_BASE = "https://pan.quark.cn"
_SHARE_ID_RE = re.compile(r"[A-Za-z0-9]{12,40}")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class QuarkClient:
    def __init__(self, cookies_str: str) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": UA,
                "Cookie": cookies_str,
                "Referer": f"{PAN_BASE}/",
                "Accept": "application/json, text/plain, */*",
                "Origin": PAN_BASE,
            }
        )

    # ------------------------------------------------------------ 基础请求 ----
    def _get_json(self, path: str, params: dict | None = None) -> dict:
        try:
            resp = self.session.get(f"{PAN_BASE}{path}", params=params, timeout=15)
        except requests.RequestException as exc:
            raise ResourceSourceError(f"夸克接口请求失败：{exc}") from exc
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ResourceSourceError(f"夸克接口响应异常（HTTP {resp.status_code}）") from exc
        if not isinstance(payload, dict):
            raise ResourceSourceError(f"夸克接口响应异常（HTTP {resp.status_code}）")
        if payload.get("status") not in (200, None):
            raise ResourceSourceError(payload.get("message") or f"夸克接口错误：{payload.get('status')}")
        return payload.get("data") or {}

    def _post_json(self, path: str, body: dict) -> dict:
        try:
            resp = self.session.post(f"{PAN_BASE}{path}", json=body, timeout=15)
        except requests.RequestException as exc:
            raise ResourceSourceError(f"夸克接口请求失败：{exc}") from exc
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ResourceSourceError(f"夸克接口响应异常（HTTP {resp.status_code}）") from exc
        if not isinstance(payload, dict):
            raise ResourceSourceError(f"夸克接口响应异常（HTTP {resp.status_code}）")
        if payload.get("status") not in (200, None):
            raise ResourceSourceError(payload.get("message") or f"夸克接口错误：{payload.get('status')}")
        return payload.get("data") or {}

    # ------------------------------------------------------------ 账号信息 ----
    def get_account_info(self) -> dict:
        """校验 cookie 有效性并返回账号信息，失败抛 ResourceSourceError。"""
        try:
            resp = self.session.get(f"{PAN_BASE}/account/info", timeout=15)
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise ResourceSourceError(f"夸克账号校验失败：{exc}") from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        if not data or not data.get("nickname"):
            msg = payload.get("message") if isinstance(payload, dict) else ""
            raise ResourceSourceError(msg or "Cookie 无效或已过期，请重新获取夸克 Cookie")
        return data

    # ------------------------------------------------------------ 分享信息 ----
    def get_share_info(self, share_id: str, pwd: str = "") -> dict:
        """
        获取分享信息。返回 {"share_token": ..., "pwd_id": ..., "files": [...]}。
        分享需要提取码时（无 pwd 或 pwd 错误）抛 ResourceSourceError，message 含提示。
        """
        data = self._get_json(
            "/interface/share/shareinfo",
            {
                "shareid": share_id,
                "pwd": pwd,
                "stoken": "",
                "pdir_fid": "0",
                "force": "0",
                "_page": "1",
                "_size": "50",
            },
        )
        files = data.get("files")
        if files is None:
            raise ResourceSourceError("需要提取码，请填写分享提取码后再试")
        if not files:
            raise ResourceSourceError("该分享没有可转存的文件")
        return data

    def verify_password(self, share_id: str, pwd: str) -> str:
        """校验提取码，返回 share_token；失败抛 ResourceSourceError。"""
        if not pwd:
            raise ResourceSourceError("该分享需要提取码")
        data = self._post_json(
            "/interface/share/share_password",
            {"share_id": share_id, "share_pwd": pwd.strip()},
        )
        token = data.get("share_token")
        if not token:
            raise ResourceSourceError("提取码错误或已失效")
        return token

    # ------------------------------------------------------------ 目录与转存 ----
    def create_dir(self, name: str, parent_fid: str = "0") -> str:
        """在网盘创建目录，返回目录 fid。"""
        data = self._post_json("/interface/clouddrive/create", {"pdir_fid": parent_fid, "pdir_name": name})
        fid = data.get("fid")
        if not fid:
            raise ResourceSourceError("创建目录失败")
        return fid

    def transfer(self, share_id: str, share_token: str, fid_list: list[str], to_pdir_fid: str = "0") -> dict:
        """把分享文件转存到目标目录（fid 为分享内文件 fid 列表）。"""
        data = self._post_json(
            "/interface/share/transfer",
            {
                "fid_list": fid_list,
                "from": "share",
                "share_id": share_id,
                "share_token": share_token,
                "to_pdir_fid": to_pdir_fid,
                "pwd_id": share_id,
            },
        )
        return data

    # ------------------------------------------------------------ 完整转存 ----
    def save_share(self, share_id: str, pwd: str, target_dir: str) -> tuple[int, str]:
        """
        完整转存链路：shareinfo → (需要提取码则校验) → 可选建目录 → transfer。
        返回 (转存文件数, 成功描述)，失败抛 ResourceSourceError。
        """
        if not _SHARE_ID_RE.fullmatch(share_id or ""):
            raise ResourceSourceError("分享链接格式不正确")

        try:
            info = self.get_share_info(share_id, pwd or "")
        except ResourceSourceError as exc:
            if "提取码" in str(exc) and pwd:
                # 带码 shareinfo 仍失败，改用 share_password 接口校验拿 token 再取文件列表
                token = self.verify_password(share_id, pwd)
                info = self.get_share_info(share_id, pwd)
                info.setdefault("share_token", token)
            else:
                raise

        share_token = info.get("share_token") or ""
        if not share_token:
            raise ResourceSourceError("未能获取分享凭证，链接可能已失效")
        files = info.get("files") or []
        fid_list = [f["fid"] for f in files if f.get("fid")]
        if not fid_list:
            raise ResourceSourceError("该分享没有可转存的文件")

        to_fid = "0"
        if target_dir and target_dir.strip():
            to_fid = self.create_dir(target_dir.strip())
            logger.info(f"quark.save 已创建目录 target_dir={target_dir} fid={to_fid}")

        self.transfer(share_id, share_token, fid_list, to_fid)
        return len(fid_list), "转存成功" + (f"，已存入「{target_dir.strip()}」" if target_dir.strip() else "（网盘根目录）")
