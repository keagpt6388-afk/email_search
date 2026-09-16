# email_search 소스 설명서 (개발자용)

이 문서는 `email_search` 가 **어떤 데이터 출처를 어떤 방식으로 써서** 이메일을 찾는지, 코드가 어떻게 나뉘어 있는지, **무엇을 바꾸려면 어디를 고쳐야 하는지**를 설명합니다. 이 문서만 읽고도 소스를 수정할 수 있도록 판정 규칙의 수치와 그 근거(실측)까지 적었습니다.

---

## 1. 설계 원칙

1. **공개·공식 출처만.** 스크래핑·비공식 API·유료 API 를 쓰지 않는다. 모든 출처는 무료이고 키 없이 동작하며, 키는 한도 증량용(선택)이다.
2. **이메일을 만들지 않는다.** 이름·도메인으로 조합하거나 추측하지 않는다. 저자가 문서(논문·ORCID·본인 홈페이지)에 스스로 적은 값만 돌려준다.
3. **모든 이메일에 근거를 붙인다.** ① 어느 문서에 실려 있었나(출처 URL) ② 왜 이 사람의 것인가(귀속) ③ 소속 공식 도메인과 맞나(검증). 근거 없는 이메일은 버린다.
4. **동명이인이 최대 리스크.** 이름 일치만으로는 절대 연결하지 않고 소속(현재·과거)·기술분야 주제까지 맞아야 한다. 확신이 없으면 "미검증"·"동명이인 가능성 확인" 을 표기한다.
5. **실패를 숨기지 않는다.** 출처 한도·차단·미발견은 탐색 로그에 사유와 함께 남긴다.

---

## 2. 디렉터리 · 모듈

```
src/email_search/
├─ config.py          Settings — 환경변수(EMS_*) 읽기
├─ models.py          Person(입력) · EmailHit(이메일+근거) · SearchResult(사람별 결과·로그)
├─ names.py           이름: 같은 사람 판정, 특허청 표기→검색 형태, 한글→로마자 후보, 이메일 추출·귀속 규칙
├─ orgs.py            기관: 별칭 등록소, 토큰 규칙(약어·법인형·국가 장식), 약어 풀기, 이메일 도메인↔공식 도메인 대조
├─ jats.py            JATS XML(Europe PMC·bioRxiv 전문) → 저자별 이메일
├─ pdf.py             OA PDF/HTML 첫 3쪽에서 이메일, 호스트 우선순위(열림/출판사)
├─ cache.py           SQLite 캐시(JSON 값, TTL, 실패 미캐시 옵션)
├─ finder.py          ★ 파이프라인 본체 EmailFinder.find(Person) → SearchResult
├─ report.py          출력: TECH-GPT 규격 JSON(to_techgpt) · xlsx(to_xlsx) · markdown
├─ web.py             FastAPI(/v1/search, /v1/jobs, 인증·CORS·작업 풀) + test_page.html
├─ cli.py             email-search find / batch / serve
└─ sources/
   ├─ openalex.py     OpenAlex 클라이언트(저자·기관·저작물·OA 위치, 예산 소진 시 익명 전환)
   ├─ registries.py   ROR · ORCID · Wikidata · OpenDART
   └─ fulltext.py     Europe PMC(서지·JATS) · bioRxiv · Unpaywall · Semantic Scholar · CORE
tests/                단위(names/orgs/jats) · 파이프라인 통합(모의 서버) · API
docs/                 API.md(호출자용) · ARCHITECTURE.md(이 문서)
```

의존 방향: `finder` → `sources/*`, `names`, `orgs`, `jats`, `pdf`, `cache`. `report` 는 `models` 만 본다. `web`/`cli` 는 `finder`+`report` 만 쓴다. `sources/*` 는 서로를 모른다.

---

## 3. 데이터 출처와 활용 방식

