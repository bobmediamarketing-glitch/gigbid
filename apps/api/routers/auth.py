"""Sign-up, sign-in, sessions and the Upwork OAuth connect flow."""
from __future__ import annotations

import os
import secrets
import urllib.parse

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError

from apps.api import db
from apps.api.schemas import LoginIn, Me, RegisterIn, Settings
from apps.api.auth import COOKIE, SESSION_HOURS, User, hash_password, make_token, store_secret, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
UPWORK_AUTHORIZE = "https://www.upwork.com/ab/account-security/oauth2/authorize"
UPWORK_TOKEN = "https://www.upwork.com/api/v3/oauth2/token"


def _set_cookie(resp: Response, uid: int) -> None:
    resp.set_cookie(COOKIE, make_token(uid), httponly=True, samesite="lax", max_age=SESSION_HOURS * 3600,
                    secure=os.getenv("GIGBID_ENV") == "production", path="/")


def me_of(u: dict) -> Me:
    return Me(id=u["id"], email=u["email"], name=u["name"], settings=Settings(**db.get_settings(u["id"])))


@router.post("/register", response_model=Me, status_code=201)
def register(body: RegisterIn, resp: Response) -> Me:
    if os.getenv("GIGBID_ALLOW_SIGNUP", "1") != "1":
        raise HTTPException(403, "sign-up is closed on this deployment")
    try:
        with db.engine().begin() as c:
            uid = c.execute(db.insert(db.users).values(email=body.email.lower(), name=body.name,
                                                       password_hash=hash_password(body.password),
                                                       created_at=db.now())).inserted_primary_key[0]
    except IntegrityError:
        raise HTTPException(409, "an account with this email already exists")
    _set_cookie(resp, uid)
    return me_of({"id": uid, "email": body.email.lower(), "name": body.name})


@router.post("/login", response_model=Me)
def login(body: LoginIn, resp: Response) -> Me:
    with db.engine().begin() as c:
        row = c.execute(db.select(db.users).where(db.users.c.email == body.email.lower())).first()
    if not row or not verify_password(body.password, row.password_hash):
        raise HTTPException(401, "wrong email or password")
    _set_cookie(resp, row.id)
    return me_of({"id": row.id, "email": row.email, "name": row.name})


@router.post("/logout", status_code=204)
def logout(resp: Response) -> None:
    resp.delete_cookie(COOKIE, path="/")


@router.get("/me", response_model=Me)
def me(u: dict = User) -> Me:
    return me_of(u)


# ---------------------------------------------------------------- Upwork OAuth (live mode)
@router.get("/upwork/start")
def upwork_start(request: Request, u: dict = User) -> RedirectResponse:
    cid = os.getenv("UPWORK_CLIENT_ID")
    if not cid:
        raise HTTPException(501, "Upwork OAuth is not configured on this deployment (UPWORK_CLIENT_ID)")
    state = secrets.token_urlsafe(24)
    db.put_settings(u["id"], {"_oauth_state": state})
    q = urllib.parse.urlencode({"response_type": "code", "client_id": cid, "state": state,
                                "redirect_uri": os.getenv("UPWORK_REDIRECT_URI",
                                                          str(request.url_for("upwork_callback")))})
    return RedirectResponse(f"{UPWORK_AUTHORIZE}?{q}")


@router.get("/upwork/callback", name="upwork_callback")
async def upwork_callback(code: str, state: str, request: Request, u: dict = User) -> RedirectResponse:
    s = db.get_settings(u["id"])
    if not state or state != s.get("_oauth_state"):
        raise HTTPException(400, "OAuth state mismatch")
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(UPWORK_TOKEN, data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": os.getenv("UPWORK_REDIRECT_URI", str(request.url_for("upwork_callback"))),
            "client_id": os.environ["UPWORK_CLIENT_ID"], "client_secret": os.environ["UPWORK_CLIENT_SECRET"]})
    if r.status_code != 200:
        raise HTTPException(502, "Upwork did not issue a token")
    tok = r.json()
    store_secret(u["id"], "upwork_access_token", tok["access_token"])  # encrypted at rest
    if tok.get("refresh_token"):
        store_secret(u["id"], "upwork_refresh_token", tok["refresh_token"])
    db.put_settings(u["id"], {"upwork_connected": True, "_oauth_state": None})
    return RedirectResponse("/settings?upwork=connected")
