"""레지스트리 커넥터: ROR(기관), ORCID(연구자 공개 레코드), Wikidata(기관 표기·공식 웹사이트, 보조), OpenDART(국내 법인 영문 상호·홈페이지, 키 선택)."""

from __future__ import annotations

import io
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import httpx

from ..names import extract_emails

ROR = "https://api.ror.org/v2/organizations"
ORCID = "https://pub.orcid.org/v3.0"
WIKIDATA = "https://www.wikidata.org/w/api.php"
DART = "https://opendart.fss.or.kr/api"


def ror_summarize(item: dict[str, Any]) -> dict[str, Any]:
    names = [n.get("value", "") for n in item.get("names", []) if n.get("value")]
    display = next((n["value"] for n in item.get("names", []) if "ror_display" in (n.get("types") or [])), names[0] if names else "")
    website = next((l.get("value", "") for l in item.get("links", []) if l.get("type") == "website"), "")
    return {"ror": item.get("id", ""), "display_name": display, "names": names, "website": website, "domains": [d.lower() for d in item.get("domains", [])]}


class Ror:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def search(self, query: str) -> list[dict[str, Any]]:
        r = self.client.get(ROR, params={"query": query})
        r.raise_for_status()
        return [ror_summarize(it) for it in r.json().get("items", [])]

    def match_affiliation(self, text: str) -> dict[str, Any] | None:
        """ROR 소속 문자열 매칭. ROR 이 확신한(chosen) 항목만."""
        r = self.client.get(ROR, params={"affiliation": text})
        r.raise_for_status()
        for item in r.json().get("items", []):
            if item.get("chosen") and item.get("organization"):
                return ror_summarize(item["organization"])
        return None

    def get(self, ror_id: str) -> dict[str, Any] | None:
        short = ror_id.rstrip("/").rsplit("/", 1)[-1]
        r = self.client.get(f"{ROR}/{short}")
        return ror_summarize(r.json()) if r.status_code == 200 else None


class Orcid:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.h = {"Accept": "application/json"}

    def search(self, given: str, family: str, rows: int = 10) -> list[dict[str, Any]]:
        r = self.client.get(f"{ORCID}/expanded-search/", params={"q": f'given-names:"{given}" AND family-name:"{family}"', "rows": rows}, headers=self.h)
        if r.status_code != 200:
            return []
        return [{"orcid": x.get("orcid-id"), "given": x.get("given-names") or "", "family": x.get("family-names") or "", "institutions": x.get("institution-name") or []} for x in (r.json().get("expanded-result") or [])]

    def person(self, orcid: str) -> dict[str, Any] | None:
        """공개 이메일, 연구자 URL, 자기소개 속 이메일, 고용(소속·ROR), 저작물 DOI. 공개 범위가 '모두' 인 항목만 온다."""
        oid = orcid.rstrip("/").rsplit("/", 1)[-1]
        r = self.client.get(f"{ORCID}/{oid}/person", headers=self.h)
        if r.status_code != 200:
            return None
        d = r.json()
        emails = [{"email": e.get("email"), "verified": bool(e.get("verified")), "from": "record"} for e in (d.get("emails") or {}).get("email", []) if e.get("email")]
        for e in extract_emails((d.get("biography") or {}).get("content") or ""):
            if e not in {x["email"] for x in emails}:
                emails.append({"email": e, "verified": False, "from": "biography"})
        urls = [{"name": u.get("url-name") or "", "url": (u.get("url") or {}).get("value", "")} for u in (d.get("researcher-urls") or {}).get("researcher-url", [])]
        out: dict[str, Any] = {"orcid": f"https://orcid.org/{oid}", "emails": emails, "urls": [u for u in urls if u["url"]], "employments": [], "dois": []}
        r2 = self.client.get(f"{ORCID}/{oid}/employments", headers=self.h)
        for g in (r2.json().get("affiliation-group") or []) if r2.status_code == 200 else []:
            s = (g.get("summaries") or [{}])[0].get("employment-summary") or {}
            org = s.get("organization") or {}
            dis = org.get("disambiguated-organization") or {}
            out["employments"].append({"name": org.get("name") or "", "id": dis.get("disambiguated-organization-identifier") or "", "id_source": dis.get("disambiguation-source") or "", "current": s.get("end-date") is None})
        r3 = self.client.get(f"{ORCID}/{oid}/works", headers=self.h)
        for g in (r3.json().get("group") or []) if r3.status_code == 200 else []:
            for x in (g.get("external-ids") or {}).get("external-id", []):
                if (x.get("external-id-type") or "").lower() == "doi" and x.get("external-id-value"):
                    v = x["external-id-value"].lower().replace("https://doi.org/", "")
                    if v not in out["dois"]:
                        out["dois"].append(v)
        out["dois"] = out["dois"][:15]
        return out


