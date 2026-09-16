"""HTTP API · 테스트 화면: 규격 형식 응답, 입력 검증, 인증, 비동기 작업."""

import time

import httpx
from fastapi.testclient import TestClient

from email_search import web
from email_search.config import Settings
from email_search.finder import EmailFinder

from .test_finder import handler


def _client(tmp_path):
    web._finder = EmailFinder(Settings(cache_dir=tmp_path / "c", contact_email="t@example.org", pdf_budget=1), client=httpx.Client(transport=httpx.MockTransport(handler)))
    return TestClient(web.app)


def test_api_returns_spec_shaped_response(tmp_path):
    c = _client(tmp_path)
    page = c.get("/")
    assert page.status_code == 200 and "email_search 테스트" in page.text and "renderTable" in page.text
    r = c.get("/v1/search", params={"name": "장진아"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input"  # affiliation 누락 → 표준 오류 형식
    assert c.post("/v1/search", json={"name": " ", "affiliation": "x"}).status_code == 422
    r = c.get("/v1/search", params={"name": "장진아", "affiliation": "포항공과대학교", "field": "바이오프린팅"})
    assert r.status_code == 200 and r.headers["X-Elapsed-Seconds"] and r.headers["X-Request-ID"]
    d = r.json()
    assert {k: v["type"] for k, v in d.items()} == {"answer": "answer", "email_table": "table", "email_cards": "card", "notice": "text"}
    rows = d["email_table"]["data"][0]["rows"]
    assert rows[0]["email"][0]["url"].startswith("mailto:") and rows[0]["status"] == "검증됨"
    assert c.get("/search", params={"name": "장진아", "affiliation": "포항공과대학교"}).status_code == 200  # 버전 없는 별칭
    b = c.post("/v1/search/batch", json={"people": [{"name": "장진아", "affiliation": "포항공과대학교"}]})
    assert b.status_code == 200 and len(b.json()["email_table"]["data"][0]["rows"]) == 1
    assert c.post("/v1/search/batch", json={"people": []}).status_code == 422
    assert c.post("/v1/search/batch", json={"people": [{"name": "a", "affiliation": ""}]}).status_code == 422
    h = c.get("/v1/health").json()
    assert h["status"] == "ok" and "sources" in h and "jobs" in h


def test_async_job_lifecycle(tmp_path):
    c = _client(tmp_path)
    r = c.post("/v1/jobs", json={"people": [{"name": "장진아", "affiliation": "포항공과대학교", "field": "바이오프린팅"}]})
    assert r.status_code == 202
    jid = r.json()["job_id"]
    for _ in range(100):
        j = c.get(f"/v1/jobs/{jid}").json()
        if j["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert j["status"] == "done" and j["progress"] == {"done": 1, "total": 1}
    assert j["result"]["email_table"]["data"][0]["rows"][0]["status"] == "검증됨"
    assert c.delete(f"/v1/jobs/{jid}").json() == {"deleted": jid}
    assert c.get(f"/v1/jobs/{jid}").status_code == 404


def test_api_key_required_when_configured(tmp_path, monkeypatch):
    c = _client(tmp_path)
    monkeypatch.setattr(web, "API_KEY", "secret")
    assert c.get("/v1/search", params={"name": "a", "affiliation": "b"}).status_code == 401
    assert c.get("/v1/search", params={"name": "장진아", "affiliation": "포항공과대학교"}, headers={"X-API-Key": "secret"}).status_code == 200
    assert c.get("/").status_code == 200  # 테스트 화면은 열려 있다(화면에서 호출하는 API 는 키가 필요)