| 출처 | 무엇을 얻나 | 어디서 쓰나 | 한도·주의 |
|---|---|---|---|
| **OpenAlex** `api.openalex.org` | 저자 검색(`/authors?search=`: 이름·별칭·현재 소속·과거 소속 이력·저작물 수·주제), 기관 검색(`/institutions`: 대체 표기·ROR·홈페이지), 저자의 OA 저작물(`/works?filter=authorships.author.id:…,is_oa:true`: PDF 주소·랜딩 페이지), 저작물 OA 위치 | 저자 연결(3단계), 소속 확장, OA PDF 목록 | 무료 키에 **일일 예산(USD)** 이 있고 IP 익명 예산도 있다. 429 `Insufficient budget` 을 받으면 키·mailto 를 빼고 완전 익명으로 재시도하고 UTC 자정까지 키를 쓰지 않는다(`OpenAlex.key_exhausted_until`). `search` 는 어간 일치라 정확 검색이 아니다 |
| **ORCID** `pub.orcid.org/v3.0` | 공개 검색(`expanded-search`: 이름·소속), `person`(공개 이메일·연구자 URL·자기소개), `employments`(고용 기관·ROR), `works`(DOI) | ORCID 확보(4단계), 이메일·홈페이지·고용 도메인·저작물 | 공개 범위가 "모두" 인 이메일만 온다. 대부분 비공개. 고용 기관이 소속과 전혀 겹치지 않으면 동명이인으로 **보류** |
| **Europe PMC** `ebi.ac.uk/europepmc/webservices/rest` | `search?query=DOI:` (PMID·PMCID·OA 여부·저자별 소속 문자열 — 생의학은 "Electronic address: …" 로 이메일 포함), `/{PMCID}/fullTextXML` (JATS 전문) | 5단계 문서 경로 | 공개 한도 없음(공정 이용). 전문 XML 은 OA 논문만 |
| **bioRxiv / medRxiv** `api.biorxiv.org/details/{server}/{doi}` | 프리프린트 상세 → `jatsxml` 주소 → JATS | 10.1101/ DOI | 한도 명시 없음 |
| **ROR** `api.ror.org/v2/organizations` | 기관 검색(`?query=`), 소속 문자열 매칭(`?affiliation=`, `chosen` 만 인정), 레코드(정식명·별칭·두문자어·타 언어 라벨·웹사이트·domains) | 소속 확장, 공식 도메인 | IP 당 5분 2,000건. 검색 결과 1위가 하위 조직(병원·학과)일 수 있어 **대표 이름 일치 우선** |
| **Wikidata** `wikidata.org/w/api.php` | `wbsearchentities`(한글→영문 레이블, 설명), `wbgetentities props=claims`(P856 공식 웹사이트) | 소속 확장(표기·홈페이지) | 보조 출처(근거로 쓰지 않음). 기관 설명 단서(company·university…)가 있는 항목만, 영문 소속명은 토큰 규칙으로 같은 기관일 때만, 한글 소속명은 검색이 일치시킨 한글 표기가 소속명과 같을 때만 |
| **OpenDART** `opendart.fss.or.kr/api` (키 선택) | `corpCode.xml`(기업 고유번호 12만 건, zip) → `company.json`(영문 상호 `corp_name_eng`, 홈페이지 `hm_url`) | 국내 법인 소속 확장·공식 도메인 | 12만 건 XML 은 `iterparse` 로 스트리밍 파싱(전체 적재 시 512MB 컨테이너가 죽었던 실측). 30일 파일 캐시 |
| **Unpaywall** `api.unpaywall.org/v2/{doi}?email=` | OA PDF 위치 보충 | OpenAlex 에 PDF 주소가 없을 때 | 이메일 파라미터 필요(`EMS_CONTACT_EMAIL`) |
| **Semantic Scholar** `api.semanticscholar.org/graph/v1/paper/DOI:` | `openAccessPdf.url` | Unpaywall 도 없을 때 | 익명 공유 1,000 RPS(혼잡 시 throttle), 키 1 RPS |
| **CORE** `api.core.ac.uk/v3/search/works?q=doi:` | 리포지터리 `downloadUrl` | 마지막 PDF 보충 | 익명 `x-ratelimit-limit: 10`(짧은 창). 논문당 1회 |
| 개인 홈페이지 | ORCID 연구자 URL 의 페이지 본문(`mailto:`·텍스트) | 5c 단계 | 본인 페이지라도 대표·부서 계정(info·enquiry…)은 이름 근거 없이는 안 붙임 |
| 이메일 도메인 홈페이지 | `https://<도메인>/` 제목·본문에 기관명이 있는가 | 공식 도메인을 어디서도 못 얻었을 때의 마지막 검증 | 개인 메일 도메인은 시도 안 함 |

