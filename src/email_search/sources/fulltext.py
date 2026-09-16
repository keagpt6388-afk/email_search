"""전문(full text) 출처: Europe PMC(서지·JATS XML), bioRxiv/medRxiv(JATS), Unpaywall·Semantic Scholar·CORE(OA PDF 위치). 모두 무료, 키 선택."""

from __future__ import annotations

from typing import Any

import httpx

from ..jats import parse_jats_emails
from ..names import extract_emails

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"


def europepmc_record(client: httpx.Client, doi: str) -> dict[str, Any] | None:
    """DOI → {pmid, pmcid, is_oa, authors:[{name, emails, affiliation}]} (저자 소속란의 이메일은 저자 이름과 함께 와 귀속이 정확)."""
    r = client.get(f"{EPMC}/search", params={"query": f'DOI:"{doi}"', "resultType": "core", "format": "json"}, timeout=25)
    if r.status_code != 200:
        return None
    res = ((r.json().get("resultList") or {}).get("result") or [])
    if not res:
        return {"authors": [], "pmcid": "", "pmid": "", "is_oa": False}
    top = res[0]
    authors = []
    for a in ((top.get("authorList") or {}).get("author") or []):
        affs = [x.get("affiliation", "") for x in ((a.get("authorAffiliationDetailsList") or {}).get("authorAffiliation") or [])]
        emails = [e for aff in affs for e in extract_emails(aff)]
        if emails:
            authors.append({"name": a.get("fullName") or "", "emails": emails, "affiliation": affs[0][:160] if affs else ""})
    return {"authors": authors, "pmid": top.get("pmid") or "", "pmcid": top.get("pmcid") or "", "is_oa": (top.get("isOpenAccess") or "") == "Y",
            "url": f"https://europepmc.org/abstract/MED/{top.get('pmid')}" if top.get("pmid") else ""}


def europepmc_fulltext(client: httpx.Client, pmcid: str) -> dict[str, Any] | None:
    r = client.get(f"{EPMC}/{pmcid}/fullTextXML", timeout=30)
    if r.status_code != 200 or "<article" not in r.text[:5000]:
        return None
    out = parse_jats_emails(r.text)
    out["url"] = f"https://europepmc.org/article/PMC/{pmcid.removeprefix('PMC')}"
    return out


def biorxiv_jats(client: httpx.Client, doi: str) -> dict[str, Any] | None:
    for server in ("biorxiv", "medrxiv"):
        r = client.get(f"https://api.biorxiv.org/details/{server}/{doi}", timeout=30)
        if r.status_code != 200:
            continue
        col = r.json().get("collection") or []
        if not col:
            continue
        item = col[-1]
        jats = item.get("jatsxml") or ""
        if not jats:
            continue
        x = client.get(jats, timeout=30)
        if x.status_code != 200:
            continue
        out = parse_jats_emails(x.text)
        out["url"] = f"https://www.{server}.org/content/{doi}v{item.get('version') or 1}"
        return out
    return None


def unpaywall_pdfs(client: httpx.Client, doi: str, email: str) -> list[str]:
    if not email or "@" not in email:
        return []
    r = client.get(f"https://api.unpaywall.org/v2/{doi}", params={"email": email}, timeout=20)
    if r.status_code != 200:
        return []
    d = r.json()
    urls = [(d.get("best_oa_location") or {}).get("url_for_pdf")] + [l.get("url_for_pdf") for l in d.get("oa_locations") or []]
    return list(dict.fromkeys(u for u in urls if u))[:3]


def semanticscholar_pdf(client: httpx.Client, doi: str, api_key: str = "") -> str:
    headers = {"x-api-key": api_key} if api_key else {}
    r = client.get(f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}", params={"fields": "openAccessPdf"}, headers=headers, timeout=20)
    if r.status_code != 200:
        return ""
    return ((r.json().get("openAccessPdf") or {}).get("url") or "").strip()


def core_pdfs(client: httpx.Client, doi: str, api_key: str = "") -> list[str]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    r = client.get("https://api.core.ac.uk/v3/search/works", params={"q": f'doi:"{doi}"', "limit": 3}, headers=headers, timeout=30)
    if r.status_code != 200:
        return []
    urls: list[str] = []
    for w in r.json().get("results") or []:
        for u in [w.get("downloadUrl"), *[l.get("url") for l in (w.get("links") or []) if l.get("type") == "download"]]:
            if u and u not in urls:
                urls.append(u)
    return urls[:3]
