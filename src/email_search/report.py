"""출력 형식.

  · to_techgpt(results)  : TECH-GPT V2 「응답 표출 규격서」(v1.1) 형식 — 최상위 키마다 {type, data}. answer(모델용 요약) · table(전문가별 한 줄) · card(전문가별 상세) · text(탐색 로그·이용 안내).
                           표·카드의 링크 컬럼은 {text, url} 또는 그 배열(link 는 http·https·mailto 만).
  · to_xlsx(results, path): 첨부 예시(특허 전문가 검색_일반.xlsx)와 같은 표 형태의 스프레드시트(시트 '이메일 검색' + '상세' + '로그').
  · to_markdown(results)  : 터미널·문서용.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import EmailHit, SearchResult

SOURCE_LABEL = {
    "orcid": "ORCID 공개 레코드", "europepmc": "Europe PMC 서지(저자 소속란)", "europepmc_xml": "Europe PMC 전문 XML(저자 태그)", "biorxiv": "bioRxiv/medRxiv 전문 XML",
    "oa_pdf": "공개 전문 PDF", "oa_html": "공개 전문 페이지(HTML)", "homepage": "개인 홈페이지",
}
NOTICE = ("이메일은 저자·연구자가 논문·ORCID 등 공개 문서에 스스로 공개한 값만 표시하며 추측·조합하지 않습니다. "
          "학술·기술 협력 문의 목적의 개별 연락에 쓰고, 대량 광고 발송에는 쓰지 마십시오(정보통신망법 영리 광고 규제). "
          "'검증' 은 이메일 도메인이 소속 기관 공식 도메인과 일치함을 뜻하며, 미검증은 출처 문서에 실린 값을 그대로 보인 것입니다.")


def _link(text: str, url: str) -> dict[str, str]:
    return {"text": text, "url": url}


def _email_links(hits: list[EmailHit]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out = []
    for h in hits:
        if h.email in seen:
            continue
        seen.add(h.email)
        out.append(_link(h.email + ("" if h.verified else " (미검증)"), f"mailto:{h.email}"))
    return out


def _source_links(hits: list[EmailHit]) -> list[dict[str, str]]:
    out, seen = [], set()
    for h in hits:
        key = (h.source, h.source_url)
        if key in seen or not h.source_url:
            continue
        seen.add(key)
        out.append(_link(SOURCE_LABEL.get(h.source, h.source), h.source_url))
    return out


def _id_links(ids: dict[str, str]) -> list[dict[str, str]]:
    out = []
    if ids.get("orcid"):
        out.append(_link("ORCID " + ids["orcid"].rsplit("/", 1)[-1], ids["orcid"]))
    if ids.get("openalex"):
        out.append(_link("OpenAlex " + ids["openalex"].rsplit("/", 1)[-1], ids["openalex"]))
    if ids.get("ror"):
        out.append(_link("ROR " + ids["ror"].rsplit("/", 1)[-1], ids["ror"]))
    return out


def to_techgpt(results: list[SearchResult], caption: str = "이메일 검색 결과") -> dict[str, Any]:
    rows_table, rows_card = [], []
    for i, r in enumerate(results, 1):
        best = r.best
        verified = [h for h in r.emails if h.verified]
        rows_table.append({
            "rank": i, "name": r.person.name, "affil": r.person.affiliation, "field": r.person.field or None,
            "email": _email_links(r.emails) or None,
            "status": ("검증됨" if verified else ("미검증" if r.emails else "미발견")),
            "source": _source_links(r.emails) or None,
            "attribution": best.attribution if best else None,
            "ids": _id_links(r.identifiers) or None,
            "domains": ", ".join(r.official_domains) or None,
            "homepage": [_link(src, url) for url, src in r.homepages[:3]] or None,
        })
        rows_card.append({
            "name": r.person.name, "affil": r.person.affiliation, "field": r.person.field or None,
            "emails": _email_links(r.emails) or None,
            "verification": "; ".join(dict.fromkeys(f"{h.email}: {h.verification}" for h in r.emails)) or None,
            "attribution": "; ".join(dict.fromkeys(f"{h.email}: {h.attribution}" for h in r.emails)) or None,
            "source": _source_links(r.emails) or None,
            "snippet": next((h.snippet for h in r.emails if h.snippet), None),
            "ids": _id_links(r.identifiers) or None,
            "affil_names": ", ".join(r.affiliation_names[:6]) or None,
            "domains": ", ".join(f"{d} ({'·'.join(s)})" for d, s in r.official_domains.items()) or None,
            "homepage": [_link(src, url) for url, src in r.homepages[:4]] or None,
            "log": "\n".join(f"- {x}" for x in r.log),
            "elapsed": f"{r.elapsed_s:.0f}초",
        })
    n_found = sum(1 for r in results if r.emails)
    n_ver = sum(1 for r in results if any(h.verified for h in r.emails))
    answer_lines = [f"{len(results)}명 중 이메일을 찾은 사람 {n_found}명(검증 {n_ver}명)."]
    for r in results:
        b = r.best
        answer_lines.append(f"- {r.person.name} ({r.person.affiliation}): " + (f"{b.email} [{'검증' if b.verified else '미검증'} · {SOURCE_LABEL.get(b.source, b.source)}]" if b else "공개 출처에서 이메일을 찾지 못함" + (f" · 공식 도메인 {', '.join(list(r.official_domains)[:2])}" if r.official_domains else "")))
    return {
        "answer": {"type": "answer", "data": "\n".join(answer_lines)},
        "email_table": {"type": "table", "data": [{
            "caption": caption,
            "fields": {"rank": "순위", "name": "전문가", "affil": "소속", "field": "기술분야", "email": "이메일", "status": "검증", "source": "출처", "attribution": "귀속 근거", "ids": "식별자", "domains": "공식 도메인", "homepage": "소속 홈페이지"},
            "order": ["rank", "name", "affil", "field", "email", "status", "source", "attribution", "ids", "domains", "homepage"],
            "link": ["email", "source", "ids", "homepage"],
            "highlight": ["email", "status"],
            "note": "검증 = 이메일 도메인이 소속 공식 도메인과 일치(ORCID 본인 레코드는 검증 불필요). 미검증 = 출처 문서에 실린 값 그대로.",
            "rows": rows_table,
        }]},
        "email_cards": {"type": "card", "data": [{
            "caption": "전문가별 상세", "title": "name", "subtitle": "affil",
            "fields": {"name": "전문가", "affil": "소속", "field": "기술분야", "emails": "이메일", "verification": "검증", "attribution": "귀속 근거", "source": "출처", "snippet": "원문 발췌", "ids": "식별자", "affil_names": "소속 표기 확장", "domains": "공식 도메인", "homepage": "홈페이지", "log": "탐색 로그", "elapsed": "소요"},
            "order": ["name", "affil", "field", "emails", "verification", "attribution", "source", "snippet", "ids", "affil_names", "domains", "homepage", "log", "elapsed"],
            "link": ["emails", "source", "ids", "homepage"],
            "highlight": ["emails"],
            "rows": rows_card,
        }]},
        "notice": {"type": "text", "data": [{"caption": "이용 안내", "content": NOTICE}]},
    }


def to_markdown(results: list[SearchResult]) -> str:
    lines = ["| 순위 | 전문가 | 소속 | 이메일 | 검증 | 출처 | 귀속 근거 |", "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(results, 1):
        b = r.best
        lines.append(f"| {i} | {r.person.name} | {r.person.affiliation} | {b.email if b else '-'} | {('검증' if b.verified else '미검증') if b else '-'} | {SOURCE_LABEL.get(b.source, b.source) if b else '-'} | {b.attribution if b else '-'} |")
    return "\n".join(lines)


def to_xlsx(results: list[SearchResult], path: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "이메일 검색"
    head = ["순위", "전문가", "소속", "기술분야", "이메일", "검증", "출처", "출처 URL", "귀속 근거", "ORCID", "OpenAlex", "공식 도메인", "소속 홈페이지", "추가 이메일"]
    ws.append(head)
    for i, r in enumerate(results, 1):
        b = r.best
        extra = "; ".join(dict.fromkeys(h.email for h in r.emails if not b or h.email != b.email))
        ws.append([i, r.person.name, r.person.affiliation, r.person.field, b.email if b else "", ("검증" if b.verified else "미검증") if b else "미발견",
                   SOURCE_LABEL.get(b.source, b.source) if b else "", b.source_url if b else "", b.attribution if b else "",
                   r.identifiers.get("orcid", ""), r.identifiers.get("openalex", ""), ", ".join(r.official_domains), r.homepages[0][0] if r.homepages else "", extra])
    ws2 = wb.create_sheet("상세")
    ws2.append(["전문가", "소속", "이메일", "검증", "검증 설명", "출처", "출처 URL", "문서", "귀속 근거", "원문 발췌"])
    for r in results:
        for h in r.emails:
            ws2.append([r.person.name, r.person.affiliation, h.email, "검증" if h.verified else "미검증", h.verification, SOURCE_LABEL.get(h.source, h.source), h.source_url, h.document_id, h.attribution, h.snippet[:200]])
    ws3 = wb.create_sheet("로그")
    ws3.append(["전문가", "소속", "단계", "내용"])
    for r in results:
        for j, line in enumerate(r.log, 1):
            ws3.append([r.person.name, r.person.affiliation, j, line])
    ws4 = wb.create_sheet("안내")
    ws4.append([NOTICE])
    for sheet, widths in ((ws, [6, 12, 18, 14, 30, 8, 24, 50, 36, 30, 34, 26, 40, 30]), (ws2, [12, 18, 30, 8, 44, 24, 50, 30, 40, 60]), (ws3, [12, 18, 6, 120])):
        for col, w in enumerate(widths, 1):
            sheet.column_dimensions[get_column_letter(col)].width = w
        for c in sheet[1]:
            c.font = Font(bold=True)
            c.fill = PatternFill("solid", fgColor="DDEBF7")
            c.alignment = Alignment(horizontal="center")
        sheet.freeze_panes = "A2"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
