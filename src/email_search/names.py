"""이름 처리: 같은 사람 판정, 특허청 표기(대문자·성 앞/뒤) → 검색 형태, 한글 → 로마자 후보, 이메일 귀속 규칙."""

from __future__ import annotations

import re
import unicodedata
from itertools import product

# ---- 같은 사람 판정 --------------------------------------------------------------------


def norm_name(name: str) -> str:
    s = unicodedata.normalize("NFKC", name).lower()
    s = re.sub(r"[\-\.‐‑,]", " ", s)
    return " ".join(sorted(t for t in s.split() if t))


def _given_joined(name: str, surname: str) -> str:
    s = re.sub(r"[\-\.‐‑,]", " ", unicodedata.normalize("NFKC", name).lower())
    return "".join(t for t in s.split() if t != surname)


def same_person_name(a: str, b: str) -> bool:
    """'J. W. Park' ↔ 'Jun Woo Park', 'KIM Joung Ho' ↔ 'Joungho Kim'(음절 붙임) 을 같은 사람으로. 공통 완전 단어(성)가 정확히 하나여야 한다."""
    if not a or not b:
        return False
    na, nb = norm_name(a), norm_name(b)
    if na == nb:
        return True
    ta, tb = na.split(), nb.split()
    shared = [t for t in ta if len(t) > 1 and t in tb]
    if len(shared) != 1:
        return False
    surname = shared[0]
    ra = [t for t in ta if t != surname]
    rb = [t for t in tb if t != surname]
    if not ra or not rb:
        return False
    if _given_joined(a, surname) == _given_joined(b, surname):
        return True
    if {t[0] for t in ra} != {t[0] for t in rb}:
        return False
    full_a = {t for t in ra if len(t) > 1}
    full_b = {t for t in rb if len(t) > 1}
    return not (full_a and full_b) or full_a == full_b


# ---- 특허청·서지 표기 → 검색 형태 -------------------------------------------------------------


def latin_name_forms(name: str) -> list[str]:
    """'KIM, Joung Ho' → ['Joung Ho Kim', 'Joungho Kim'] · 'KIM JOUNG HO'(EPO, 성 앞) 와 'SARBAJIT K. RAKSHIT'(USPTO, 성 뒤) 는 두 해석 모두 · 'Joungho Kim' 은 그대로."""
    if not name or not name.isascii():
        return []
    toks = [t for t in re.split(r"[\s,]+", name.strip()) if t]
    if len(toks) < 2:
        return []

    def build(sur: str, given: list[str]) -> list[str]:
        if not any(t.isupper() or t.istitle() for t in toks) or sur.isupper():
            sur = sur.capitalize()
        parts = [p for g in given for p in g.split("-") if p and p.strip(".")]
        spaced = " ".join("-".join(p.capitalize() for p in g.split("-")) if g.isupper() or g.islower() else g for g in given)
        joined = "".join(p.strip(".") for p in parts).capitalize() if len(parts) > 1 else spaced
        out = []
        for f in (f"{spaced} {sur}", f"{joined} {sur}"):
            f = " ".join(f.split())
            if f and f not in out:
                out.append(f)
        return out

    if "," in name:
        orders = [(toks[0], toks[1:])]
    elif all(t.isupper() for t in toks):
        has_initial = any(re.fullmatch(r"[A-Z]\.", t) for t in toks)
        given_first, surname_first = (toks[-1], toks[:-1]), (toks[0], toks[1:])
        orders = [given_first, surname_first] if has_initial else [surname_first, given_first]
    else:
        orders = [(toks[-1], toks[:-1])]
    out: list[str] = []
    for sur, given in orders:
        for f in build(sur, given):
            if f not in out:
                out.append(f)
    return out[:4]


# ---- 한글 → 로마자 후보 -------------------------------------------------------------------

_INITIAL = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
_MEDIAL = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i"]
_FINAL = ["", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "p", "l", "m", "p", "p", "t", "t", "ng", "t", "t", "k", "t", "p", "t"]
_INITIAL_VARIANTS = {"g": ["g", "k"], "d": ["d", "t"], "b": ["b", "p"], "j": ["j", "ch"], "r": ["r", "l"], "s": ["s", "sh"]}
_MEDIAL_VARIANTS = {"eo": ["eo", "u", "ou", "o"], "eu": ["eu", "u"], "u": ["u", "oo", "woo"], "ae": ["ae", "ai"], "yeo": ["yeo", "you", "yu", "yo"], "i": ["i", "ee"], "ui": ["ui", "ee"],
                    "yu": ["yu", "you", "yoo"], "a": ["a", "ah"]}
