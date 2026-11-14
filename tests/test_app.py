import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["LLM_API_KEY"] = "test-key"
os.environ["DEMO_PASSWORD"] = "pw-test"
os.environ["SEED_DEMO"] = "1"

import pytest
from fastapi.testclient import TestClient

from app import llm, review
from app.main import app
from app.seed import SAMPLE_DRAFT

H = {"X-BrandProof": "1"}


def fake_llm(system, user):
    return {"findings": [
        # grounded: excerpt in draft, quote copied from the Packaging fact
        {"excerpt": "Our packaging is fully recyclable", "category": "claim",
         "issue": "Packaging is only partly recycled.", "source_id": 10,
         "quote": "made from 70% recycled plastic", "replacement": "Our packaging is made from 70% recycled plastic",
         "confidence": 0.9},
        # invented quote -> must be dropped
        {"excerpt": "boost your energy", "category": "claim", "issue": "x", "source_id": 10,
         "quote": "this text is not in any source", "replacement": "y", "confidence": 0.9},
        # excerpt not in draft -> must be dropped
        {"excerpt": "not in the draft at all", "category": "tone", "issue": "x", "source_id": 1,
         "quote": "warm, plain-spoken and optimistic", "replacement": "y", "confidence": 0.9},
    ]}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(llm, "chat_json", fake_llm)
    review._cache.clear()
    with TestClient(app) as c:
        yield c


def login(c, user):
    r = c.post("/api/login", json={"username": user, "password": "pw-test"}, headers=H)
    assert r.status_code == 200, r.text


def test_rule_checks_find_banned_and_terms():
    src = [
        {"id": 1, "kind": "banned", "avoid": "#1", "prefer": None, "body": "b", "case_sensitive": 0},
        {"id": 2, "kind": "term", "avoid": "snack bar", "prefer": "oat bar", "body": "t", "case_sensitive": 0},
        {"id": 3, "kind": "term", "avoid": "VERDANT", "prefer": "Verdant", "body": "c", "case_sensitive": 1},
    ]
    out = review.rule_findings("VERDANT is the #1 Snack Bar. Verdant rocks.", src)
    ex = {f["excerpt"] for f in out}
    assert ex == {"VERDANT", "#1", "Snack Bar"}


def test_csrf_header_required(client):
    r = client.post("/api/login", json={"username": "admin", "password": "pw-test"})
    assert r.status_code == 403


def test_end_to_end_workflow(client):
    login(client, "creator")
    r = client.post("/api/drafts", json={"title": "t", "channel": "social", "content": SAMPLE_DRAFT}, headers=H)
    assert r.status_code == 200, r.text
    d = r.json()
    did = d["draft"]["id"]
    ai = [f for f in d["findings"] if f["origin"] == "ai"]
    assert len(ai) == 1 and "70% recycled" in ai[0]["source_quote"]
    assert "discarded" in (d["note"] or "")
    assert any(f["origin"] == "rule" and f["excerpt"] == "#1" for f in d["findings"])

    # accept the AI fix: content changes, version recorded
    r = client.post(f"/api/findings/{ai[0]['id']}/resolve", json={"action": "accept"}, headers=H)
    assert "70% recycled plastic" in r.json()["draft"]["content"]
    # dismiss one rule finding
    fid = next(f["id"] for f in r.json()["findings"] if f["status"] == "open")
    r = client.post(f"/api/findings/{fid}/resolve", json={"action": "dismiss", "reason": "ok"}, headers=H)
    assert r.status_code == 200

    # creator cannot approve
    assert client.post(f"/api/drafts/{did}/decision", json={"decision": "approve"}, headers=H).status_code == 403
    assert client.post(f"/api/drafts/{did}/submit", headers=H).status_code == 200

    client.post("/api/logout", headers=H)
    login(client, "reviewer")
    r = client.post(f"/api/drafts/{did}/decision", json={"decision": "approve"}, headers=H)
    assert r.status_code == 409  # open findings need explicit acknowledgement
    r = client.post(f"/api/drafts/{did}/decision", json={"decision": "approve", "acknowledge_open": True}, headers=H)
    assert r.json()["draft"]["status"] == "approved"
    # approved drafts are locked
    assert client.post(f"/api/drafts/{did}/review", headers=H).status_code == 409


def test_creator_cannot_see_others_or_edit_library(client):
    login(client, "creator")
    assert client.post("/api/sources", json={"kind": "fact", "title": "x", "body": "y"}, headers=H).status_code == 403
    client.post("/api/logout", headers=H)
    assert client.get("/api/drafts").status_code == 401


def test_bad_login_rejected(client):
    r = client.post("/api/login", json={"username": "admin", "password": "wrong"}, headers=H)
    assert r.status_code == 401
