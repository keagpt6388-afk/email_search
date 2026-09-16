"""이메일 탐색 파이프라인.

입력: 이름 · 소속 · 기술분야.  출처는 모두 공개·공식 API 이며 이메일 자체는 **저자가 문서에 공개한 값**만 쓴다(추측·조합 없음).

  1. 이름 형태: 로마자 표기(특허청 대문자 표기는 성 앞/뒤 두 해석) → 없으면 한글 → 로마자 **추정** 후보(소속 일치 저자가 실제로 있을 때만 채택)
  2. 소속 확장: 별칭 표 + DART 영문 상호·홈페이지 + Wikidata 레이블·공식 웹사이트 + 약어 풀기 + ROR(대표 이름 일치 우선·소속 매칭) + OpenAlex 기관 → 공식 도메인 집합
  3. OpenAlex 저자 연결: 이름 일치 + 소속(현재·과거) 일치, 기술분야 주제 일치 가점. 유일하면 식별자 확정, 여럿이면 상위 후보 논문을 훑음(추정 표기는 압도적 후보만)
  4. ORCID: 저자 레코드의 ORCID 또는 공개 검색(유일·소속 일치). 고용 기관이 소속과 전혀 겹치지 않으면 동명이인으로 보류. 공개 이메일·연구자 URL·저작물 DOI
  5. 문서 경로: Europe PMC 서지(저자 소속란 이메일) → 전문 JATS XML(저자 태그) → bioRxiv JATS → OA PDF(OpenAlex → Unpaywall → Semantic Scholar → CORE; 열림 호스트 우선, HTML 본문도 읽음) → 개인 홈페이지
  6. 귀속: 계정에 이름 조각·성+이니셜, 원문 근접, JATS 저자 태그. 검증: 소속 공식 도메인 일치(또는 ORCID 본인 레코드). 도메인이 없으면 이메일 도메인 홈페이지에서 기관명 확인
"""

from __future__ import annotations

import re
import time
from collections import Counter
from typing import Any

import httpx

from . import pdf as pdfmod
from .cache import Cache
from .config import Settings
from .models import EmailHit, Person, SearchResult
from .names import GENERIC_LOCALPART, PERSONAL_MAIL, attributed_to, extract_emails, latin_name_forms, romanization_candidates, same_person_name, snippet
from .orgs import REGISTRY, domain_matches, expand_abbreviations, host_of, same_org
from .sources import fulltext as ft
from .sources.openalex import OpenAlex, pdf_urls_of
from .sources.registries import Dart, Orcid, Ror, Wikidata


