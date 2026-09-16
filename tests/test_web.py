"""HTTP API · 테스트 화면: 규격 형식 응답과 입력 검증."""

import httpx
from fastapi.testclient import TestClient

from email_search import web
from email_search.config import Settings
from email_search.finder import EmailFinder

from .test_finder import handler


def test_api_returns_spec_shaped_response(tmp_path):
    web._finder = EmailFinder(Settings(cache_dir=tmp_path / "c", contact_email="t@example.org", pdf_budget=1), client=httpx.Client(transport=httpx.MockTransport(handler)))
    c = TestClient(web.app)
    page = c.get("/")
    assert page.status_code == 200 and "email_search 테스트" in page.text and "renderTable" in page.text
    assert c.get("/search", params={"name": "장진아"}).status_code == 422  # affiliation 누락
    assert c.post("/search", json={"name": " ", "affiliation": "x"}).status_code == 422
    r = c.get("/search", params={"name": "장진아", "affiliation": "포항공과대학교", "field": "바이오프린팅"})
    assert r.status_code == 200
    d = r.json()
    assert {k: v["type"] for k, v in d.items()} == {"answer": "answer", "email_table": "table", "email_cards": "card", "notice": "text"}
    rows = d["email_table"]["data"][0]["rows"]
    assert rows[0]["email"][0]["url"].startswith("mailto:") and rows[0]["status"] == "검증됨"
    b = c.post("/search/batch", json={"people": [{"name": "장진아", "affiliation": "포항공과대학교"}, {"name": "", "affiliation": "x"}]})
    assert b.status_code == 200 and len(b.json()["email_table"]["data"][0]["rows"]) == 1
    assert c.post("/search/batch", json={"people": []}).status_code == 422
    assert c.get("/health").json()["status"] == "ok"