**쓰지 않는 것과 이유**: Google Scholar(API 없음·스크래핑 약관 위반), LinkedIn·ResearchGate(약관), Scopus·Web of Science(유료), 출판사 API(비상업 약관 확인 필요 — 보류), 특허 대리인 연락처(사용자 결정으로 제외), NTIS·KRI(연구자 이메일 미노출), WHOIS(등록자 비공개).

---

## 4. 파이프라인 (finder.py `EmailFinder.find`)

각 단계는 결과를 `SearchResult.log` 에 한 줄씩 남긴다. 단계 번호는 소스 주석과 같다.

### 1) 이름 형태 — `names.latin_name_forms`, `names.romanization_candidates`
- 로마자 이름이 있으면 검색 형태를 만든다. `KIM, Joung Ho` → `Joung Ho Kim`, `Joungho Kim`(음절 붙임 — 문헌 표기가 갈리므로 둘 다).
- **대문자만인 표기는 특허청마다 순서가 다르다**: EPO(epodoc) `KIM JOUNG HO` 는 성이 앞, USPTO `SARBAJIT K. RAKSHIT` 은 성이 뒤 → 두 해석을 모두 만들고, 이니셜 마침표가 있으면 USPTO 식을 먼저 둔다(실측: 'K. Rakshit Sarbajit' 로 잘못 뒤집혔던 사례).
- 로마자가 없고 한글이면 **로마자 추정** 후보 16개(국어 로마자 표기법 + 문헌 변형: 정→Jeong/Jung/Joung/Jong, 우→u/oo/woo, 유→yu/you/yoo, 아→a/ah …, 성은 관용 표기 사전). 표준 조합부터 정렬. 후보는 추측이므로 **소속 일치 저자가 실제로 있을 때만** 채택하고 로그에 '로마자 추정' 을 남긴다.

### 2) 소속 확장 — `finder.expand_affiliation`, `orgs.py`
씨앗(검색어)을 늘리며 표기를 모은다: 원문 → DART 영문 상호(`한온시스템` → Hanon Systems) → Wikidata 레이블(기관 설명 항목만) → 약어 풀기(`Univ. of Tokyo` → University of Tokyo) → ROR 검색(대표 이름 일치 우선 → 별칭 일치 → `?affiliation=` chosen) → OpenAlex 기관.
- 모은 표기는 `orgs.REGISTRY` (별칭 등록소)에 등록되어 이후 `same_org` 가 모두 인식한다. 3자 이하 영문 약어(UT·KU)는 등록하지 않는다(다른 기관 두문자어와 겹침).
- **등록용 대조는 엄격**(`same_org(strict=True)`: 정규화 동일 또는 토큰 규칙)이다. 부분 포함 규칙을 쓰면 'University of Tokyo Hospital' 이 대학 별칭으로 들어간다.
- 공식 도메인 = ROR `domains` + 각 출처의 공식 웹사이트 호스트(DART `hm_url`, Wikidata P856, OpenAlex `homepage_url`, ROR `links.website`). ROR 에 도메인이 없는 기업(현대모비스 등)도 이렇게 채운다.

