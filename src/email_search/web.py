"""HTTP API + 테스트 화면.

TECH-GPT V2 「응답 표출 규격서 v1.1」에 맞는 도구 응답을 돌려준다: 최상위 키마다 {type, data}, type 은 answer·table·card·text.
  GET  /                    테스트 화면(입력 폼 + 규격대로 그린 표·카드·텍스트 + 원본 JSON)
  GET  /search?name=&affiliation=&field=   한 사람 (플랫폼 도구 호출·브라우저 테스트 겸용)
  POST /search              {"name","affiliation","field"}
  POST /search/batch        {"people":[{"name","affiliation","field"}, ...]}  (최대 50명)
  GET  /health
  GET  /docs                OpenAPI 문서(FastAPI 기본)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from .config import Settings
from .finder import EmailFinder
from .models import Person
from .report import to_techgpt

app = FastAPI(title="email_search", version="0.1.0", description="소속·이름·기술분야로 공개 출처에서 이메일을 찾는다. 응답은 TECH-GPT V2 응답 표출 규격(v1.1).")
_finder: EmailFinder | None = None
_HTML = Path(__file__).with_name("test_page.html")


def finder() -> EmailFinder:
    global _finder
    if _finder is None:
        _finder = EmailFinder(Settings())
    return _finder


def _run(name: str, affiliation: str, field: str) -> dict[str, Any]:
    name, affiliation = name.strip(), affiliation.strip()
    if not name or not affiliation:
        raise HTTPException(422, "name 과 affiliation 은 필수입니다")
    res = finder().find(Person(name=name, affiliation=affiliation, field=field.strip()))
    return to_techgpt([res])


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def test_page() -> str:
    return _HTML.read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict[str, Any]:
    f = finder()
    return {"status": "ok", "openalex_key": bool(f.s.openalex_api_key), "openalex_key_exhausted": f.openalex.key_exhausted(), "dart": f.dart is not None}


@app.get("/search", summary="한 사람 검색 (GET)")
def search_get(name: str = Query(..., description="이름(한글·로마자)"), affiliation: str = Query(..., description="소속"), field: str = Query("", description="기술분야")) -> dict[str, Any]:
    return _run(name, affiliation, field)


@app.post("/search", summary="한 사람 검색 (POST)")
def search(payload: dict[str, Any] = Body(..., examples=[{"name": "홍길동", "affiliation": "한국과학기술원", "field": "고대역폭 메모리"}])) -> dict[str, Any]:
    return _run(str(payload.get("name") or ""), str(payload.get("affiliation") or ""), str(payload.get("field") or ""))


@app.post("/search/batch", summary="여러 사람 검색")
def search_batch(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    people = payload.get("people") or []
    if not people or len(people) > 50:
        raise HTTPException(422, "people 은 1~50명")
    results = [finder().find(Person(name=str(p.get("name", "")).strip(), affiliation=str(p.get("affiliation", "")).strip(), field=str(p.get("field", "")).strip())) for p in people if p.get("name") and p.get("affiliation")]
    if not results:
        raise HTTPException(422, "name 과 affiliation 이 있는 항목이 없습니다")
    return to_techgpt(results)