_FINAL_VARIANTS = {"k": ["k", "g"], "t": ["t"], "p": ["p", "b"], "l": ["l", "r"]}
SURNAMES: dict[str, list[str]] = {
    "김": ["Kim", "Gim"], "이": ["Lee", "Yi", "Rhee", "Li"], "박": ["Park", "Pak", "Bak"], "최": ["Choi", "Choe"], "정": ["Jung", "Jeong", "Chung", "Joung"],
    "강": ["Kang", "Gang"], "조": ["Cho", "Jo", "Joe"], "윤": ["Yoon", "Yun"], "장": ["Jang", "Chang"], "임": ["Lim", "Im", "Rim"], "한": ["Han"], "오": ["Oh", "O"],
    "서": ["Seo", "Suh", "Su"], "신": ["Shin", "Sin"], "권": ["Kwon", "Gwon", "Kweon"], "황": ["Hwang", "Whang"], "안": ["Ahn", "An"], "송": ["Song"], "류": ["Ryu", "Yoo", "Ryoo"],
    "전": ["Jeon", "Jun", "Chun", "Jeun"], "홍": ["Hong"], "고": ["Ko", "Go", "Koh"], "문": ["Moon", "Mun"], "양": ["Yang"], "손": ["Son", "Sohn"], "배": ["Bae", "Pae"],
    "백": ["Baek", "Paik", "Back"], "허": ["Heo", "Huh", "Hur"], "유": ["Yoo", "Yu", "You"], "남": ["Nam"], "심": ["Shim", "Sim"], "노": ["Noh", "Roh", "No"], "하": ["Ha"],
    "곽": ["Kwak", "Gwak"], "성": ["Sung", "Seong"], "차": ["Cha"], "주": ["Joo", "Ju", "Chu"], "우": ["Woo", "U"], "구": ["Koo", "Ku", "Gu"], "민": ["Min"], "나": ["Na", "Ra"],
    "진": ["Jin", "Chin"], "지": ["Ji", "Chi"], "엄": ["Um", "Eom", "Uhm"], "채": ["Chae"], "원": ["Won"], "천": ["Chun", "Cheon"], "방": ["Bang", "Pang"], "공": ["Kong", "Gong"],
    "현": ["Hyun", "Hyeon"], "함": ["Ham"], "변": ["Byun", "Byeon"], "염": ["Yeom", "Yum"], "여": ["Yeo", "Yuh"], "추": ["Choo", "Chu"], "도": ["Do", "Doh"], "소": ["So", "Soh"],
    "석": ["Seok", "Suk"], "선": ["Sun", "Seon"], "설": ["Seol", "Sul"], "마": ["Ma"], "길": ["Gil", "Kil"], "연": ["Yeon", "Youn"], "위": ["Wee", "Wi"], "표": ["Pyo"],
    "명": ["Myung", "Myeong"], "기": ["Ki", "Gi"], "반": ["Ban", "Bahn"], "왕": ["Wang"], "금": ["Keum", "Geum"], "옥": ["Ok"], "육": ["Yook", "Yuk"], "인": ["In"],
    "맹": ["Maeng"], "제": ["Je"], "모": ["Mo"], "탁": ["Tak"], "국": ["Kook", "Guk"], "어": ["Eo", "Uh"], "은": ["Eun"], "편": ["Pyun", "Pyeon"], "용": ["Yong"],
    "예": ["Ye"], "봉": ["Bong"], "사": ["Sa"], "부": ["Boo", "Bu"], "감": ["Kam", "Gam"], "복": ["Bok"], "빙": ["Bing"], "태": ["Tae"], "피": ["Pi"],
}