### 3) 저자 연결 — `finder.link_authors`
- 각 이름 형태로 OpenAlex 저자 검색(인쇄된 표기 최대 4개, 추정 표기 최대 16개). 후보 조건: `same_person_name(형태, display_name 또는 별칭)` **그리고** 소속 일치(`same_org` 로 현재 소속 `last_known_institutions` 또는 과거 소속 `affiliations`).
- 정렬: 현재 소속 일치 → 기술분야 주제 일치(입력 `field` 의 3자 이상 토큰이 저자 `topics` 에 포함) → 저작물 수.
- **유일 판정**(식별자 `openalex`·`orcid` 를 결과에 기록): 현재 소속 → 주제 순으로 좁혀 정확히 하나 남을 때만.
- 유일하지 않으면: 인쇄된 표기는 상위 `EMS_AUTHOR_CANDIDATES`(기본 2)명의 논문을 훑고 라벨에 '동명이인 가능성 확인' 을 붙인다(OpenAlex 가 같은 사람을 여러 레코드로 갈라 두는 일이 잦음: 'Joungho Kim' 715편·'Joung Ho Kim' 2편).
- **로마자 추정 표기**는 더 엄격: 유일하거나, **압도적 후보**(저작물 20편 이상이고 2위의 3배 이상, 또는 상위 둘이 같은 표기의 분리 레코드)만 훑는다. 그때 그 레코드의 표기를 이름 목록에 더해 귀속 규칙에 쓴다(한글 이름만으로는 이메일 계정을 대조할 수 없기 때문). 비슷한 규모의 후보가 여럿이면 논문을 열지 않는다(흔한 이름은 대부분 동명이인).

### 4) ORCID — `sources.registries.Orcid`, `finder.search_orcid`
- 저자 레코드에 ORCID 가 있으면 그것, 없으면 공개 검색(`given-names`·`family-name`)에서 이름 일치 후보가 유일하거나 소속 일치 후보가 유일할 때만.
- **동명이인 보류**: 고용 기관 목록이 있고 그중 하나도 소속과 `same_org` 가 아니면 이 레코드를 쓰지 않고 로그만 남긴다(YONG CHEN · USC 는 고용에 USC→HKUST 이직 기록이 있어 통과 — 현재 주소 yongchen@ust.hk 가 나온 사례).
- 공개 이메일(도메인 검증 없이 인정), 연구자 URL(개인 홈페이지 후보), 고용→ROR 도메인 추가, 저작물 DOI(최대 15).

### 5) 문서 경로
- **저작물 목록**: 연결된 저자들의 OA 저작물(최신순 25건, PDF 주소 포함) + ORCID DOI. 입력 `field` 가 있으면 제목·주제에 그 토큰이 든 논문을 앞에 둔다.
- **5a Europe PMC / bioRxiv** (최대 6개 DOI): 서지의 저자 소속란 이메일(저자 이름과 함께 오므로 귀속 정확) → OA 면 전문 JATS XML → `jats.parse_jats_emails` → 저자 태그로 연결된 이메일(교신저자 `<corresp>` 를 `<xref rid>` 로 연결). 교신저자 둘이 `<corresp>` 하나에 이메일 둘을 적은 경우 계정에 이름 흔적(성+이니셜)이 있는 것만 각 저자에게 준다. bioRxiv DOI(10.1101/)는 상세 API 의 JATS.
- **5b OA PDF**: 문서마다 PDF 주소 1개(OpenAlex → 없으면 Unpaywall → Semantic Scholar → CORE). 주소는 `pdf.host_rank` 로 **봇 차단이 드문 호스트(arXiv·PMC·리포지터리·KoreaScience) 먼저**, 출판사(MDPI·Wiley·Elsevier…) 는 뒤로. 예산 `EMS_PDF_BUDGET`(기본 8)은 '읽은' PDF 기준이며 차단·실패 시도는 0.5 로 계산해 최대 2배까지 더 시도한다. PDF 대신 HTML 이 오면(랜딩·뷰어 페이지) 봇 차단 문구가 없을 때 본문의 이메일을 읽는다. IEEE `stamp.jsp` 래퍼는 안의 PDF 로 한 번 더 들어간다. `{a, b}@dept.edu` 묶음 표기는 펼친다. 첫 3쪽만 읽는다(저자 블록·각주). 검증된 이메일이 2개 나오면 멈춘다.
- **5c 개인 홈페이지**: ORCID 연구자 URL 최대 2장. 이름 귀속이 있거나, 페이지가 공식 도메인이고 계정이 대표·부서 계정이 아닐 때 '본인 홈페이지에 표기'.

