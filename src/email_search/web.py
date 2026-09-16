"""HTTP API (서비스용) + 테스트 화면.

응답은 TECH-GPT V2 「응답 표출 규격서 v1.1」 형식(최상위 키마다 {type, data}; answer·table·card·text)이다. 자세한 사용법은 docs/API.md.

  GET  /                          테스트 화면
  GET  /v1/health                 상태(의존 출처·키·예산)
  GET  /v1/search?name=&affiliation=&field=     한 사람 동기 검색(30~90초)
  POST /v1/search                 {"name","affiliation","field"}
  POST /v1/search/batch           {"people":[…]} 최대 50명, 동기(시간 주의)
  POST /v1/jobs                   {"people":[…]} → 비동기 작업 등록 {job_id}
  GET  /v1/jobs/{job_id}          작업 상태·진행률·(완료 시) 규격 응답
  DELETE /v1/jobs/{job_id}        작업 결과 삭제
  (버전 없는 /search, /search/batch, /health 는 v1 별칭)

인증: 환경변수 EMS_API_KEY 가 설정되어 있으면 모든 /v1 요청에 헤더 X-API-Key 가 필요하다(테스트 화면 GET / 는 예외).
CORS: EMS_CORS_ORIGINS (쉼표 구분, 기본 *).
동시성: EMS_WORKERS (기본 2) 개의 작업자 스레드가 검색을 수행한다. 동기 요청도 같은 풀을 거친다.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from .config import Settings
from .finder import EmailFinder
from .models import Person, SearchResult
from .report import to_techgpt

__version__ = "0.2.0"
log = logging.getLogger("email_search.web")

API_KEY = os.environ.get("EMS_API_KEY", "")
CORS_ORIGINS = [o.strip() for o in os.environ.get("EMS_CORS_ORIGINS", "*").split(",") if o.strip()]
WORKERS = int(os.environ.get("EMS_WORKERS", "2"))
JOB_TTL = int(os.environ.get("EMS_JOB_TTL", "3600"))  # 완료된 작업 결과 보관(초)
MAX_BATCH = 50

app = FastAPI(
    title="email_search API",
    version=__version__,
    description="소속·이름·기술분야로 신뢰할 수 있는 공개 출처에서 연구자·발명자의 공개 이메일을 찾는다. 응답은 TECH-GPT V2 응답 표출 규격(v1.1). 문서: docs/API.md",
    openapi_tags=[{"name": "search", "description": "동기 검색(한 사람 30~90초)"}, {"name": "jobs", "description": "비동기 작업(여러 사람·긴 검색)"}, {"name": "system"}],
)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])

_HTML = Path(__file__).with_name("test_page.html")
_finder: EmailFinder | None = None
_pool = ThreadPoolExecutor(max_workers=max(1, WORKERS), thread_name_prefix="ems")
_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def finder() -> EmailFinder:
    global _finder
    if _finder is None:
        _finder = EmailFinder(Settings())
    return _finder


def require_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(401, {"code": "unauthorized", "message": "X-API-Key 헤더가 없거나 틀립니다"})


def _people_from(payload: dict[str, Any]) -> list[Person]:
    people = payload.get("people")
    if people is None and payload.get("name"):
        people = [payload]
    if not isinstance(people, list) or not people:
        raise HTTPException(422, {"code": "invalid_input", "message": "people 배열(또는 name·affiliation)이 필요합니다"})
    if len(people) > MAX_BATCH:
        raise HTTPException(422, {"code": "too_many", "message": f"한 번에 최대 {MAX_BATCH}명"})
    out = []
    for p in people:
        name, aff = str(p.get("name") or "").strip(), str(p.get("affiliation") or "").strip()
        if not name or not aff:
            raise HTTPException(422, {"code": "invalid_input", "message": "각 항목에 name 과 affiliation 이 필요합니다", "item": p})
        out.append(Person(name=name, affiliation=aff, field=str(p.get("field") or "").strip(), name_variants=[str(v) for v in (p.get("name_variants") or []) if v]))
    return out


def _search_sync(people: list[Person]) -> list[SearchResult]:
    futs: list[Future] = [_pool.submit(finder().find, p) for p in people]
    return [f.result() for f in futs]


@app.middleware("http")
async def _timing(request: Request, call_next):
    t = time.time()
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    response.headers["X-Elapsed-Seconds"] = f"{time.time() - t:.1f}"
    return response


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content={"error": detail})


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    missing = [".".join(str(x) for x in e.get("loc", [])[1:]) for e in exc.errors()]
    return JSONResponse(status_code=422, content={"error": {"code": "invalid_input", "message": "필수 입력이 없거나 형식이 틀립니다: " + ", ".join(missing), "details": exc.errors()}})


# ---- 화면 · 상태 ------------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def test_page() -> str:
    return _HTML.read_text(encoding="utf-8")


@app.get("/v1/health", tags=["system"])
@app.get("/health", include_in_schema=False)
def health() -> dict[str, Any]:
    f = finder()
    with _jobs_lock:
        jobs = {"total": len(_jobs), "running": sum(1 for j in _jobs.values() if j["status"] == "running"), "queued": sum(1 for j in _jobs.values() if j["status"] == "queued")}
    return {"status": "ok", "version": __version__, "auth": bool(API_KEY), "workers": WORKERS, "jobs": jobs,
            "sources": {"openalex_key": bool(f.s.openalex_api_key), "openalex_key_exhausted": f.openalex.key_exhausted(), "dart": f.dart is not None, "s2_key": bool(f.s.s2_api_key), "core_key": bool(f.s.core_api_key)}}


# ---- 동기 검색 -------------------------------------------------------------------------------
@app.get("/v1/search", tags=["search"], dependencies=[Depends(require_key)], summary="한 사람 검색 (GET)")
@app.get("/search", include_in_schema=False, dependencies=[Depends(require_key)])
def search_get(name: str = Query(..., description="이름(한글·로마자·특허청 표기)"), affiliation: str = Query(..., description="소속(한글·영문·약어)"), field: str = Query("", description="기술분야(선택)")) -> dict[str, Any]:
    people = _people_from({"name": name, "affiliation": affiliation, "field": field})
    return to_techgpt(_search_sync(people))


@app.post("/v1/search", tags=["search"], dependencies=[Depends(require_key)], summary="한 사람 검색 (POST)")
@app.post("/search", include_in_schema=False, dependencies=[Depends(require_key)])
def search_post(payload: dict[str, Any] = Body(..., examples=[{"name": "홍길동", "affiliation": "한국과학기술원", "field": "고대역폭 메모리"}])) -> dict[str, Any]:
    people = _people_from({**payload, "people": None} if payload.get("name") else payload)
    return to_techgpt(_search_sync(people[:1]))


@app.post("/v1/search/batch", tags=["search"], dependencies=[Depends(require_key)], summary="여러 사람 동기 검색(최대 50명, 오래 걸림)")
@app.post("/search/batch", include_in_schema=False, dependencies=[Depends(require_key)])
def search_batch(payload: dict[str, Any] = Body(..., examples=[{"people": [{"name": "홍길동", "affiliation": "한국과학기술원", "field": "고대역폭 메모리"}]}])) -> dict[str, Any]:
    return to_techgpt(_search_sync(_people_from(payload)))


# ---- 비동기 작업 -----------------------------------------------------------------------------
def _run_job(job_id: str, people: list[Person]) -> None:
    with _jobs_lock:
        job = _jobs[job_id]
        job["status"] = "running"
        job["started_at"] = time.time()
    results: list[SearchResult] = []
    try:
        for i, p in enumerate(people, 1):
            results.append(finder().find(p))
            with _jobs_lock:
                job["progress"] = {"done": i, "total": len(people)}
        with _jobs_lock:
            job.update(status="done", finished_at=time.time(), result=to_techgpt(results))
    except Exception as exc:  # noqa: BLE001
        log.exception("job %s failed", job_id)
        with _jobs_lock:
            job.update(status="error", finished_at=time.time(), error={"code": type(exc).__name__, "message": str(exc)[:300]}, result=to_techgpt(results) if results else None)


def _sweep_jobs() -> None:
    now = time.time()
    with _jobs_lock:
        for jid in [j for j, v in _jobs.items() if v.get("finished_at") and now - v["finished_at"] > JOB_TTL]:
            _jobs.pop(jid, None)


@app.post("/v1/jobs", tags=["jobs"], dependencies=[Depends(require_key)], status_code=202, summary="비동기 작업 등록")
def create_job(payload: dict[str, Any] = Body(..., examples=[{"people": [{"name": "홍길동", "affiliation": "한국과학기술원", "field": "고대역폭 메모리"}]}])) -> dict[str, Any]:
    _sweep_jobs()
    people = _people_from(payload)
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {"job_id": job_id, "status": "queued", "created_at": time.time(), "progress": {"done": 0, "total": len(people)}, "people": [{"name": p.name, "affiliation": p.affiliation, "field": p.field} for p in people]}
    _pool.submit(_run_job, job_id, people)
    return {"job_id": job_id, "status": "queued", "total": len(people), "status_url": f"/v1/jobs/{job_id}", "estimated_seconds": 60 * len(people)}


@app.get("/v1/jobs/{job_id}", tags=["jobs"], dependencies=[Depends(require_key)], summary="작업 상태·결과")
def get_job(job_id: str) -> dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(404, {"code": "not_found", "message": "작업이 없거나 보관 기간이 지났습니다"})
        out = {k: v for k, v in job.items() if k != "people"}
        out["people"] = job["people"]
        if job.get("started_at"):
            out["elapsed_seconds"] = round((job.get("finished_at") or time.time()) - job["started_at"], 1)
        return out


@app.delete("/v1/jobs/{job_id}", tags=["jobs"], dependencies=[Depends(require_key)], summary="작업 결과 삭제")
def delete_job(job_id: str) -> dict[str, Any]:
    with _jobs_lock:
        if _jobs.pop(job_id, None) is None:
            raise HTTPException(404, {"code": "not_found", "message": "작업이 없습니다"})
    return {"deleted": job_id}
