from __future__ import annotations

import re
from urllib.parse import urlencode

import httpx

from . import constants as C


class CasLoginError(RuntimeError):
    pass


_LOGIN_FORM_RE = re.compile(r'name="execution"\s+value="([^"]+)"')


def cas_login(username: str, password: str, cas_base: str = C.DEFAULT_CAS_BASE,
              service: str = C.DEFAULT_CAS_SERVICE, tls_verify: bool = True) -> dict[str, str]:
    """EXPERIMENTAL. Automates CAS sign-in with user-supplied credentials to
    obtain TIS session cookies. Credentials are used in memory only."""
    login_url = cas_base.rstrip("/") + "/cas/login"
    params = {"service": service}
    headers = {"user-agent": C.USER_AGENT}
    with httpx.Client(verify=tls_verify, timeout=15.0, headers=headers) as client:
        r = client.get(login_url, params=params)
        if r.status_code != 200:
            raise CasLoginError(f"CAS 页面访问失败: HTTP {r.status_code}")
        if re.search(r'name="captcha', r.text, re.I):
            raise CasLoginError("CAS 页面需要验证码，请改用浏览器登录后导出 Cookie")
        m = _LOGIN_FORM_RE.search(r.text)
        if not m:
            raise CasLoginError("未在 CAS 页面找到 execution 字段，登录流程可能已变更")
        data = {
            "username": username,
            "password": password,
            "execution": m.group(1),
            "_eventId": "submit",
            "geolocation": "",
        }
        r = client.post(login_url, params=params, data=data)
        if "execution" in r.text and "password" in r.text.lower():
            raise CasLoginError("用户名或密码错误（或需要额外验证）")
        pairs = {c.name: c.value for c in client.cookies.jar
                 if any(d in str(getattr(c, "domain", "")).lower() for d in TIS_MARKERS)
                 or str(getattr(c, "domain", "")).strip(".") == "tis.sustech.edu.cn"}
        if not pairs:
            tis_host = service.split("//")[-1].split("/")[0]
            pairs = {c.name: c.value for c in client.cookies.jar
                     if tis_host in str(getattr(c, "domain", "")).lower()}
        if not pairs:
            raise CasLoginError("未获取到 TIS 会话 Cookie")
        return pairs


TIS_MARKERS = ("tis.sustech.edu.cn",)


def prompt_credentials() -> tuple[str, str]:
    import getpass

    username = input("学号/工号: ").strip()
    password = getpass("CAS 密码（不回显，仅用于本次会话，不写入磁盘）: ")
    return username, password
