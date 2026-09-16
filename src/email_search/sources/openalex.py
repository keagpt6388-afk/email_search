"""OpenAlex(무료). 저자 검색·저자의 OA 저작물·저작물 OA 위치·기관 검색.
무료 키의 **일일 예산**이 소진되면(429 'Insufficient budget') 키·mailto 를 빼고 완전 익명으로 재시도하고 그날 자정(UTC)까지 키를 쓰지 않는다."""

from __future__ import annotations

import time
from typing import Any

import httpx

BASE = "https://api.openalex.org"


class OpenAlex:
    def __init__(self, client: httpx.Client, api_key: str = "", mailto: str = "") -> None:
        self.client = client
        self.api_key = api_key
        self.mailto = mailto if "@" in mailto and not mailto.startswith("unknown@") else ""
        self.key_exhausted_until = 0.0
        self.last_error = ""

    def key_exhausted(self) -> bool:
        return time.time() < self.key_exhausted_until

    @staticmethod
    def _budget_error(r: httpx.Response) -> bool:
        if r.status_code != 429:
            return False
        try:
            body = r.json()
        except Exception:  # noqa: BLE001
            return False
        return "dailyRemainingUsd" in body or "Insufficient budget" in str(body.get("message", ""))

    def get(self, path: str, params: dict[str, Any], retries: int = 2) -> httpx.Response:
        params = dict(params)
        if self.mailto and not self.key_exhausted():
            params.setdefault("mailto", self.mailto)
        if self.api_key and not self.key_exhausted():
            params.setdefault("api_key", self.api_key)
        r = None
        for attempt in range(retries + 1):
            r = self.client.get(f"{BASE}{path}", params=params)
            if self._budget_error(r) and ("api_key" in params or "mailto" in params):
                try:
                    self.key_exhausted_until = time.time() + float(r.json().get("retryAfter") or 3600)
                except Exception:  # noqa: BLE001
                    self.key_exhausted_until = time.time() + 3600
                params.pop("api_key", None)
                params.pop("mailto", None)
                r = self.client.get(f"{BASE}{path}", params=params)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = 1.5 * (attempt + 1)
                if r.status_code == 429:
                    try:
                        wait = float(r.headers.get("Retry-After") or r.json().get("retryAfter") or wait)
                    except Exception:  # noqa: BLE001
                        pass
                if wait > 12:
                    break
                time.sleep(wait)
                continue
            break
        assert r is not None
        if r.status_code != 200:
            self.last_error = f"HTTP {r.status_code}" + (" (일일 예산 소진 — UTC 자정 초기화)" if self._budget_error(r) else "")
        return r

    def search_authors(self, name: str, per_page: int = 5) -> list[dict[str, Any]]:
        r = self.get("/authors", {"search": name, "per-page": per_page, "select": "id,orcid,display_name,display_name_alternatives,last_known_institutions,affiliations,works_count,topics"})
        r.raise_for_status()
        return r.json().get("results", [])

    def search_institutions(self, name: str, per_page: int = 5) -> list[dict[str, Any]]:
        r = self.get("/institutions", {"search": name, "per-page": per_page, "select": "id,ror,display_name,display_name_alternatives,country_code,homepage_url,works_count"})
        r.raise_for_status()
        return r.json().get("results", [])

    def author_oa_works(self, author_id: str, per_page: int = 25) -> list[dict[str, Any]]:
        short = author_id.rsplit("/", 1)[-1]
        r = self.get("/works", {"filter": f"authorships.author.id:{short},is_oa:true", "per-page": per_page, "sort": "publication_year:desc", "select": "id,doi,title,publication_year,best_oa_location,locations,topics"})
        return r.json().get("results", []) if r.status_code == 200 else []

    def work_locations(self, doi: str) -> dict[str, Any]:
        d = doi if doi.startswith("http") else f"https://doi.org/{doi}"
        r = self.get(f"/works/{d}", {"select": "id,doi,locations,best_oa_location,open_access"})
        return r.json() if r.status_code == 200 else {}


def pdf_urls_of(work: dict[str, Any]) -> list[str]:
    """저작물의 OA PDF 주소들(best 먼저). IEEE 랜딩 페이지만 있으면 문서 번호로 stampPDF 주소를 만든다."""
    import re
    urls: list[str] = []
    best = work.get("best_oa_location") or {}
    if best.get("pdf_url"):
        urls.append(best["pdf_url"])
    for loc in work.get("locations") or []:
        if loc.get("pdf_url") and loc["pdf_url"] not in urls:
            urls.append(loc["pdf_url"])
        lp = loc.get("landing_page_url") or ""
        m = re.search(r"ieeexplore\.ieee\.org/(?:document|abstract/document)/(\d+)", lp)
        if m and loc.get("is_oa"):
            u = f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={m.group(1)}"
            if u not in urls:
                urls.append(u)
    return urls