class EmailFinder:
    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None) -> None:
        self.s = settings or Settings()
        self.client = client or httpx.Client(timeout=self.s.timeout, headers={"User-Agent": self.s.user_agent}, follow_redirects=True)
        self.cache = Cache(self.s.cache_dir)
        self.openalex = OpenAlex(self.client, self.s.openalex_api_key, self.s.contact_email)
        self.ror = Ror(self.client)
        self.orcid = Orcid(self.client)
        self.wikidata = Wikidata(self.client)
        self.dart = Dart(self.client, self.s.dart_api_key, self.s.cache_dir) if self.s.dart_api_key else None

    # ---- 공개 진입점 ---------------------------------------------------------------------
    def find(self, person: Person) -> SearchResult:
        t0 = time.time()
        res = SearchResult(person=person)
        log = res.log
        names = list(person.names)

        # 1) 이름 형태
        forms: list[str] = []
        for n in names:
            for f in latin_name_forms(n):
                if f not in forms:
                    forms.append(f)
        guessed = False
        if not forms:
            for n in names:
                if n and not n.isascii():
                    forms = romanization_candidates(n, 16)
                    guessed = bool(forms)
                    break
        log.append(f"이름 형태 · {'로마자 추정 ' if guessed else '표기 '}{', '.join(forms[:4])}{' …' if len(forms) > 4 else ''}" if forms else "이름 형태 · 로마자 표기를 만들 수 없음")

        # 2) 소속 확장
        exp = self.expand_affiliation(person.affiliation)
        aff_all: list[str] = [person.affiliation, *exp["names"]]
        res.affiliation_names = list(dict.fromkeys(exp["names"]))
        res.official_domains = dict(exp["domains"])
        res.homepages = [(u, s) for u, s in exp["websites"]]
        if exp.get("ror"):
            res.identifiers["ror"] = exp["ror"]
        if exp["names"]:
            log.append(f"소속 확장 · '{person.affiliation}' → {', '.join(exp['names'][:5])} ({'·'.join(exp['sources'])})")
        if exp["domains"]:
            log.append("공식 도메인 · " + ", ".join(f"{d} ({'·'.join(s)})" for d, s in list(exp["domains"].items())[:4]))
        else:
            log.append("공식 도메인 · 없음(ROR·DART·Wikidata·OpenAlex 어디에도 홈페이지 정보 없음) — 이메일은 도메인 홈페이지 확인으로 검증 시도")
        domains: set[str] = set(exp["domains"])

        # 3) OpenAlex 저자 연결
        linked: list[tuple[str, str]] = []  # (author id, 표시 라벨)
        cands = self.link_authors(forms, aff_all, person.field, guessed)
        if cands["error"]:
            log.append(f"OpenAlex 저자 검색 실패 · {cands['error']}")
        top = cands["candidates"]
        if cands["unique"] is not None:
            u = cands["unique"]
            res.identifiers["openalex"] = u["id"]
            if u.get("orcid"):
                res.identifiers["orcid"] = u["orcid"]
            if guessed and u["display_name"] not in names:
                names.append(u["display_name"])
            linked.append((u["id"], "" if not guessed else f"로마자 추정 '{u['form']}' 로 연결한 저자 '{u['display_name']}'"))
            log.append(f"OpenAlex 저자 연결 · 유일 후보 '{u['display_name']}' ({u['institution']}, 저작물 {u['works_count']}편) [{cands['criteria']}]")
        elif top:
            if not guessed:
                for c in top[: self.s.author_candidates]:
                    linked.append((c["id"], f"저자 '{c['display_name']}' ({c['institution']}, {c['works_count']}편) — 후보 {len(top)}명 중 상위, 동명이인 가능성 확인"))
                log.append(f"OpenAlex 저자 연결 · 이름·소속 일치 후보 {len(top)}명 — 상위 {len(linked)}명의 OA 논문을 훑음: " + " / ".join(f"'{c['display_name']}'({c['works_count']}편)" for c in top[:2]))
            else:
                first, second = top[0], (top[1] if len(top) > 1 else None)
                dominant = first["works_count"] >= 20 and (second is None or first["works_count"] >= 3 * max(second["works_count"], 1) or same_person_name(first["display_name"], second["display_name"]))
                if dominant:
                    picks = [first] + ([second] if second is not None and same_person_name(first["display_name"], second["display_name"]) else [])
                    for c in picks:
                        if c["display_name"] not in names:
                            names.append(c["display_name"])
                        linked.append((c["id"], f"로마자 추정 '{c['form']}' 로 찾은 압도적 후보 '{c['display_name']}' ({c['institution']}, {c['works_count']}편) — 동명이인 가능성 확인"))
                    log.append(f"OpenAlex 저자 연결 · 로마자 추정 후보 {len(top)}명 중 압도적 후보 '{first['display_name']}'({first['works_count']}편)의 논문을 훑음")
                else:
                    log.append(f"OpenAlex 저자 연결 · 로마자 추정 후보 {len(top)}명이 비슷한 규모라 특정 불가(논문을 열지 않음): " + ", ".join(f"'{c['display_name']}'({c['works_count']}편)" for c in top[:3]))
        elif forms and not cands["error"]:
            log.append("OpenAlex 저자 연결 · 이름·소속 일치 저자 없음(논문이 없거나 표기가 다름)")

        # 4) ORCID
        orcid_id = res.identifiers.get("orcid") or self.search_orcid(forms if not guessed else [n for n in names if n.isascii()], aff_all)
        orcid_dois: list[str] = []
        personal_pages: list[tuple[str, str]] = []
        if orcid_id:
            rec = self.cache.cached(f"orcid:{orcid_id}", lambda: self.orcid.person(orcid_id))
            if rec:
                emp_names = [e["name"] for e in rec.get("employments", []) if e.get("name")]
                if emp_names and not any(same_org(a, n) for a in aff_all for n in emp_names):
                    log.append(f"ORCID {orcid_id.rsplit('/', 1)[-1]} 보류 · 고용 기관({', '.join(emp_names[:2])})이 소속과 불일치 — 동명이인 가능성으로 이 레코드는 쓰지 않음")
                    res.identifiers.pop("orcid", None)
                    rec = None
            if rec:
                res.identifiers["orcid"] = orcid_id
                for e in rec.get("emails", []):
                    res.emails.append(EmailHit(e["email"], "orcid", orcid_id, orcid_id, True, "ORCID 본인 레코드에 공개된 이메일 — 도메인 검증 불필요", "ORCID 본인 레코드" + (" (자기소개란)" if e.get("from") == "biography" else "")))
                for u in rec.get("urls", [])[:3]:
                    personal_pages.append((u["url"], "ORCID 연구자 URL"))
                    res.homepages.append((u["url"], "ORCID 연구자 URL"))
                for emp in sorted(rec.get("employments", []), key=lambda x: not x.get("current")):
                    rr = None
                    if emp.get("id_source") == "ROR" and emp.get("id"):
                        rr = self.cache.cached(f"ror:{emp['id']}", lambda emp=emp: self.ror.get(emp["id"]))
                    if rr:
                        for d in rr.get("domains") or []:
                            domains.add(d)
                            res.official_domains.setdefault(d, []).append("ORCID 고용→ROR")
                        if emp.get("name"):
                            REGISTRY.register([person.affiliation, emp["name"], *rr.get("names", [])] if any(same_org(person.affiliation, n) for n in rr.get("names", [])) else rr.get("names", []))
                orcid_dois = rec.get("dois", [])
                log.append(f"ORCID {orcid_id.rsplit('/', 1)[-1]} · 공개 이메일 {len(rec.get('emails', []))} · 웹사이트 {len(rec.get('urls', []))} · 고용 {len(rec.get('employments', []))} · 저작물 DOI {len(orcid_dois)}")

        # 5) 문서 경로: 저작물 목록
        works: list[dict[str, Any]] = []  # {doi, urls, label}
        seen_doi: set[str] = set()
        for aid, label in linked:
            for w in self.cache.cached(f"oa-works:{aid}", lambda aid=aid: self.openalex.author_oa_works(aid)) or []:
                doi = (w.get("doi") or "").replace("https://doi.org/", "").lower()
                key = doi or w.get("id", "")
                if key in seen_doi:
                    continue
                seen_doi.add(key)
                works.append({"doi": doi, "urls": pdf_urls_of(w), "label": label, "title": w.get("title") or "", "topics": [t.get("display_name", "") for t in (w.get("topics") or [])]})
        for doi in orcid_dois:
            if doi not in seen_doi:
                seen_doi.add(doi)
                works.append({"doi": doi, "urls": [], "label": "ORCID 저작물", "title": "", "topics": []})
        # 기술분야가 주어지면 그 분야 논문을 먼저 연다(같은 사람일 확률·이메일이 현재 소속일 확률)
        field_terms = [t.lower() for t in re.split(r"[\s,/·]+", person.field) if len(t) >= 3] if person.field else []
        if field_terms:
            works.sort(key=lambda w: 0 if any(ft_ in (w["title"] + " " + " ".join(w["topics"])).lower() for ft_ in field_terms) else 1)
        log.append(f"저작물 · OA 논문 {sum(1 for w in works if w['urls'])}건 + ORCID DOI {len(orcid_dois)}건")

        # 5a) Europe PMC · bioRxiv (문서당 1~2회, 최대 6개 DOI)
        epmc_checked = 0
        for w in [w for w in works if w["doi"]][:6]:
            doi = w["doi"]
            rec = self.cache.cached(f"epmc:{doi}", lambda doi=doi: ft.europepmc_record(self.client, doi))
            if rec:
                epmc_checked += 1
                for a in rec.get("authors", []):
                    if any(same_person_name(a["name"], n) for n in names if n):
                        for e in a["emails"]:
                            self._add(res, names, domains, e, "europepmc", rec.get("url") or f"https://europepmc.org/search?query=DOI:{doi}", doi, f"Europe PMC 저자란 이름 일치 '{a['name']}'", f"소속란: {a.get('affiliation', '')[:100]}")
                if rec.get("pmcid"):
                    xml = self.cache.cached(f"epmc-xml:{rec['pmcid']}", lambda p=rec["pmcid"]: ft.europepmc_fulltext(self.client, p))
                    for e, aname, why in self._jats_hits(names, xml):
                        self._add(res, names, domains, e, "europepmc_xml", (xml or {}).get("url", ""), doi, why, f"Europe PMC 전문 XML · 저자 '{aname}'")
            if doi.startswith("10.1101/"):
                bx = self.cache.cached(f"biorxiv:{doi}", lambda doi=doi: ft.biorxiv_jats(self.client, doi))
                for e, aname, why in self._jats_hits(names, bx):
                    self._add(res, names, domains, e, "biorxiv", (bx or {}).get("url", ""), doi, why, f"bioRxiv/medRxiv 전문 XML · 저자 '{aname}'")

        # 5b) OA PDF (열림 호스트 먼저, 차단 시도는 절반 비용)
        fetched, budget, failures, no_email = 0.0, float(self.s.pdf_budget), [], 0
        n_fetch = 0
        for w in works:
            if fetched >= budget or n_fetch >= self.s.pdf_budget * 2:
                break
            urls = list(w["urls"])
            if not urls and w["doi"]:
                urls = self.cache.cached(f"pdf-fallback:{w['doi']}", lambda d=w["doi"]: self._fallback_pdfs(d)) or []
            urls.sort(key=pdfmod.host_rank)
            for u in urls[:1]:
                n_fetch += 1
                r = self.cache.cached(f"pdf:{u}", lambda u=u: pdfmod.fetch_emails(self.client, u), cache_none=False) or {}
                if not r or r.get("error") or r.get("status") != 200:
                    failures.append((r.get("error") or f"HTTP {r.get('status')}") if r else "응답 없음")
                    fetched += 0.5
                    continue
                fetched += 1
                if not r.get("emails"):
                    no_email += 1
                for e in r["emails"]:
                    why = attributed_to(e, names, r.get("head", ""))
                    if why:
                        self._add(res, names, domains, e, "oa_html" if r.get("kind") == "html" else "oa_pdf", r.get("url") or u, w["doi"] or u, why + (f" · {w['label']}" if w["label"] else ""), (r.get("snippets") or {}).get(e, ""))
            if len([h for h in res.emails if h.verified]) >= 2:
                break
        fail_txt = (" · 열기 실패 " + ", ".join(f"{k}×{n}" for k, n in Counter(failures).most_common(3))) if failures else ""
        log.append(f"공개 전문 · Europe PMC 서지 {epmc_checked}건 · PDF/HTML 시도 {n_fetch}건{fail_txt}" + (f" · 읽었지만 이메일 없음 {no_email}건" if no_email else ""))

        # 5c) 개인 홈페이지
        for url, via in personal_pages[:2]:
            page = self.cache.cached(f"page:{url}", lambda u=url: self._page_emails(u))
            for e in (page or {}).get("emails", []):
                local = e.split("@")[0]
                generic = bool(GENERIC_LOCALPART.match(local)) or bool(re.search(r"(enquir|inquir|info|office|admin|contact|webmaster|support|general|dept|department)", local, re.I))  # 대표·부서 계정(menquiry@…)
                why = attributed_to(e, names, page.get("head", "")) or ("본인 홈페이지에 표기" if not generic and any(domain_matches(host_of(url), d) for d in domains) else None)
                if why:
                    self._add(res, names, domains, e, "homepage", url, url, f"{why} ({via})", snippet(page.get("head", ""), e))

        # 6) 도메인 없음 → 이메일 도메인 홈페이지에서 기관명 확인
        for h in res.emails:
            if not h.verified and "공식 도메인 정보 없음" in h.verification:
                dom = h.email.split("@")[-1]
                hit = self._domain_confirms_org(dom, aff_all)
                if hit:
                    h.verified, h.verification = True, f"도메인 확인 · {dom} 홈페이지에 기관명 '{hit}' 표기"
                    domains.add(dom)
                    res.official_domains.setdefault(dom, []).append("도메인 홈페이지 기관명 확인")

        # 중복 제거·정렬
        uniq: dict[tuple[str, str], EmailHit] = {}
        for h in res.emails:
            uniq.setdefault((h.email, h.source), h)
        # 정렬: 검증 → 귀속 근거가 강한 것(ORCID 본인·저자 태그·이름 조각) → 홈페이지 표기 → 이메일
        def strength(h: EmailHit) -> int:
            if "ORCID 본인" in h.attribution or "저자 태그" in h.attribution or "이름 '" in h.attribution or "성 '" in h.attribution or "저자란" in h.attribution:
                return 0
            return 1 if "바로 뒤" in h.attribution else 2
        res.emails = sorted(uniq.values(), key=lambda h: (not h.verified, strength(h), h.email))
        res.elapsed_s = time.time() - t0
        n_ok = len({h.email for h in res.emails if h.verified})
        log.append(f"결과 · 이메일 {len({h.email for h in res.emails})}개 (검증 {n_ok}개) · 근거 {len(res.emails)}건 · {res.elapsed_s:.0f}초")
        return res

    # ---- 내부 -----------------------------------------------------------------------------
    def _add(self, res: SearchResult, names: list[str], domains: set[str], email: str, source: str, url: str, doc: str, attribution: str, snip: str = "") -> None:
        email = email.lower().strip(".")
        dom = email.split("@")[-1]
        if domains:
            ok = any(domain_matches(dom, d) for d in domains)
            if ok:
                verification = "소속 공식 도메인 일치"
            elif PERSONAL_MAIL.search(dom + "."):
                verification = f"미검증 · 개인 메일 도메인({dom}) · 출처 문서에 실린 값 그대로"
            else:
                verification = f"미검증 · 소속 공식 도메인과 다름({dom}) — 이전 소속·겸직 가능"
        else:
            ok, verification = False, "미검증 · 소속 공식 도메인 정보 없음 — 출처 문서에 실린 값 그대로"
        res.emails.append(EmailHit(email, source, url, doc, ok, verification, attribution, snip))

    @staticmethod
    def _jats_hits(names: list[str], rec: dict[str, Any] | None) -> list[tuple[str, str, str]]:
        out = []
        for a in (rec or {}).get("authors") or []:
            if a.get("emails") and any(same_person_name(a.get("name", ""), n) for n in names if n):
                for e in a["emails"]:
                    out.append((e, a["name"], f"전문 XML 저자 태그 '{a['name']}'" + (" (교신저자)" if a.get("corresp") else "")))
        return out

    def _fallback_pdfs(self, doi: str) -> list[str]:
        urls: list[str] = []
        try:
            urls += ft.unpaywall_pdfs(self.client, doi, self.s.contact_email)
        except Exception:  # noqa: BLE001
            pass
        if not urls:
            try:
                u = ft.semanticscholar_pdf(self.client, doi, self.s.s2_api_key)
                if u:
                    urls.append(u)
            except Exception:  # noqa: BLE001
                pass
        if not urls:
            try:
                urls += ft.core_pdfs(self.client, doi, self.s.core_api_key)
            except Exception:  # noqa: BLE001
                pass
        return urls[:3]

    def _page_emails(self, url: str) -> dict[str, Any]:
        r = self.client.get(url, headers={"Accept": "text/html,*/*", "User-Agent": "Mozilla/5.0 (compatible; email-search/0.1)"}, timeout=20)
        if r.status_code != 200 or "html" not in (r.headers.get("content-type") or "").lower():
            return {"emails": [], "head": ""}
        html = r.text[:2_000_000]
        mailtos = [m.lower() for m in re.findall(r'href=["\']mailto:([^"\'?]+)', html, flags=re.I)]
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))
        return {"emails": list(dict.fromkeys([*mailtos, *extract_emails(text)])), "head": text[:8000]}

    def _domain_confirms_org(self, domain: str, org_names: list[str]) -> str | None:
        if not domain or PERSONAL_MAIL.search(domain + "."):
            return None
        base = domain
        for i in range(2):
            parts = base.split(".")
            if i:
                if len(parts) <= 2:
                    break
                base = ".".join(parts[1:])
            page = self.cache.cached(f"page:https://{base}/", lambda b=base: self._page_emails(f"https://{b}/"))
            head = ((page or {}).get("head") or "").lower()
            for n in org_names:
                k = (n or "").strip().lower()
                if len(re.sub(r"[^0-9a-z가-힣]", "", k)) >= 4 and k in head:
                    return n
        return None

    # ---- 소속 확장 ---------------------------------------------------------------------------
    def expand_affiliation(self, name: str) -> dict[str, Any]:
        rec = self.cache.cached(f"aff:v1:{name.lower()}", lambda: self._expand_one(name)) or {"names": [], "ror": "", "sources": [], "websites": []}
        found = [n for n in rec.get("names") or [] if n and not (n.isascii() and len(re.sub(r"[^A-Za-z]", "", n)) < 4)]
        group = list(dict.fromkeys([name, *REGISTRY.aliases(name), *found]))
        if len(group) > 1:
            REGISTRY.register(group)
        domains: dict[str, list[str]] = {}
        websites: list[tuple[str, str]] = []
        for url, src in rec.get("websites") or []:
            websites.append((url, src))
            d = host_of(url)
            if d and src not in domains.setdefault(d, []):
                domains[d].append(src)
        for d in rec.get("ror_domains") or []:
            domains.setdefault(d, []).insert(0, "ROR")
        return {"names": [n for n in group if n != name], "ror": rec.get("ror", ""), "sources": rec.get("sources", []), "websites": websites, "domains": domains}

    def _expand_one(self, name: str) -> dict[str, Any]:
        names: list[str] = []
        sources: list[str] = []
        websites: list[list[str]] = []
        ror_id, ror_domains = "", []
        seeds = [name]
        korean = bool(re.search(r"[가-힣]", name))

        def known() -> list[str]:
            return [name, *names]

        if self.dart is not None and korean:
            try:
                corp = self.dart.find_corp([name])
                info = self.dart.company(corp["corp_code"]) if corp else None
                if info:
                    eng = info.get("corp_name_eng") or ""
                    if eng:
                        names += [corp["corp_name"], eng]
                        seeds.append(eng)
                    hp = info.get("hm_url") or ""
                    if hp:
                        websites.append([hp if hp.startswith("http") else "https://" + hp, "DART 기업개황"])
                    sources.append("DART")
            except Exception:  # noqa: BLE001
                pass
        try:
            for h in self.wikidata.search(name, "ko" if korean else "en", 5):
                label, desc = h.get("label") or "", h.get("description") or ""
                if not (label and label.isascii() and Wikidata.ORG_CUES.search(desc)):
                    continue
                if not korean and not same_org(name, label, strict=True):
                    continue
                if korean:
                    matched = ((h.get("match") or {}).get("text") or "").replace(" ", "")
                    if matched and matched != name.replace(" ", ""):
                        continue
                names.append(label)
                seeds.append(label)
                sources.append("Wikidata")
                try:
                    for site in self.wikidata.official_websites(h["id"])[:2]:
                        websites.append([site, "Wikidata 공식 웹사이트"])
                except Exception:  # noqa: BLE001
                    pass
                break
        except Exception:  # noqa: BLE001
            pass
        exp = expand_abbreviations(name)
        if exp:
            seeds.append(exp)
        for seed in list(dict.fromkeys(seeds))[:4]:
            if ror_id:
                break
            try:
                items = self.ror.search(seed)
                pick = next((t for t in items[:5] if any(same_org(k, t["display_name"], strict=True) for k in known())), None) or next((t for t in items[:5] if any(same_org(k, n, strict=True) for k in known() for n in t["names"])), None)
                if not pick:
                    pick = self.ror.match_affiliation(seed)
                if pick:
                    names += pick["names"]
                    ror_id, ror_domains = pick.get("ror", ""), pick.get("domains", [])
                    if pick.get("website"):
                        websites.append([pick["website"], "ROR"])
                    sources.append("ROR")
            except Exception:  # noqa: BLE001
                continue
        for seed in list(dict.fromkeys(seeds))[:4]:
            try:
                hit = False
                for inst in self.openalex.search_institutions(seed, 5):
                    cand = [inst.get("display_name") or "", *(inst.get("display_name_alternatives") or [])]
                    if any(same_org(k, n, strict=True) for k in known() for n in cand if n):
                        names += [n for n in cand if n]
                        if inst.get("homepage_url"):
                            websites.append([inst["homepage_url"], "OpenAlex 기관 레코드"])
                        if not ror_id and inst.get("ror"):
                            rr = self.ror.get(inst["ror"])
                            if rr:
                                ror_id, ror_domains = rr.get("ror", ""), rr.get("domains", [])
                                names += rr.get("names", [])
                        sources.append("OpenAlex 기관")
                        hit = True
                        break
                if hit:
                    break
            except Exception:  # noqa: BLE001
                continue
        return {"names": list(dict.fromkeys(n for n in names if n and n != name))[:20], "ror": ror_id, "ror_domains": ror_domains, "sources": list(dict.fromkeys(sources)), "websites": websites[:5]}

    # ---- 저자 연결 ---------------------------------------------------------------------------
    def link_authors(self, forms: list[str], affs: list[str], field: str, guessed: bool) -> dict[str, Any]:
        out: dict[str, Any] = {"candidates": [], "unique": None, "criteria": "", "error": ""}
        if not forms or not affs:
            return out
        terms = {t.lower() for t in re.split(r"[\s,/·]+", field) if len(t) >= 3}
        seen: set[str] = set()
        cands: list[dict[str, Any]] = []
        for form in forms[: (16 if guessed else 4)]:
            try:
                found = self.cache.cached(f"oa-authors:{form.lower()}", lambda f=form: self.openalex.search_authors(f), cache_none=False)
            except Exception:  # noqa: BLE001
                found = None
            if found is None:
                out["error"] = self.openalex.last_error or "조회 실패"
                continue
            for a in found:
                aid = a.get("id") or ""
                if not aid or aid in seen:
                    continue
                seen.add(aid)
                alts = [a.get("display_name") or "", *(a.get("display_name_alternatives") or [])[:10]]
                if not any(same_person_name(form, n) for n in alts if n):
                    continue
                current = [i.get("display_name") or "" for i in (a.get("last_known_institutions") or [])]
                history = [((x.get("institution") or {}).get("display_name") or "") for x in (a.get("affiliations") or [])]
                hit_cur = next((y for x in affs for y in current if y and same_org(x, y)), None)
                hit_hist = None if hit_cur else next((y for x in affs for y in history if y and same_org(x, y)), None)
                if not (hit_cur or hit_hist):
                    continue
                topics = [(t.get("display_name") or "").lower() for t in (a.get("topics") or [])]
                cands.append({"id": aid, "display_name": a.get("display_name") or "", "orcid": a.get("orcid") or "", "works_count": int(a.get("works_count") or 0),
                              "institution": hit_cur or hit_hist or "", "current": bool(hit_cur), "topic_hit": bool(terms) and any(term in tp or tp in term for tp in topics for term in terms), "form": form})
            if guessed and len(cands) >= 4:
                break
        cands.sort(key=lambda c: (not c["current"], not c["topic_hit"], -c["works_count"]))
        out["candidates"] = cands
        pool, crit = list(cands), ["이름 일치", "소속 일치"]
        if len(pool) != 1 and [c for c in pool if c["current"]]:
            pool, crit = [c for c in pool if c["current"]], [*crit, "현재 소속"]
        if len(pool) != 1 and [c for c in pool if c["topic_hit"]]:
            pool, crit = [c for c in pool if c["topic_hit"]], [*crit, "기술분야 주제 일치"]
        if len(pool) == 1:
            out["unique"], out["criteria"] = pool[0], " · ".join(crit)
        return out

    # ---- ORCID 검색 ---------------------------------------------------------------------------
    def search_orcid(self, forms: list[str], affs: list[str]) -> str | None:
        for form in forms[:2]:
            toks = form.split()
            if len(toks) < 2:
                continue
            given, family = " ".join(toks[:-1]), toks[-1]
            cands = self.cache.cached(f"orcid-search:{form.lower()}", lambda g=given, f=family: self.orcid.search(g, f)) or []
            exact = [c for c in cands if same_person_name(f"{c['given']} {c['family']}", form)]
            if len(exact) == 1 and (not exact[0]["institutions"] or any(same_org(a, i) for a in affs for i in exact[0]["institutions"])):
                return f"https://orcid.org/{exact[0]['orcid']}"
            by_aff = [c for c in exact if any(same_org(a, i) for a in affs for i in c["institutions"])]
            if len(by_aff) == 1:
                return f"https://orcid.org/{by_aff[0]['orcid']}"
        return None
