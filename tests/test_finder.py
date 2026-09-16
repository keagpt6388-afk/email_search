"""파이프라인 통합(모의 서버): 한글 이름 → 로마자 추정 → OpenAlex 저자(유일) → ORCID(고용 일치) → Europe PMC 전문 XML → 검증된 이메일, 규격 JSON."""

import httpx

from email_search.config import Settings
from email_search.finder import EmailFinder
from email_search.models import Person
from email_search.report import to_techgpt, to_xlsx

JATS = """<article><front><article-meta><contrib-group>
<contrib contrib-type="author" corresp="yes"><name><surname>Jang</surname><given-names>Jinah</given-names></name><xref ref-type="corresp" rid="c1"/></contrib>
<contrib contrib-type="author"><name><surname>Kim</surname><given-names>Minsu</given-names></name><email>minsu@postech.ac.kr</email></contrib>
</contrib-group><author-notes><corresp id="c1"><email>jinahjang@postech.ac.kr</email></corresp></author-notes></article-meta></front></article>"""


def handler(request: httpx.Request) -> httpx.Response:
    u, p = str(request.url), request.url.params
    if "api.openalex.org/authors" in u:
        if p.get("search", "").lower() in ("jinah jang", "jin ah jang"):
            return httpx.Response(200, json={"results": [{"id": "https://openalex.org/A1", "display_name": "Jinah Jang", "orcid": "https://orcid.org/0000-0001-9046-3495", "works_count": 242,
                                                          "last_known_institutions": [{"display_name": "Pohang University of Science and Technology"}], "affiliations": [], "topics": [{"display_name": "3D Bioprinting"}]}]})
        return httpx.Response(200, json={"results": []})
    if "api.openalex.org/institutions" in u:
        return httpx.Response(200, json={"results": [{"id": "https://openalex.org/I1", "ror": "https://ror.org/04xysgw12", "display_name": "Pohang University of Science and Technology", "display_name_alternatives": ["POSTECH"], "homepage_url": "https://postech.ac.kr"}]})
    if "api.openalex.org/works" in u:
        return httpx.Response(200, json={"results": [{"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1000/bio1", "title": "3D bioprinting of tissue", "best_oa_location": {"pdf_url": None}, "locations": [], "topics": []}]})
    if "api.ror.org" in u:
        rec = {"id": "https://ror.org/04xysgw12", "names": [{"value": "Pohang University of Science and Technology", "types": ["ror_display"]}, {"value": "POSTECH", "types": ["acronym"]}, {"value": "포항공과대학교", "types": ["label"]}],
               "links": [{"type": "website", "value": "https://postech.ac.kr"}], "domains": ["postech.ac.kr"]}
        return httpx.Response(200, json=rec if u.rstrip("/").endswith("04xysgw12") else {"items": [rec]})
    if "wikidata.org" in u:
        return httpx.Response(200, json={"search": []})
    if "pub.orcid.org" in u and "/person" in u:
        return httpx.Response(200, json={"emails": {"email": []}, "researcher-urls": {"researcher-url": []}, "biography": None})
    if "pub.orcid.org" in u and "/employments" in u:
        return httpx.Response(200, json={"affiliation-group": [{"summaries": [{"employment-summary": {"organization": {"name": "Pohang University of Science and Technology", "disambiguated-organization": {"disambiguated-organization-identifier": "https://ror.org/04xysgw12", "disambiguation-source": "ROR"}}, "end-date": None}}]}]})
    if "pub.orcid.org" in u and "/works" in u:
        return httpx.Response(200, json={"group": []})
    if "europepmc/webservices/rest/search" in u:
        return httpx.Response(200, json={"resultList": {"result": [{"pmid": "1", "pmcid": "PMC77", "isOpenAccess": "Y", "authorList": {"author": []}}]}})
    if "/PMC77/fullTextXML" in u:
        return httpx.Response(200, text=JATS)
    return httpx.Response(404)


def test_pipeline_finds_verified_email_and_formats_spec(tmp_path):
    settings = Settings(cache_dir=tmp_path / "cache", contact_email="test@example.org", pdf_budget=2)
    finder = EmailFinder(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    res = finder.find(Person(name="장진아", affiliation="포항공과대학교", field="바이오프린팅"))
    emails = {(h.email, h.source, h.verified) for h in res.emails}
    assert ("jinahjang@postech.ac.kr", "europepmc_xml", True) in emails
    assert not any(e == "minsu@postech.ac.kr" for e, _, _ in emails)  # 공저자 이메일 제외
    assert res.identifiers["openalex"].endswith("A1") and res.identifiers["orcid"].endswith("3495") and "postech.ac.kr" in res.official_domains
    assert any("로마자 추정" in line for line in res.log)

    out = to_techgpt([res])
    assert set(out) == {"answer", "email_table", "email_cards", "notice"}
    tbl = out["email_table"]
    assert tbl["type"] == "table" and tbl["data"][0]["order"][0] == "rank"
    row = tbl["data"][0]["rows"][0]
    assert row["status"] == "검증됨" and row["email"][0] == {"text": "jinahjang@postech.ac.kr", "url": "mailto:jinahjang@postech.ac.kr"}
    assert all(k in tbl["data"][0]["fields"] for k in tbl["data"][0]["link"])  # link 컬럼은 fields 에 있어야 한다
    card = out["email_cards"]["data"][0]
    assert card["title"] == "name" and card["title"] in card["fields"] and card["rows"][0]["name"] == "장진아"
    assert out["notice"]["type"] == "text" and "content" in out["notice"]["data"][0]
    path = to_xlsx([res], tmp_path / "r.xlsx")
    assert path.exists()
