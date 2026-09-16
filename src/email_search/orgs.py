"""기관명 대조: 약어·법인형·어순·국가 장식이 달라도 같은 기관으로 보는 규칙, 별칭 등록소, 이메일 도메인 ↔ 공식 도메인 대조."""

from __future__ import annotations

import re
import unicodedata

ORG_SUFFIXES = ("주식회사", "(주)", "㈜", "재단법인", "사단법인", "산학협력단", "co., ltd.", "co. ltd", "co.,ltd", "ltd.", "ltd", "inc.", "inc", "corp.", "corporation", "gmbh", "llc", "univ.")

_ALIAS_GROUPS: list[tuple[str, ...]] = [
    ("KAIST", "카이스트", "한국과학기술원", "Korea Advanced Institute of Science and Technology", "KOREA ADVANCED INST SCI & TECH"),
    ("KIST", "한국과학기술연구원", "Korea Institute of Science and Technology", "KOREA INST SCI & TECH"),
    ("ETRI", "한국전자통신연구원", "Electronics and Telecommunications Research Institute", "ELECTRONICS & TELECOMMUNICATIONS RES INST"),
    ("KERI", "한국전기연구원", "Korea Electrotechnology Research Institute"),
    ("KITECH", "한국생산기술연구원", "Korea Institute of Industrial Technology"),
    ("KRICT", "한국화학연구원", "Korea Research Institute of Chemical Technology"),
    ("KIER", "한국에너지기술연구원", "Korea Institute of Energy Research"),
    ("KIMS", "한국재료연구원", "Korea Institute of Materials Science"),
    ("KETI", "한국전자기술연구원", "Korea Electronics Technology Institute"),
    ("KIMM", "한국기계연구원", "Korea Institute of Machinery and Materials"),
    ("KAERI", "한국원자력연구원", "Korea Atomic Energy Research Institute"),
    ("POSTECH", "포스텍", "포항공과대학교", "포항공대", "Pohang University of Science and Technology", "POSTECH ACAD IND FOUND"),
    ("UNIST", "울산과학기술원", "Ulsan National Institute of Science and Technology"),
    ("GIST", "광주과학기술원", "Gwangju Institute of Science and Technology"),
    ("DGIST", "대구경북과학기술원", "Daegu Gyeongbuk Institute of Science and Technology"),
    ("SNU", "서울대학교", "서울대", "Seoul National University", "SEOUL NAT UNIV R&DB FOUNDATION"),
    ("고려대학교", "고려대", "Korea University"),
    ("연세대학교", "연세대", "Yonsei University"),
    ("SKKU", "성균관대학교", "성균관대", "Sungkyunkwan University"),
    ("한양대학교", "한양대", "Hanyang University"),
    ("영남대학교", "영남대", "Yeungnam University"),
    ("삼성전자", "Samsung Electronics", "SAMSUNG ELECTRONICS CO LTD"),
    ("삼성에스디아이", "삼성SDI", "Samsung SDI", "SAMSUNG SDI CO LTD"),
    ("LG에너지솔루션", "LG Energy Solution", "LG ENERGY SOLUTION LTD"),
    ("현대자동차", "현대차", "Hyundai Motor Company", "Hyundai Motor", "HYUNDAI MOTOR CO LTD"),
    ("SK하이닉스", "SK hynix", "SK HYNIX INC"),
]
_ACRONYM_SKIP = {"of", "and", "the", "for", "de", "&"}
_TOKEN_EXPAND = {
    "inst": "institute", "institut": "institute", "tech": "technology", "technol": "technology", "univ": "university", "sci": "science", "res": "research",
    "corp": "corporation", "elec": "electric", "elect": "electric", "electr": "electric", "electron": "electronics", "ind": "industrial", "indust": "industrial",
    "natl": "national", "nat": "national", "acad": "academy", "found": "foundation", "mfg": "manufacturing", "eng": "engineering", "engng": "engineering",
    "lab": "laboratory", "labs": "laboratory", "laboratories": "laboratory", "dept": "department", "intl": "international", "int": "international",
    "telecom": "telecommunications", "telecommun": "telecommunications", "chem": "chemical", "mech": "mechanical", "med": "medical", "hosp": "hospital",
    "assoc": "association", "soc": "society", "adv": "advanced", "mat": "materials", "mater": "materials", "sys": "systems", "syst": "systems",
    "institutes": "institute", "technologies": "technology", "sciences": "science", "universities": "university", "industries": "industrial", "industry": "industrial",
}
_TOKEN_STOP = {"of", "and", "the", "for", "de", "a", "an", "at", "in", "co", "ltd", "inc", "corp", "corporation", "gmbh", "llc", "plc", "ag", "kk", "sa", "spa", "bv", "nv", "pte", "pty", "limited", "company",
               "주식회사", "주", "유한회사", "재단법인", "사단법인", "산학협력단", "rdb", "r", "d", "b"}
