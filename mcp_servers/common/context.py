"""Per-request context shared by the MCP servers: who is calling and which trace this belongs to.

Set by the HTTP auth middleware from the bearer token and the `X-Trace-Id` header,
so one trace id flows from the UI request through the graph into every audit row (E3).
"""
from __future__ import annotations

import contextvars
import json
import os
from dataclasses import dataclass, field

from starlette.types import ASGIApp, Receive, Scope, Send


@dataclass(frozen=True)
class Caller:
    user_id: str
    tenant: str
    credentials: dict = field(default_factory=dict)  # marketplace credentials resolved server-side


current_caller: contextvars.ContextVar[Caller | None] = contextvars.ContextVar("caller", default=None)
current_trace: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace", default=None)


def default_caller() -> Caller:
    """Used for stdio and in-memory transports, where the host process is the only user."""
    return Caller(user_id=os.getenv("GIGBID_DEFAULT_USER", "local"), tenant=os.getenv("GIGBID_DEFAULT_TENANT", "local"),
                  credentials={"gigsim_token": os.getenv("GIGSIM_TOKEN", "gigsim-ai_ml-token")})


def caller() -> Caller:
    return current_caller.get() or default_caller()


def load_token_table(env_var: str) -> dict[str, Caller]:
    """`{"<bearer>": {"user_id": .., "tenant": .., "credentials": {..}}}` from an env var (JSON)."""
    raw = os.getenv(env_var)
    if not raw:
        return {}
    return {tok: Caller(**v) for tok, v in json.loads(raw).items()}


# ---------------------------------------------------------------- signed caller tokens (service-to-service)
CALLER_TTL_S = 900


def sign_caller(who: Caller, secret: str | None = None, ttl: int = CALLER_TTL_S) -> str:
    """Short-lived JWT the GigBid API/worker sends to an MCP server over HTTP, naming the end user and the
    marketplace credentials to act with. Signed with MCP_CALLER_SECRET; never stored."""
    import time

    import jwt
    secret = secret or os.environ["MCP_CALLER_SECRET"]
    now = int(time.time())
    return jwt.encode({"sub": who.user_id, "tenant": who.tenant, "creds": who.credentials, "iat": now,
                       "exp": now + ttl, "aud": "gigbid-mcp"}, secret, "HS256")


def verify_caller(token: str, secret: str | None = None) -> Caller | None:
    import jwt
    secret = secret or os.getenv("MCP_CALLER_SECRET")
    if not secret or token.count(".") != 2:
        return None
    try:
        c = jwt.decode(token, secret, algorithms=["HS256"], audience="gigbid-mcp")
    except jwt.PyJWTError:
        return None
    return Caller(user_id=c["sub"], tenant=c["tenant"], credentials=c.get("creds") or {})


class BearerAuthMiddleware:
    """Pure-ASGI bearer auth for the Streamable HTTP endpoint (does not buffer streaming responses)."""

    def __init__(self, app: ASGIApp, tokens: dict[str, Caller]) -> None:
        self.app, self.tokens = app, tokens

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/healthz":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        tok = headers.get("authorization", "").removeprefix("Bearer ").strip()
        who = self.tokens.get(tok) or verify_caller(tok)  # static tokens (desktop hosts) or signed callers
        if not who:
            body = b'{"error":"invalid or missing bearer token"}'
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
            await send({"type": "http.response.body", "body": body})
            return
        t1, t2 = current_caller.set(who), current_trace.set(headers.get("x-trace-id"))
        try:
            await self.app(scope, receive, send)
        finally:
            current_caller.reset(t1)
            current_trace.reset(t2)


def transport_security():
    """DNS-rebinding protection stays on; MCP_ALLOWED_HOSTS adds the service names a deployment uses
    (e.g. "mcp-marketplace:*,mcp-portfolio:*"). Without it only localhost is accepted."""
    from mcp.server.transport_security import TransportSecuritySettings
    extra = [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                     allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", *extra],
                                     allowed_origins=["http://127.0.0.1:*", "http://localhost:*"])

