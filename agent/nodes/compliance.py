"""Compliance Guard: policy-pack rules (config, not code), platform limits and injection-echo checks."""
from __future__ import annotations

import re

from agent.guards import policy_rules
from agent.handoffs import ComplianceVerdict
from agent.nodes.base import Ctx, node


def _sentences(t: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", t)


def check_policy(text: str, answers: list[str], evidence: dict[str, str], injection_spans: list[str],
                 platform: dict, length_check: bool = True) -> tuple[ComplianceVerdict, list[str]]:
    rules = policy_rules()
    allowed, vio = True, []
    pool = " ".join(evidence.values()).lower()

    def apply(t: str) -> str:
        nonlocal allowed
        for rule in rules["rules"]:
            for pat in rule["patterns"]:
                for m in list(re.finditer(pat, t)):
                    act = rule["action"]
                    if act == "verify_claims" and m.group(0).lower() in pool:
                        continue
                    vio.append({"rule": rule["id"], "action": act, "match": m.group(0)})
                    if act == "redact":
                        t = t.replace(m.group(0), "")
                    elif act == "rewrite":
                        t = " ".join(s for s in _sentences(t) if m.group(0) not in s)
                    else:  # block, verify_claims (unsupported)
                        allowed = False
        return re.sub(r"[ \t]{2,}", " ", t).strip()

    text = apply(text)
    answers = [apply(a) for a in answers]
    # Anything the injected text asked us to say must not appear in what we send.
    for span in injection_spans:
        for phrase in re.findall(r"'([^']{4,})'", span):
            if phrase.lower() in text.lower() or any(phrase.lower() in a.lower() for a in answers):
                allowed = False
                vio.append({"rule": "injection_echo", "action": "block", "match": phrase})
    props = (platform.get("raw") or {}).get("proposals", {})
    lo, hi = props.get("min_cover_letter_chars", 150), props.get("max_cover_letter_chars", 5000)
    if length_check and not lo <= len(text) <= hi:
        allowed = False
        vio.append({"rule": "platform_length", "action": "block", "match": f"{len(text)} chars (allowed {lo}-{hi})"})
    version = f"rules v{rules.get('version')} / platform v{platform.get('version', '?')}"
    return ComplianceVerdict(allowed=allowed, policy_version=version, violations=vio,
                             redacted_text=text), answers


@node("compliance")
async def compliance(state: dict, ctx: Ctx, usages: list) -> dict:
    d = state["draft"]
    verdict, answers = check_policy(d.client_text(), d.screening_answers, state.get("evidence", {}),
                                    state.get("injection_spans", []), state.get("policy", {}))
    out = {"compliance": verdict, "draft": d.model_copy(update={"screening_answers": answers})}
    if not verdict.allowed and not state.get("approval"):  # a human edit that fails goes back to the human
        if state.get("compliance_retries", 0) >= 1:
            out["status"] = "blocked"
        else:
            out["compliance_retries"] = 1
    return out
