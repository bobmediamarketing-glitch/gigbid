"""Portfolio MCP server through an in-memory MCP client."""
import json
import shutil
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from mcp_servers.portfolio import server as pf

pytestmark = pytest.mark.anyio
PERSONA = Path(__file__).resolve().parents[3] / "data" / "personas" / "data_analyst"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def persona(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DIR", str(PERSONA))


def data(r):
    assert not r.isError, r.content
    return r.structuredContent


async def test_search_evidence_finds_exact_tool_names():
    async with connect(pf.mcp) as c:
        r = data(await c.call_tool("search_evidence", {"requirement": "Experience with dbt and snowflake", "k": 5}))
    assert r["items"], "no evidence returned"
    top = r["items"][0]
    assert {"dbt", "snowflake"} & set(top["skills"])
    assert top["uri"].startswith("portfolio://")


async def test_filters_outcome_and_type():
    async with connect(pf.mcp) as c:
        r = data(await c.call_tool("search_evidence", {"requirement": "dashboard", "k": 10,
                                                       "filters": {"types": ["past_proposal"], "outcomes": ["won"]}}))
    assert r["items"] and all(i["type"] == "past_proposal" and i["outcome"] == "won" for i in r["items"])


async def test_case_study_resources_prompts():
    async with connect(pf.mcp) as c:
        cs = data(await c.call_tool("get_case_study", {"id": "data_analyst-cs-01"}))
        assert cs["body"].startswith("# ")
        res = await c.read_resource("portfolio://case/data_analyst-cs-01")
        assert res.contents[0].text == cs["body"]
        prop = json.loads((await c.read_resource("portfolio://proposal/data_analyst-prop-001")).contents[0].text)
        assert prop["outcome"] in {"won", "replied", "ignored"}
        templates = {t.uriTemplate for t in (await c.list_resource_templates()).resourceTemplates}
        assert {"portfolio://case/{id}", "portfolio://proposal/{id}"} <= templates
        prompts = {p.name for p in (await c.list_prompts()).prompts}
        assert "answer_screening_question" in prompts
        missing = await c.call_tool("get_case_study", {"id": "nope"})
        assert missing.isError
        skills = data(await c.call_tool("list_skills", {}))["skills"]
        assert skills[0]["count"] >= skills[-1]["count"]


async def test_incremental_reindex(tmp_path, monkeypatch):
    work = tmp_path / "p"
    shutil.copytree(PERSONA, work)
    monkeypatch.setenv("PORTFOLIO_DIR", str(work))
    async with connect(pf.mcp) as c:
        before = data(await c.call_tool("search_evidence", {"requirement": "quantum annealing scheduler"}))["items"]
        (work / "case_studies" / "new-cs-99.md").write_text(
            "# Quantum annealing scheduler for a logistics client\n\n**Date:** 2026-10-01\n\nBuilt a quantum annealing "
            "scheduler.", encoding="utf-8")
        after = data(await c.call_tool("search_evidence", {"requirement": "quantum annealing scheduler"}))["items"]
    assert not any(i["id"] == "new-cs-99" for i in before)
    assert after[0]["id"] == "new-cs-99"
