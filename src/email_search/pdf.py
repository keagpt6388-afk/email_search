"""공개 전문 PDF(또는 PDF 대신 온 HTML) 첫 3쪽에서 이메일. IEEE stamp.jsp 래퍼는 안의 PDF 로 한 번 더 들어간다."""

from __future__ import annotations

import io
import logging
import re
from typing import Any

import httpx

from .names import EMAIL_RE, deobfuscate, extract_emails, snippet

_OPEN_HOSTS = re.compile(r"arxiv\.org|europepmc\.org|ncbi\.nlm\.nih\.gov|koreascience|\.ac\.kr|\.edu(/|$)|\.ac\.uk|\.ac\.jp|biorxiv|medrxiv|osti\.gov|hal\.science|zenodo|core\.ac\.uk|semanticscholar|openreview|aclanthology|thecvf|ieeexplore\.ieee\.org/(ielx|stampPDF)|dspace|repository|scholarworks|s-space|dcollection", re.I)
_BLOCKY_HOSTS = re.compile(r"mdpi\.com|wiley\.com|sciencedirect|elsevier|springer|nature\.com|tandfonline|acs\.org|sagepub|frontiersin|iop\.org|rsc\.org|pubs\.|cell\.com|jstage", re.I)


def host_rank(url: str) -> int:
    """0 열림(리포지터리·프리프린트·PMC) · 1 미상 · 2 출판사(봇 차단 잦음). 배포 환경(공용 IP)에서는 출판사 PDF 가 대부분 차단된다."""
    if _OPEN_HOSTS.search(url):
        return 0
    if _BLOCKY_HOSTS.search(url):
        return 2
    return 1


def pdf_text(content: bytes, max_pages: int = 3) -> str:
    from pypdf import PdfReader
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = PdfReader(io.BytesIO(content))
    out = []
    for page in reader.pages[:max_pages]:
        try:
            out.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001
            continue
    return "\n".join(out)


def fetch_emails(client: httpx.Client, url: str) -> dict[str, Any]:
    """→ {"status", "url", "emails", "snippets", "head", "error", "kind": "pdf"|"html"}."""
    headers = {"Accept": "application/pdf,*/*", "User-Agent": "Mozilla/5.0 (compatible; email-search/0.1)"}
    target = url
    m = re.search(r"ieeexplore\.ieee\.org/stamp/stamp\.jsp\?.*?arnumber=(\d+)", url)
    if m:
        target = f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={m.group(1)}"
    try:
        r = client.get(target, headers=headers, follow_redirects=True, timeout=30)
    except Exception as exc:  # noqa: BLE001
        return {"status": 0, "url": url, "emails": [], "error": type(exc).__name__}
    ctype = (r.headers.get("content-type") or "").lower()
    if r.status_code == 200 and "html" in ctype and "ieeexplore" in str(r.url):
        inner = re.search(r'(?:src|href)=["\']([^"\']*(?:ielx\d*/[^"\']*\.pdf|stampPDF/getPDF[^"\']*))', r.text)
        if inner:
            r = client.get(inner.group(1).replace("&amp;", "&"), headers=headers, follow_redirects=True, timeout=30)
            ctype = (r.headers.get("content-type") or "").lower()
    if r.status_code == 200 and "html" in ctype and not r.content[:5].startswith(b"%PDF"):
        html = r.text[:2_000_000]
        if re.search(r"captcha|are you a robot|access denied|just a moment|enable javascript and cookies", html[:20000], re.I):
            return {"status": 200, "url": str(r.url), "emails": [], "error": "봇 차단 페이지"}
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
        text = re.sub(r"\s+", " ", deobfuscate(re.sub(r"<[^>]+>", " ", text)))
        mailtos = [deobfuscate(x).lower() for x in re.findall(r'href=["\']mailto:([^"\'?]+)', html, flags=re.I)]
        emails = list(dict.fromkeys([*[x for x in mailtos if EMAIL_RE.fullmatch(x)], *extract_emails(text)]))
        if not emails:
            return {"status": 200, "url": str(r.url), "emails": [], "error": f"PDF 아님({ctype[:30]})"}
        return {"status": 200, "url": str(r.url), "emails": emails, "snippets": {e: snippet(text, e) for e in emails[:20]}, "head": text[:8000], "kind": "html"}
    if r.status_code != 200 or ("pdf" not in ctype and not r.content[:5].startswith(b"%PDF")):
        return {"status": r.status_code, "url": str(r.url), "emails": [], "error": f"PDF 아님({ctype[:30]})" if r.status_code == 200 else ""}
    if len(r.content) > 12_000_000:
        return {"status": 200, "url": str(r.url), "emails": [], "error": "PDF 12MB 초과"}
    try:
        text = pdf_text(r.content)
    except Exception as exc:  # noqa: BLE001
        return {"status": 200, "url": str(r.url), "emails": [], "error": f"PDF 파싱 실패 {type(exc).__name__}"}
    text = re.sub(r"[ \t]+", " ", text)
    for mm in re.finditer(r"\{([^{}]{1,120})\}\s*@\s*([A-Za-z0-9.-]+\.[A-Za-z]{2,})", text):  # '{a, b}@dept.edu' 펼치기
        for local in re.split(r"[,\s;]+", mm.group(1)):
            if local:
                text += f"\n{local}@{mm.group(2)}"
    emails = extract_emails(text)
    return {"status": 200, "url": str(r.url), "emails": emails, "snippets": {e: snippet(text, e) for e in emails[:20]}, "head": text[:8000], "kind": "pdf"}