class Wikidata:
    ORG_CUES = re.compile(r"compan|corporat|enterprise|manufactur|university|institute|research|laborator|organi[sz]ation|agency|hospital|foundation|school|college|academy|conglomerate|business|firm", re.I)

    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def search(self, term: str, language: str, limit: int = 5) -> list[dict[str, Any]]:
        r = self.client.get(WIKIDATA, params={"action": "wbsearchentities", "search": term, "language": language, "uselang": "en", "type": "item", "limit": limit, "format": "json"})
        r.raise_for_status()
        return r.json().get("search", [])

    def official_websites(self, qid: str) -> list[str]:
        r = self.client.get(WIKIDATA, params={"action": "wbgetentities", "ids": qid, "props": "claims", "format": "json"})
        r.raise_for_status()
        claims = ((r.json().get("entities") or {}).get(qid) or {}).get("claims") or {}
        out = []
        for c in claims.get("P856") or []:
            v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
            if isinstance(v, str) and v.startswith("http") and v not in out:
                out.append(v)
        return out


class Dart:
    """OpenDART(무료 키). 기업 고유번호 목록(12만 건, 스트리밍 파싱·30일 파일 캐시) → 정규화 완전 일치 → 기업개황(영문 상호·홈페이지)."""

    def __init__(self, client: httpx.Client, api_key: str, cache_dir: Path) -> None:
        self.client = client
        self.api_key = api_key
        self.cache_dir = cache_dir
        self._index: dict[str, list[dict[str, str]]] | None = None

    @staticmethod
    def _norm(name: str) -> str:
        from ..orgs import _norm_raw
        return _norm_raw(name)

    def corp_codes(self) -> list[dict[str, str]]:
        path = self.cache_dir / "dart_corpcode.json"
        if path.exists() and time.time() - path.stat().st_mtime < 30 * 86400:
            return json.loads(path.read_text(encoding="utf-8"))
        r = self.client.get(f"{DART}/corpCode.xml", params={"crtfc_key": self.api_key}, timeout=60)
        if r.status_code != 200 or r.content[:2] != b"PK":
            raise RuntimeError(f"corpCode HTTP {r.status_code}")
        out: list[dict[str, str]] = []
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            with z.open(next(n for n in z.namelist() if n.lower().endswith(".xml"))) as fh:
                for _ev, el in ElementTree.iterparse(fh, events=("end",)):
                    if el.tag == "list":
                        code, name = (el.findtext("corp_code") or "").strip(), (el.findtext("corp_name") or "").strip()
                        if code and name:
                            out.append({"corp_code": code, "corp_name": name, "stock_code": (el.findtext("stock_code") or "").strip()})
                        el.clear()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        return out

    def find_corp(self, names: list[str]) -> dict[str, str] | None:
        if self._index is None:
            idx: dict[str, list[dict[str, str]]] = {}
            for it in self.corp_codes():
                idx.setdefault(self._norm(it["corp_name"]), []).append(it)
            self._index = idx
        for n in names:
            key = self._norm(n)
            if key and key in self._index:
                return sorted(self._index[key], key=lambda c: (not c.get("stock_code"), c["corp_code"]))[0]
        return None

    def company(self, corp_code: str) -> dict[str, Any] | None:
        r = self.client.get(f"{DART}/company.json", params={"crtfc_key": self.api_key, "corp_code": corp_code}, timeout=30)
        if r.status_code != 200:
            return None
        d = r.json()
        return d if d.get("status") == "000" else None

    @staticmethod
    def public_url(corp_code: str) -> str:
        return f"https://dart.fss.or.kr/dsae001/main.do?selectKey={corp_code}"
