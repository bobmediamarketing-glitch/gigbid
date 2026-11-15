"""Passwords (scrypt), sessions (JWT in an httpOnly cookie or a bearer header) and token encryption."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets as pysecrets
import time

import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request, status

from apps.api import db

COOKIE = "gigbid_session"
SESSION_HOURS = 24 * 7


def _jwt_secret() -> str:
    s = os.getenv("JWT_SECRET")
    if not s:
        if os.getenv("GIGBID_ENV", "dev") == "production":
            raise RuntimeError("JWT_SECRET must be set in production")
        s = "dev-only-insecure-jwt-secret-change-me"
    return s


def hash_password(pw: str) -> str:
    salt = pysecrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, salt_b64, dk_b64 = stored.split("$")
        dk = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt_b64), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except Exception:
        return False


def make_token(uid: int) -> str:
    now = int(time.time())
    return jwt.encode({"sub": str(uid), "iat": now, "exp": now + SESSION_HOURS * 3600}, _jwt_secret(), "HS256")


def _decode(token: str) -> int:
    try:
        return int(jwt.decode(token, _jwt_secret(), algorithms=["HS256"])["sub"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired or invalid")


def current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE)
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
    uid = _decode(token)
    with db.engine().begin() as c:
        row = c.execute(db.select(db.users.c.id, db.users.c.email, db.users.c.name)
                        .where(db.users.c.id == uid)).first()
    if not row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user no longer exists")
    return {"id": row.id, "email": row.email, "name": row.name}


User = Depends(current_user)


# ---------------------------------------------------------------- encrypted OAuth tokens
def _fernet() -> Fernet:
    key = os.getenv("TOKEN_ENCRYPTION_KEY")
    if not key:
        if os.getenv("GIGBID_ENV", "dev") == "production":
            raise RuntimeError("TOKEN_ENCRYPTION_KEY must be set in production")
        key = base64.urlsafe_b64encode(hashlib.sha256(b"dev-only-token-key").digest()).decode()
    return Fernet(key)


def store_secret(uid: int, kind: str, value: str) -> None:
    ct = _fernet().encrypt(value.encode()).decode()
    with db.engine().begin() as c:
        c.execute(db.delete(db.secrets).where(db.secrets.c.user_id == uid, db.secrets.c.kind == kind))
        c.execute(db.insert(db.secrets).values(user_id=uid, kind=kind, ciphertext=ct, updated_at=db.now()))


def load_secret(uid: int, kind: str) -> str | None:
    with db.engine().begin() as c:
        row = c.execute(db.select(db.secrets.c.ciphertext)
                        .where(db.secrets.c.user_id == uid, db.secrets.c.kind == kind)).first()
    if not row:
        return None
    try:
        return _fernet().decrypt(row[0].encode()).decode()
    except InvalidToken:
        return None
