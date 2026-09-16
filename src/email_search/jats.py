"""JATS XML(Europe PMC fullTextXML·bioRxiv) 에서 저자별 이메일. <contrib> 안 <email>, <xref ref-type="corresp"> → <corresp>/<fn> 이메일을 저자와 연결한다."""

from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _text(el: ElementTree.Element | None) -> str:
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def _ln(tag: Any) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _iter(el: ElementTree.Element, name: str):
    for e in el.iter():
        if _ln(e.tag) == name:
            yield e


def _child(el: ElementTree.Element | None, name: str) -> ElementTree.Element | None:
    if el is None:
        return None
    return next((c for c in el if _ln(c.tag) == name), None)


def parse_jats_emails(xml_text: str) -> dict[str, Any]:
    """→ {"authors": [{"name", "emails", "corresp"}], "corresp_emails": [...]}. 편집자(contrib-type≠author)는 제외."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return {"authors": [], "corresp_emails": []}
    corresp: dict[str, list[str]] = {}
    for notes in _iter(root, "author-notes"):
        for c in notes:
            if _ln(c.tag) not in ("corresp", "fn"):
                continue
            emails = [_text(e) for e in _iter(c, "email") if _text(e)]
            emails += [m for m in _EMAIL_RE.findall(_text(c)) if m not in emails]
            if emails:
                corresp[c.get("id") or f"_{len(corresp)}"] = emails
    for c in _iter(root, "corresp"):
        if c.get("id") not in corresp:
            emails = [_text(e) for e in _iter(c, "email") if _text(e)]
            emails += [m for m in _EMAIL_RE.findall(_text(c)) if m not in emails]
            if emails:
                corresp[c.get("id") or f"_{len(corresp)}"] = emails
    contribs = []
    rid_users: dict[str, int] = {}
    for contrib in _iter(root, "contrib"):
        if (contrib.get("contrib-type") or "author") != "author":
            continue
        name_el = _child(contrib, "name") or _child(_child(contrib, "name-alternatives"), "name")
        if name_el is not None:
            name = f"{_text(_child(name_el, 'given-names'))} {_text(_child(name_el, 'surname'))}".strip()
        else:
            name = _text(_child(contrib, "string-name"))
        if not name:
            continue
        rids = [x.get("rid") for x in _iter(contrib, "xref") if x.get("ref-type") in ("corresp", "author-notes", "fn") and x.get("rid")]
        for rid in rids:
            rid_users[rid] = rid_users.get(rid, 0) + 1
        contribs.append((contrib, name, rids))
    authors: list[dict[str, Any]] = []
    for contrib, name, rids in contribs:
        emails = [_text(e) for e in _iter(contrib, "email") if _text(e)]
        for rid in rids:
            shared = corresp.get(rid, [])
            if len(shared) > 1 and rid_users.get(rid, 0) > 1:
                # 교신저자 둘이 <corresp> 하나에 이메일 둘을 함께 적은 경우(실측 PMC12385360: smchoi@… sshan@…) → 계정에 이름 흔적이 있는 것만 그 저자에게
                from .names import attributed_to
                mine = [e for e in shared if attributed_to(e, [name])]
                shared = mine or shared
            emails += [e for e in shared if e not in emails]
        authors.append({"name": name, "emails": emails, "corresp": contrib.get("corresp") == "yes" or any(r in corresp for r in rids)})
    flat = [e for es in corresp.values() for e in es]
    marked = [a for a in authors if a["corresp"] and not a["emails"]]
    if len(corresp) == 1 and len(marked) == 1 and flat:
        marked[0]["emails"] = list(dict.fromkeys(flat))
    return {"authors": authors, "corresp_emails": list(dict.fromkeys(flat))}