def _decompose(ch: str) -> tuple[str, str, str] | None:
    code = ord(ch) - 0xAC00
    if not 0 <= code < 11172:
        return None
    return _INITIAL[code // 588], _MEDIAL[(code % 588) // 28], _FINAL[code % 28]


def syllable_spellings(ch: str, max_n: int = 4) -> list[str]:
    parts = _decompose(ch)
    if parts is None:
        return [ch]
    ini, med, fin = parts
    out: list[str] = []
    for i, m, f in product(_INITIAL_VARIANTS.get(ini, [ini]), _MEDIAL_VARIANTS.get(med, [med]), _FINAL_VARIANTS.get(fin, [fin])):
        s = f"{i}{m}{f}"
        if s not in out:
            out.append(s)
        if len(out) >= max_n:
            break
    return out


def romanization_candidates(korean_name: str, max_candidates: int = 16) -> list[str]:
    """'조동우' → ['Dongu Cho', 'Dong U Cho', 'Dongoo Cho', …, 'Dongwoo Cho', 'Dong Woo Cho' …]. 표준 조합부터. 후보는 추측이므로 소속 일치 저자가 실제로 있을 때만 쓴다."""
    name = korean_name.strip().replace(" ", "")
    if not (2 <= len(name) <= 4) or any(_decompose(c) is None for c in name):
        return []
    sur, given = name[0], name[1:]
    surnames = SURNAMES.get(sur) or [syllable_spellings(sur, 1)[0].capitalize()]
    given_sets = [syllable_spellings(c, 4) for c in given]
    out: list[str] = []
    combos = sorted(product(*given_sets), key=lambda combo: sum(given_sets[i].index(s) for i, s in enumerate(combo)))
    for combo in combos:
        joined = "".join(combo).capitalize()
        spaced = " ".join(c.capitalize() for c in combo)
        for form in (joined, spaced) if len(combo) > 1 else (joined,):
            cand = f"{form} {surnames[0]}"
            if cand not in out:
                out.append(cand)
            if len(out) >= max_candidates:
                return out
    for s in surnames[1:]:
        cand = f"{''.join(g[0] for g in given_sets).capitalize()} {s}"
        if cand not in out:
            out.append(cand)
        if len(out) >= max_candidates:
            break
    return out


# ---- 이메일 귀속 -------------------------------------------------------------------------

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
GENERIC_LOCALPART = re.compile(r"^(info|contact|contactus|inquir|enquir|sales|pr|press|ir|hr|recruit|career|office|admin|webmaster|help|support|biz|business|editor|editorial|journal|permissions|privacy|legal|marketing|service|services|customer|abuse|postmaster|noreply|no-reply|donotreply|example|test)", re.I)
PERSONAL_MAIL = re.compile(r"(gmail|naver|daum|hanmail|kakao|outlook|hotmail|yahoo|proton|qq|163|126|live|icloud|nate)\.", re.I)


def deobfuscate(text: str) -> str:
    t = text.replace("%40", "@").replace("&#64;", "@").replace("&#46;", ".")
    t = re.sub(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*", "@", t, flags=re.I)
    t = re.sub(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*", ".", t, flags=re.I)
    t = re.sub(r"(?<=[A-Za-z0-9])\s+AT\s+(?=[A-Za-z0-9])", "@", t)
    t = re.sub(r"(?<=[A-Za-z0-9])\s+DOT\s+(?=[A-Za-z]{2,})", ".", t)
    return t


def extract_emails(text: str) -> list[str]:
    found: list[str] = []
    for m in EMAIL_RE.findall(deobfuscate(text)):
        e = m.strip(".").lower()
        local = e.split("@")[0]
        if GENERIC_LOCALPART.match(local) or re.search(r"\.(png|jpg|jpeg|gif|svg|js|css|webp)$", e):
            continue
        if e not in found:
            found.append(e)
    return found


def name_tokens(names: list[str]) -> list[str]:
    toks: list[str] = []
    for n in names:
        if not n or not n.isascii():
            continue
        for t in re.split(r"[\s,.\-]+", n.lower()):
            if len(t) >= 3 and t.isalpha() and t not in toks:
                toks.append(t)
    return toks


def attributed_to(email: str, names: list[str], context: str = "") -> str | None:
    """이메일이 이 사람의 것이라고 볼 근거. ① 계정에 이름 조각(4자 이상) ② 성 + 이름 이니셜 ③ 원문에서 이름 바로 뒤(160자, 사이에 '@'·다른 사람 이름 없음). 없으면 None.
    한글 이름만으로는 귀속할 수 없다 — 로마자 표기가 있어야 한다."""
    local = email.split("@")[0].lower()
    local_clean = re.sub(r"[._\-]", "", local)
    toks = name_tokens(names)
    for t in toks:
        if len(t) >= 4 and t in local_clean:
            return f"이메일 계정에 이름 '{t}' 포함"
    for n in names:
        if not n or not n.isascii():
            continue
        parts = [t for t in re.split(r"[\s,.\-]+", n.lower()) if t.isalpha()]
        if len(parts) < 2:
            continue
        for surname in parts:
            if len(surname) < 3 or surname not in local_clean:
                continue
            initials = "".join(t[0] for t in parts if t != surname)
            rest = local_clean.replace(surname, "", 1)
            if initials and (rest == initials or rest.startswith(initials) or rest.endswith(initials) or (len(initials) >= 2 and initials in rest)):
                return f"이메일 계정에 성 '{surname}'+이니셜 '{initials}' 포함"
    if context:
        low = context.lower()
        cand_names = [n.lower() for n in names if n and len(n) >= 3] + [t for t in toks if len(t) >= 4]
        other_name = re.compile(r"\b[A-Z][a-z]+(?:[ \-][A-Z]\.?[a-z]*)+\b")
        start = 0
        while True:
            i = low.find(email.lower(), start)
            if i < 0:
                break
            w0 = max(0, i - 160)
            before, before_orig = low[w0:i], context[w0:i]
            for n in cand_names:
                j = before.rfind(n)
                if j < 0 or "@" in before[j + len(n):]:
                    continue
                between = before_orig[j + len(n):]
                if any(not any(_safe_same(m.group(0), o) for o in names if o) for m in other_name.finditer(between)):
                    continue
                return f"원문에서 이름 '{n}' 바로 뒤"
            start = i + 1
    return None


def _safe_same(a: str, b: str) -> bool:
    try:
        return same_person_name(a, b)
    except Exception:  # noqa: BLE001
        return False


def snippet(text: str, needle: str, width: int = 70) -> str:
    i = text.lower().find(needle.lower())
    if i < 0:
        return ""
    s = re.sub(r"<[^>]+>", " ", text[max(0, i - width): i + len(needle) + width])
    return re.sub(r"\s+", " ", s).strip()
