from email_search.jats import parse_jats_emails
from email_search.names import attributed_to, latin_name_forms, romanization_candidates, same_person_name
from email_search.orgs import domain_matches, expand_abbreviations, same_org, same_org_tokens


def test_name_forms_and_matching():
    assert latin_name_forms("KIM, Joung Ho") == ["Joung Ho Kim", "Joungho Kim"]
    assert latin_name_forms("SARBAJIT K. RAKSHIT")[0] == "Sarbajit K. Rakshit"  # USPTO 식: 이니셜이 있으면 성 뒤 해석 먼저
    assert "Kim Joung Ho" in latin_name_forms("KIM JOUNG HO") and latin_name_forms("KIM JOUNG HO")[0] == "Joung Ho Kim"  # EPO 식
    assert same_person_name("KIM Joung Ho", "Joungho Kim") and same_person_name("J. W. Park", "Jun Woo Park")
    assert not same_person_name("Joungho Kim", "Kiyeong Kim")
    assert "Dongwoo Cho" in romanization_candidates("조동우") and "Jinah Jang" in romanization_candidates("장진아")


def test_attribution_rules():
    names = ["Joungho Kim", "KIM Joung Ho"]
    assert attributed_to("joungho@kaist.ac.kr", names) and attributed_to("jhkim@kaist.ac.kr", names)
    assert attributed_to("lab@kaist.ac.kr", names) is None
    assert attributed_to("lab@kaist.ac.kr", names, "Joungho Kim (corresponding) lab@kaist.ac.kr")
    assert attributed_to("kky@kaist.ac.kr", names, "Joungho Kim, Kiyeong Kim kky@kaist.ac.kr") is None  # 사이에 다른 사람 이름
    assert attributed_to("jhkim@kaist.ac.kr", ["김정호"]) is None  # 한글만으로는 귀속 불가


def test_org_matching():
    assert same_org_tokens("KOREA ADVANCED INST SCI & TECH", "Korea Advanced Institute of Science and Technology")
    assert same_org("HANON SYSTEMS CO LTD", "Hanon Systems (South Korea)") and same_org("Arkema", "Arkema (France)")
    assert same_org("HEWLETT-PACKARD DEVELOPMENT", "Hewlett-Packard (United States)")
    assert not same_org_tokens("Korea Advanced Institute of Science and Technology", "Korea Institute of Science and Technology")
    assert same_org("카이스트", "KAIST") and same_org("포항공과대학교", "POSTECH ACAD IND FOUND")
    assert not same_org("Seoul National University", "Seoul National University Hospital", strict=True)
    assert expand_abbreviations("Univ. of Tokyo") == "University of Tokyo"
    assert domain_matches("ee.kaist.ac.kr", "kaist.ac.kr") and domain_matches("is.mpg.de", "tue.mpg.de") and not domain_matches("snu.ac.kr", "kaist.ac.kr")


JATS = """<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta><contrib-group>
<contrib contrib-type="author" corresp="yes"><name><surname>Kim</surname><given-names>Joungho</given-names></name><xref ref-type="corresp" rid="cor1"/></contrib>
<contrib contrib-type="author"><name><surname>Lee</surname><given-names>Chul</given-names></name><email>chlee@kaist.ac.kr</email></contrib>
<contrib contrib-type="editor"><name><surname>Park</surname><given-names>Ed</given-names></name><email>ed@journal.org</email></contrib>
</contrib-group><author-notes><corresp id="cor1"><email xlink:type="simple">joungho@kaist.ac.kr</email></corresp></author-notes></article-meta></front></article>"""


def test_jats_parser_links_email_to_author():
    rec = parse_jats_emails(JATS)
    by = {a["name"]: a for a in rec["authors"]}
    assert by["Joungho Kim"]["emails"] == ["joungho@kaist.ac.kr"] and by["Joungho Kim"]["corresp"]
    assert by["Chul Lee"]["emails"] == ["chlee@kaist.ac.kr"] and "Ed Park" not in by


SHARED = """<article><front><article-meta><contrib-group>
<contrib contrib-type="author" corresp="yes"><name><surname>Choi</surname><given-names>Soon Mo</given-names></name><xref ref-type="corresp" rid="c1"/></contrib>
<contrib contrib-type="author" corresp="yes"><name><surname>Han</surname><given-names>Sung Soo</given-names></name><xref ref-type="corresp" rid="c1"/></contrib>
</contrib-group><author-notes><corresp id="c1">Correspondence: <email>smchoi@ynu.ac.kr</email> (S.M.C.); <email>sshan@yu.ac.kr</email> (S.S.H.)</corresp></author-notes></article-meta></front></article>"""


def test_jats_shared_corresp_is_split_by_name_trace():
    """교신저자 둘이 <corresp> 하나를 공유하면(실측 PMC12385360) 계정에 이름 흔적(성+이니셜)이 있는 이메일만 각 저자에게."""
    by = {a["name"]: a for a in parse_jats_emails(SHARED)["authors"]}
    assert by["Sung Soo Han"]["emails"] == ["sshan@yu.ac.kr"] and by["Soon Mo Choi"]["emails"] == ["smchoi@ynu.ac.kr"]