### 6) 귀속과 검증 — `names.attributed_to`, `finder._add`
- **귀속**(이 사람의 이메일인가) — 하나라도 있어야 표시:
  1. 계정에 이름 조각 4자 이상(`joungho@`, `jinahjang@`)
  2. 성 + 이름 이니셜(`jhkim@`, `sshan@`, `kim.jh@`) — 표기별로 성을 하나씩 가정
  3. 원문에서 이름 바로 뒤 160자 이내, 사이에 다른 `@` 도 다른 사람 이름(대문자 두 단어)도 없음
  4. JATS 저자 태그 / Europe PMC 저자란 / ORCID 본인 레코드(문서가 이미 저자와 연결해 준 경우)
- **검증**(도메인) — `orgs.domain_matches`: 이메일 도메인이 공식 도메인과 같거나 하위(`ee.kaist.ac.kr` ⊂ `kaist.ac.kr`), 또는 같은 기관 상위 도메인의 형제(`is.mpg.de` ↔ `tue.mpg.de`; 공용 접미사 `ac.kr`·`com` 아래 형제는 제외). 불일치면 "미검증 · 개인 메일" 또는 "미검증 · 소속 공식 도메인과 다름 — 이전 소속·겸직 가능" 으로 **표시는 한다**(숨기지 않음). 공식 도메인을 전혀 못 얻었으면 이메일 도메인의 홈페이지(`https://<도메인>/`, 상위 한 단계까지)에 기관명 4자 이상이 있으면 '도메인 확인' 으로 검증.
- 정렬: 검증 → 귀속 강도(ORCID·저자 태그·이름 조각 > 원문 근접 > 홈페이지 표기) → 이메일. `SearchResult.best` 가 표의 대표 이메일.

### 캐시 — `cache.py`
키 접두어별로 외부 조회 결과를 SQLite 에 저장한다: `aff:v1:`(소속 확장), `oa-authors:`, `oa-works:`, `orcid:`, `orcid-search:`, `epmc:`, `epmc-xml:`, `biorxiv:`, `pdf:`, `pdf-fallback:`, `page:`. 한도 오류처럼 다음에 다시 시도해야 하는 실패는 `cache_none=False` 로 캐시하지 않는다(`oa-authors`, `pdf`). 캐시된 규칙을 바꿨으면 키의 버전(`v1`)을 올려 무효화한다.

---

## 5. 판정 규칙 요약표 (바꿀 때 참고)

| 규칙 | 값 | 위치 | 근거(실측) |
|---|---|---|---|
| 로마자 추정 후보 수 | 16 | `finder.find` | 8개로는 'Dong-Woo Cho' 같은 흔한 표기가 잘렸다 |
| 인쇄 표기 검색 형태 수 | 4 | `link_authors` | 두 해석 × 띄움/붙임 |
| 압도적 후보 | 20편 이상 & 2위의 3배 (또는 같은 표기 분리 레코드) | `finder.find` 3단계 | 장진아 242편 vs 다른 후보 소수 |
| 비유일 후보 훑기 | 상위 2명 | `EMS_AUTHOR_CANDIDATES` | 분리 레코드 대응 |
| Europe PMC 조회 DOI 수 | 6 | 5a | 응답 시간 |
| PDF 예산 | 8 (실패 0.5, 최대 2배 시도) | `EMS_PDF_BUDGET` | 공용 IP 에서 8건 중 7건 차단 실측 |
| 검증 이메일 조기 종료 | 2개 | 5b | 서로 다른 문서에서 두 번 확인되면 충분 |
| 이름 조각 최소 길이 | 4자 | `attributed_to` | 3자('kim')는 흔함 |
| 원문 근접 창 | 160자 | `attributed_to` | 저자 블록 한 줄 |
| 별칭 등록 제외 약어 | 3자 이하 | `expand_affiliation` | 'UT'(도쿄대) ≠ 'UT'(텍사스대) |
| 토큰 규칙 장식 토큰 | 국가·지역·united/states/development… | `orgs._DECOR` | 'Hanon Systems (South Korea)', 'HEWLETT-PACKARD DEVELOPMENT' |
| OpenAlex 재시도 대기 상한 | 12초 | `OpenAlex.get` | 웹 응답 시간 |

