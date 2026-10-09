"""Minimal stateless auth: HMAC-signed session tokens for configured reviewer accounts.

Accounts come from AUTH_USERS ("email:password:Display Name:role;..."); the demo default
is a single reviewer whose credentials are shown on the login page. Tokens are
base64(payload).base64(HMAC-SHA256(payload)) with an expiry, so they verify on any
serverless instance as long as AUTH_SECRET is the same everywhere.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

TOKEN_TTL_S = 12 * 3600
DEMO_USERS = "reviewer@freightaudit.demo:demo-review-2026:Alex Morgan:reviewer"


@dataclass(frozen=True)
class User:
    email: str
    name: str
    role: str


def _secret() -> bytes:
    # Set AUTH_SECRET in production. The fallback keeps local dev and the public demo working.
    return os.getenv("AUTH_SECRET", "freight-audit-demo-secret-change-me").encode()


def _accounts() -> dict[str, tuple[str, User]]:
    out = {}
    for entry in filter(None, os.getenv("AUTH_USERS", DEMO_USERS).split(";")):
        email, password, name, role = (entry.split(":") + ["", "", "", "reviewer"])[:4]
        out[email.strip().lower()] = (password, User(email.strip().lower(), name.strip() or email, role or "reviewer"))
    return out


def demo_credentials() -> dict | None:
    """Shown on the login page only while the built-in demo account is active."""
    if "AUTH_USERS" in os.environ:
        return None
    email, password, *_ = DEMO_USERS.split(":")
    return dict(email=email, password=password)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def login(email: str, password: str) -> tuple[str, User] | None:
    acct = _accounts().get(email.strip().lower())
    if not acct or not hmac.compare_digest(acct[0].encode(), password.encode()):
        return None
    user = acct[1]
    payload = _b64(json.dumps(dict(sub=user.email, name=user.name, role=user.role,
                                   exp=int(time.time()) + TOKEN_TTL_S)).encode())
    sig = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}", user


def verify(token: str | None) -> User | None:
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    expect = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expect):
        return None
    try:
        data = json.loads(_unb64(payload))
    except ValueError:
        return None
    if data.get("exp", 0) < time.time():
        return None
    return User(data["sub"], data["name"], data["role"])
