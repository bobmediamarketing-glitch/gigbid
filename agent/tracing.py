"""Tracing (E3) with Langfuse (cloud or self-hosted). One trace id per run flows through everything:

- the trace id is derived from the LangGraph thread id, so the UI, API, worker and graph all agree on it
  without passing it around;
- the API sets it as `current_trace`, which the MCP servers write into every audit-log row;
- LangGraph and every model call report to that trace through the Langfuse callback, so each node
  shows its latency, tokens and cost;
- emails, phone numbers, card numbers and tokens are masked before anything leaves the process.

With no LANGFUSE_* keys configured, tracing is a no-op and nothing is sent anywhere.
"""
from __future__ import annotations

import functools
import logging
import os

from mcp_servers.common.pii import mask as mask_pii

log = logging.getLogger("gigbid.tracing")


def enabled() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def _mask(*, data, **_):
    return mask_pii(data)


@functools.lru_cache(maxsize=1)
def client():
    if not enabled():
        return None
    from langfuse import Langfuse
    return Langfuse(mask=_mask, environment=os.getenv("GIGBID_ENV", "dev"),
                    release=os.getenv("GIGBID_RELEASE"))


def trace_id_for(thread_id: str) -> str:
    """Deterministic 32-hex trace id for a thread (the same in the API, worker and run viewer)."""
    from langfuse import Langfuse
    return Langfuse.create_trace_id(seed=thread_id)


def run_config(thread_id: str, user_id: str, kind: str) -> dict:
    """Extra LangGraph config for one run: callbacks + metadata. Empty when tracing is off."""
    c = client()
    if c is None:
        return {}
    from langfuse.langchain import CallbackHandler
    handler = CallbackHandler(trace_context={"trace_id": trace_id_for(thread_id)})
    return {"callbacks": [handler], "run_name": f"{kind}_graph",
            "metadata": {"langfuse_session_id": thread_id, "langfuse_user_id": user_id, "langfuse_tags": [kind]}}


def trace_url(thread_id: str) -> str | None:
    tpl = os.getenv("TRACE_URL_TEMPLATE")
    if tpl:
        return tpl.format(thread_id=thread_id, trace_id=trace_id_for(thread_id))
    c = client()
    if c is None:
        return None
    try:
        return c.get_trace_url(trace_id=trace_id_for(thread_id))
    except Exception:  # project id not resolvable offline
        return None


def flush() -> None:
    c = client()
    if c is not None:
        try:
            c.flush()
        except Exception as e:  # never let tracing break a run
            log.warning("langfuse flush failed: %s", e)