_DECOR = {"south", "north", "korea", "korean", "republic", "japan", "china", "usa", "us", "uk", "germany", "france", "india", "taiwan", "europe", "asia", "global", "international", "group", "holdings", "worldwide",
          "united", "states", "america", "american", "kingdom", "netherlands", "switzerland", "sweden", "italy", "spain", "canada", "australia", "israel", "singapore", "brazil", "mexico", "russia",
          "poland", "austria", "belgium", "denmark", "norway", "finland", "ireland", "development"}
_PUBLIC_SUFFIXES = {"ac.kr", "co.kr", "or.kr", "re.kr", "go.kr", "ne.kr", "pe.kr", "edu", "com", "org", "net", "gov", "ac.uk", "co.uk", "ac.jp", "co.jp", "or.jp", "edu.cn", "com.cn", "ac.cn", "edu.au", "com.au", "edu.tw", "ac.in", "co.in", "de", "fr", "it", "es", "nl", "ch", "at", "be", "se", "dk", "no", "fi", "kr", "jp", "cn", "tw", "uk", "ca", "au", "eu"}


def _norm_raw(name: str) -> str:
    s = unicodedata.normalize("NFKC", name).lower()
    for suf in ORG_SUFFIXES:
        s = s.replace(suf, " ")
    return re.sub(r"[^0-9a-z가-힣]+", "", s)


def _acronym(name: str) -> str:
    words = [w for w in re.split(r"[\s\-]+", unicodedata.normalize("NFKC", name)) if w]
    if len(words) < 2 or not all(w.isascii() for w in words):
        return ""
    letters = [w[0] for w in words if w.lower() not in _ACRONYM_SKIP and w[0].isalpha()]
    return "".join(letters).lower() if len(letters) >= 2 else ""


class AliasRegistry:
    """정규화 이름 → 대표 키. 정적 표 + 실행 중 확인된 표기(ROR·Wikidata·DART). 대표 키는 그룹의 최장 이름."""

    def __init__(self) -> None:
        self._canon: dict[str, str] = {}
        self._acro: dict[str, str] = {}
        self._names: dict[str, list[str]] = {}
        for g in _ALIAS_GROUPS:
            self.register(g)

    def register(self, names: tuple[str, ...] | list[str]) -> None:
        keys = [k for k in (_norm_raw(n) for n in names if n) if k]
        if not keys:
            return
        canon = next((self._canon[k] for k in keys if k in self._canon), max(keys, key=len))
        for k in keys:
            self._canon[k] = canon
        bucket = self._names.setdefault(canon, [])
        for n in names:
            if n and n not in bucket:
                bucket.append(n)
        for n in names:
            a = _acronym(n)
            if len(a) >= 4:
                self._acro.setdefault(a, canon)

    def canonical(self, name: str) -> str:
        k = _norm_raw(name)
        if k in self._canon:
            return self._canon[k]
        a = _acronym(name)
        if len(a) >= 4 and a in self._acro:
            return self._acro[a]
        return k

    def aliases(self, name: str) -> list[str]:
        return list(self._names.get(self.canonical(name), []))