---

## 6. 변경 방법 (How-to)

### 6.1 데이터 출처 추가
1. `sources/` 에 함수(또는 클래스)를 만든다. 입력은 `httpx.Client` 와 식별자(DOI·이름), 출력은 **문서 단위**(예: `{"authors":[{"name","emails"}], "url"}`) 또는 PDF 주소 목록. 이메일을 직접 "결정" 하지 말고 문서를 돌려준다 — 귀속·검증은 `finder` 가 한다.
2. `finder.find` 의 알맞은 단계에 호출을 넣고 `self.cache.cached("접두어:키", loader)` 로 감싼다. 한도 오류가 있을 수 있으면 `cache_none=False`.
3. 이메일을 결과에 넣을 때는 반드시 `self._add(res, names, domains, email, source, url, doc_id, attribution, snippet)` 을 거친다(도메인 검증·설명 문구 통일).
4. 새 `source` 코드에 대한 라벨을 `report.SOURCE_LABEL` 에 추가한다(표·카드·xlsx 에 표시).
5. `tests/test_finder.py` 의 모의 서버(`handler`)에 그 출처의 응답을 추가하고 기대 결과를 단언한다. README 3절 표와 이 문서 3절 표에 한도를 적는다.

### 6.2 기관 대조 규칙 바꾸기 (`orgs.py`)
- 특정 기관의 한/영/약어 표기를 고정하려면 `_ALIAS_GROUPS` 에 한 줄 추가(한 튜플 = 같은 기관). 3자 이하 약어는 다른 기관과 겹칠 수 있으니 넣지 않는 편이 안전하다('SDI' 가 ROR 의 Systems Dynamics 와 섞였던 사례).
- 특허청 약어를 더 풀려면 `_TOKEN_EXPAND`(예: `"kk": ""` 는 `_TOKEN_STOP` 쪽). 국가·법인 장식은 `_DECOR`.
- 판정이 너무 느슨/엄격하면 `same_org_tokens` 를 본다: 내용 토큰 집합이 같거나, 서로 다른 토큰이 **장식 토큰만**일 때 같은 기관. 내용 토큰이 하나라도 다르면 다른 기관(KAIST ≠ KIST).
- 별칭 **등록**에는 `strict=True` 를 유지한다. 느슨한 규칙으로 등록하면 하위 조직이 모기관으로 굳어진다.

### 6.3 이름 규칙 바꾸기 (`names.py`)
- 로마자 변형 추가: `_INITIAL_VARIANTS`·`_MEDIAL_VARIANTS`·`_FINAL_VARIANTS`(표준 표기를 첫 항목에), 성은 `SURNAMES`(빈도순). 후보 수를 늘리면 OpenAlex 호출이 그만큼 늘어난다(후보당 1회).
- 특허청 표기 해석 순서는 `latin_name_forms` 의 `orders`.
- 귀속 규칙 추가는 `attributed_to` 에 조건을 더하고 돌려주는 문구를 정한다. 문구는 `finder` 의 정렬(`strength`)과 `report` 표시에 쓰이므로 기존 문구 형식("이메일 계정에 …", "원문에서 …")을 따른다.

