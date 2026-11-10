"""Smoke test for the GigSim stand-in: auth, idempotency, Connects, client reaction, rate limit, outage."""
import os

os.environ["GIGSIM_ERROR_RATE"] = "0"
os.environ["GIGSIM_STATE_FILE"] = os.path.join(os.path.dirname(__file__), ".gigsim_test_state.json")

from fastapi.testclient import TestClient  # noqa: E402

from gigsim.app import SIM, app  # noqa: E402

H = {"Authorization": "Bearer gigsim-ai_ml-token"}
A = {"X-Admin-Token": "gigsim-admin"}


def setup_function():
    SIM.reset()
    SIM.outage = False


def test_auth_required():
    c = TestClient(app)
    assert c.get("/jobs").status_code == 401


def test_proposal_flow_idempotent_and_charges_once():
    c = TestClient(app)
    job = c.get("/jobs", params={"category": "RAG chatbot"}, headers=H).json()["items"][0]
    before = c.get("/me/connects", headers=H).json()["balance"]
    body = {"job_id": job["id"], "cover_letter": "Your RAG chatbot goal matches my policy Q&A assistant built with rag, "
            "langchain and qdrant, which cut manual effort by 60%. " * 3, "bid_amount": job["budget"]["max"],
            "bid_type": job["budget"]["type"]}
    dry = c.post("/proposals", json=body | {"dry_run": True}, headers=H).json()
    assert dry["dry_run"] and dry["would_create"]["connects_cost_on_submit"] == job["connects_cost"]
    assert c.post("/proposals", json=body, headers=H).status_code == 400  # missing idempotency key
    p1 = c.post("/proposals", json=body, headers=H | {"Idempotency-Key": "k1"}).json()
    p2 = c.post("/proposals", json=body, headers=H | {"Idempotency-Key": "k1"}).json()
    assert p1["id"] == p2["id"] and p2["idempotent_replay"]
    s1 = c.post(f"/proposals/{p1['id']}/submit", json={}, headers=H | {"Idempotency-Key": "s1"})
    s2 = c.post(f"/proposals/{p1['id']}/submit", json={}, headers=H | {"Idempotency-Key": "s1"})
    assert s1.status_code == 200 and s2.json()["idempotent_replay"]
    assert c.get("/me/connects", headers=H).json()["balance"] == before - job["connects_cost"]
    c.post("/admin/advance", json={"minutes": 60 * 80}, headers=A)
    status = c.get(f"/proposals/{p1['id']}", headers=H).json()["status"]
    assert status in {"viewed", "replied", "lost", "submitted"}
    types = {e["type"] for e in c.get("/events", headers=H).json()["items"]}
    assert "proposal_submitted" in types


def test_outage_and_rate_limit():
    c = TestClient(app)
    c.post("/admin/outage", json={"on": True}, headers=A)
    assert c.get("/jobs", headers=H).status_code == 503
    c.post("/admin/outage", json={"on": False}, headers=A)
    codes = [c.get("/jobs", headers={"Authorization": "Bearer gigsim-fullstack-token"}).status_code for _ in range(25)]
    assert 429 in codes


def test_client_scoring_prefers_specific_grounded_proposals():
    from gigsim.app import score_proposal
    job = next(j for j in SIM.jobs.values() if SIM.hidden_jobs[j["id"]]["kind"] == "normal"
               and "pineapple" not in j["description"])
    must = SIM.hidden_jobs[job["id"]]["must_have"]
    good = (f"Your {job['category'].lower()} project is close to work I shipped last year using {', '.join(must)}. "
            "It cut manual effort by 60% and the client extended the contract. ") * 3
    bad = "Dear Hiring Manager, I am a passionate and hardworking professional. I can do this job. " * 4
    b = job["budget"]["max"]
    assert score_proposal(job, good, b)["score"] > score_proposal(job, bad, b)["score"]
    assert score_proposal(job, good + " Email me at me@x.com", b)["violation"]