REGISTRY = AliasRegistry()


def org_tokens(name: str) -> frozenset[str]:
    s = unicodedata.normalize("NFKC", name).lower().replace("&", " and ")
    out: set[str] = set()
    for t in re.split(r"[^0-9a-z가-힣]+", s):
        if not t:
            continue
        t = _TOKEN_EXPAND.get(t.rstrip("."), t.rstrip("."))
        if t in _TOKEN_STOP:
            continue
        out.add(t)
    return frozenset(out)


def same_org_tokens(a: str, b: str) -> bool:
    """내용 토큰이 같으면(약어 확장·법인형 제거 뒤) 같은 기관. 국가·법인 장식 토큰만 다른 것도 같다: 'Hanon Systems (South Korea)' = 'HANON SYSTEMS CO LTD'. KAIST ≠ KIST."""
    ta, tb = org_tokens(a), org_tokens(b)
    if not ta or not tb:
        return False
    if ta == tb:
        return len(ta) >= 2
    core, diff = ta & tb, ta ^ tb
    if not core or not diff <= _DECOR:
        return False
    return len(core) >= 2 or all(len(t) >= 4 and t not in _DECOR for t in core)


def same_org(a: str, b: str, strict: bool = False) -> bool:
    """strict=False: 별칭·두문자어·부분 포함(4자 이상)·토큰 규칙. strict=True: 정규화 동일 또는 토큰 규칙만(별칭 **등록**용 — 병원≠대학)."""
    ka, kb = REGISTRY.canonical(a), REGISTRY.canonical(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    if same_org_tokens(a, b):
        return True
    if strict:
        return False
    aa, ab = _acronym(a), _acronym(b)
    if (len(aa) >= 3 and aa == _norm_raw(b)) or (len(ab) >= 3 and ab == _norm_raw(a)):
        return True
    if (len(ka) >= 4 and ka in kb) or (len(kb) >= 4 and kb in ka):
        return True
    return any(same_org_tokens(x, b) for x in REGISTRY.aliases(a) if x != a) or any(same_org_tokens(x, a) for x in REGISTRY.aliases(b) if x != b)


def expand_abbreviations(name: str) -> str:
    """'Univ. of Tokyo' → 'University of Tokyo', 'KOREA ADVANCED INST SCI & TECH' → 'Korea Advanced Institute Science and Technology'. 바뀐 게 없으면 빈 문자열."""
    words = []
    for w in re.split(r"\s+", unicodedata.normalize("NFKC", name).replace("&", " and ").strip()):
        core = w.strip(".,()").lower()
        if not core or core in ("co", "ltd", "inc", "corp", "corporation", "gmbh", "llc", "plc", "limited", "company"):
            continue
        rep = _TOKEN_EXPAND.get(core)
        words.append(rep.capitalize() if rep else (w if not w.isupper() or len(w) <= 3 else w.capitalize()))
    out = " ".join(words)
    return out if out and _norm_raw(out) != _norm_raw(name) else ""


def domain_matches(email_domain: str, official: str) -> bool:
    """같거나 하위(ee.kaist.ac.kr ⊂ kaist.ac.kr)거나 같은 기관 상위 도메인의 형제 서브도메인(tue.mpg.de ↔ is.mpg.de). 공용 접미사 아래 형제는 다른 기관."""
    e, o = email_domain.lower(), official.lower().removeprefix("www.")
    if e == o or e.endswith("." + o):
        return True
    parts = o.split(".")
    if len(parts) >= 3:
        parent = ".".join(parts[1:])
        if parent not in _PUBLIC_SUFFIXES and (e == parent or e.endswith("." + parent)):
            return True
    return False


def host_of(url: str) -> str:
    m = re.match(r"^(?:https?://)?([^/:?#]+)", url.strip(), re.I)
    return (m.group(1).lower().removeprefix("www.") if m else "")