### 6.4 출력 컬럼 추가 (`report.py`)
- `to_techgpt`: `rows_table`/`rows_card` 에 키를 추가하고 **같은 키를 `fields`(라벨)와 `order`(순서)에도** 추가한다. 링크 값이면 `{text, url}` 배열로 만들고 `link` 목록에 키를 넣는다(규격 7절). 카드의 `title` 키가 `fields` 에 없으면 카드가 통째로 안 나오므로 주의(규격 3절).
- xlsx 는 `to_xlsx` 의 `head` 와 행 append 를 같이 고친다.
- 테스트 `tests/test_finder.py` 의 규격 형식 단언(link 컬럼이 fields 에 있는지, title 이 fields 에 있는지)이 자동으로 검사한다.

### 6.5 임계값 조정
5절 표의 위치를 고친다. 캐시에 영향이 있는 규칙(소속 확장 결과, JATS 파싱 결과)을 바꿨다면 해당 캐시 키의 버전을 올린다(`aff:v1` → `aff:v2` 등). 로컬에서는 `cache/` 디렉터리를 지워도 된다.

### 6.6 API 바꾸기 (`web.py`)
- 새 엔드포인트는 `/v1/` 아래에 두고 `dependencies=[Depends(require_key)]` 를 붙인다. 오류는 `HTTPException(status, {"code", "message"})` 형식으로.
- 긴 작업은 `_pool`(스레드 풀) 을 쓴다. 작업 상태는 `_jobs` 딕셔너리(인메모리)이며 프로세스가 재시작되면 사라진다 — 영속이 필요하면 `cache.Cache` 나 외부 큐로 바꾼다.
- 테스트 화면(`test_page.html`)은 규격 렌더러를 포함하므로 응답 형식을 바꾸면 화면에서 바로 확인한다.

### 6.7 테스트 · 실측
```bash
pytest -q                                  # 모의 서버 기반, 네트워크 없음
email-search find 장진아 포항공과대학교 --field 바이오프린팅   # 실제 출처 호출(로컬에서)
```
실측은 **로컬**에서 한다. 배포 서버(공용 IP)에서 대량 실행하면 OpenAlex 익명 예산과 출판사 차단이 함께 소진된다. 실측 결과 파일(xlsx·json)은 실제 개인 이메일을 담으므로 저장소에 넣지 않는다(`.gitignore` 에 등록됨).

---

## 7. 알려진 한계

- 기업 연구자(특허 발명자)는 논문·ORCID 가 없어 이메일이 나오지 않는 경우가 많다. 회사 공식 도메인·홈페이지만 제시된다. (대안이던 특허 대리인 연락처·출판사 API 는 채택하지 않았다.)
- 출판사 PDF 는 공용 IP 에서 대부분 차단된다. 리포지터리·PMC·arXiv 가 없으면 못 읽는다.
- 로마자 특이 표기(Kunyoo Shin, Hyun-Wook Kang)는 후보 16개 밖일 수 있다.
- 이직한 사람은 현재 소속 이메일이 나올 수 있다(ORCID 고용 기록으로 같은 사람임은 확인). 응답에 "미검증 · 이전 소속·겸직 가능" 또는 ORCID 고용 로그로 드러난다.
- OpenAlex 는 같은 사람을 여러 레코드로 가르거나(분리) 동명이인을 합치기도 한다(병합). 분리는 상위 2명 훑기로, 병합은 소속·주제 일치와 ORCID 고용 대조로 완화한다.
- 작업 상태(`/v1/jobs`)는 인메모리라 재시작 시 사라진다.

---

## 8. 용어

- **귀속(attribution)**: 이메일이 그 사람의 것이라고 볼 근거.
- **검증(verification)**: 이메일 도메인이 소속 공식 도메인과 일치.
- **공식 도메인**: ROR·DART·Wikidata·OpenAlex 기관 레코드가 가리키는 홈페이지의 호스트.
- **인쇄된 표기 / 추정 표기**: 문서(공보·서지)에 실제 적힌 로마자 이름 / 한글에서 규칙으로 만든 로마자 후보.
- **OA**: Open Access. 누구나 읽을 수 있게 공개된 전문.
- **JATS**: 학술 논문 XML 표준. 저자·교신저자·이메일이 태그로 구조화되어 있다.
