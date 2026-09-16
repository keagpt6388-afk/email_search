# email_search

**소속 · 이름 · 기술분야**를 입력하면, 신뢰할 수 있는 **공개·공식 출처**에서 그 사람이 스스로 공개한 이메일 주소를 찾아 근거(출처 문서·귀속 이유·도메인 검증)와 함께 돌려주는 도구입니다.
TECH-GPT V2 「응답 표출 규격서 v1.1」 형식(table · card · text · answer)으로 응답하므로 플랫폼의 도구(tool)로 바로 붙일 수 있고, 스프레드시트(xlsx)·CLI 로도 쓸 수 있습니다.

- 돈이 드는 API 를 쓰지 않습니다. 모든 출처는 무료이며 키 없이 동작합니다(키가 있으면 한도가 늘어납니다).
- 스크래핑이 아니라 공식 API 와 공개 문서만 씁니다. 이메일을 추측하거나 조합하지 않습니다.
- 찾은 이메일마다 **어느 문서에 실려 있었는지**, **왜 이 사람의 것이라고 봤는지**, **소속 공식 도메인과 일치하는지**를 함께 보입니다.

## 설치

```bash
uv venv .venv && uv pip install -e ".[dev]" --python .venv/Scripts/python.exe   # Windows
# 또는  pip install -e ".[dev]"
```

Python 3.11+. HTTP API(FastAPI)와 테스트 화면이 함께 설치됩니다.

## 사용

```bash
# 한 사람
email-search find 장진아 포항공과대학교 --field 바이오프린팅 --json out/jang.json --xlsx out/jang.xlsx

# 여러 사람(xlsx/csv: 열 '전문가'·'소속'·[기술분야] — 예시 파일 형식 그대로)
email-search batch examples/sample_input.csv --field "3D 바이오프린팅" --out out/result.xlsx --json out/result.json

# TECH-GPT 도구용 HTTP API
email-search serve --port 8000
#   POST /search        {"name":"장진아","affiliation":"포항공과대학교","field":"바이오프린팅"}
#   POST /search/batch  {"people":[{"name":..,"affiliation":..,"field":..}, ...]}   (최대 50명)
#   GET  /health
```

라이브러리:

```python
from email_search import EmailFinder, Person
from email_search.report import to_techgpt
res = EmailFinder().find(Person(name="장진아", affiliation="포항공과대학교", field="바이오프린팅"))
print(res.best.email if res.best else None, res.log)
payload = to_techgpt([res])   # 응답 표출 규격 JSON
```

### 설정(환경변수, 전부 선택)

| 변수 | 뜻 |
|---|---|
| `EMS_CONTACT_EMAIL` | OpenAlex polite pool·Unpaywall 파라미터·User-Agent 에 들어가는 운영자 이메일 |
| `EMS_OPENALEX_API_KEY` | OpenAlex 무료 키. 일일 예산이 소진되면 자동으로 익명 호출로 전환 |
| `EMS_DART_API_KEY` | OpenDART 무료 키 — 국내 법인의 영문 상호·홈페이지(소속 확장·공식 도메인) |
| `EMS_S2_API_KEY`, `EMS_CORE_API_KEY` | Semantic Scholar·CORE 무료 키(OA PDF 위치 보충 한도 증량) |
| `EMS_PDF_BUDGET` | 사람당 읽어 볼 OA PDF 수(기본 8, 차단된 시도는 절반 비용) |
| `EMS_CACHE_DIR` | 조회 캐시 디렉터리(기본 `cache/`) |

## 응답 형식 (TECH-GPT 응답 표출 규격 v1.1)

최상위 키마다 `{type, data}` 를 붙입니다. 표·카드의 링크 컬럼 값은 `{text, url}` 또는 그 배열이며 `mailto:` 로 이메일을 링크합니다.

| 최상위 키 | type | 내용 |
|---|---|---|
| `answer` | answer | 모델이 읽는 요약("N명 중 M명 발견 … 이름: 이메일 [검증·출처]") |
| `email_table` | table | 전문가별 한 줄: 순위 · 전문가 · 소속 · 기술분야 · 이메일(link) · 검증 · 출처(link) · 귀속 근거 · 식별자(ORCID/OpenAlex/ROR link) · 공식 도메인 · 소속 홈페이지(link) |
| `email_cards` | card | 전문가별 상세(title=name, subtitle=affil): 모든 이메일·검증 설명·귀속 근거·원문 발췌·소속 표기 확장·탐색 로그·소요 시간 |
| `notice` | text | 이용 안내(공개 출처 원칙, 대량 광고 발송 금지, 검증의 뜻) |

```json
{
  "answer": {"type": "answer", "data": "1명 중 이메일을 찾은 사람 1명(검증 1명).\n- 홍길동 (A대학교): gildong.hong@a-univ.ac.kr [검증 · Europe PMC 전문 XML(저자 태그)]"},
  "email_table": {"type": "table", "data": [{"caption": "이메일 검색 결과",
      "fields": {"rank": "순위", "name": "전문가", "affil": "소속", "field": "기술분야", "email": "이메일", "status": "검증", "source": "출처", "attribution": "귀속 근거", "ids": "식별자", "domains": "공식 도메인", "homepage": "소속 홈페이지"},
      "order": ["rank", "name", "affil", "field", "email", "status", "source", "attribution", "ids", "domains", "homepage"],
      "link": ["email", "source", "ids", "homepage"], "highlight": ["email", "status"],
      "note": "검증 = 이메일 도메인이 소속 공식 도메인과 일치(ORCID 본인 레코드는 검증 불필요). 미검증 = 출처 문서에 실린 값 그대로.",
      "rows": [{"rank": 1, "name": "홍길동", "affil": "A대학교", "field": "수소 촉매",
                "email": [{"text": "gildong.hong@a-univ.ac.kr", "url": "mailto:gildong.hong@a-univ.ac.kr"}], "status": "검증됨",
                "source": [{"text": "Europe PMC 전문 XML(저자 태그)", "url": "https://europepmc.org/article/PMC/0000000"}],
                "attribution": "전문 XML 저자 태그 'Gildong Hong' (교신저자)",
                "ids": [{"text": "ORCID 0000-0000-0000-0000", "url": "https://orcid.org/0000-0000-0000-0000"}], "domains": "a-univ.ac.kr", "homepage": [{"text": "ROR", "url": "https://www.a-univ.ac.kr"}]}]}]},
  "email_cards": {"type": "card", "data": [{"caption": "전문가별 상세", "title": "name", "subtitle": "affil", "fields": {"...": "..."}, "order": ["..."], "link": ["emails", "source", "ids", "homepage"], "rows": [{"...": "..."}]}]},
  "notice": {"type": "text", "data": [{"caption": "이용 안내", "content": "이메일은 저자·연구자가 … 공개한 값만 표시하며 …"}]}
}
```

(위 값은 형식 예시이며 실제 인물의 정보가 아닙니다. 저장소에는 실제 이메일 결과를 두지 않습니다.)

xlsx 출력은 예시 파일(순위 · 전문가 · 소속 …)과 같은 표 형태이며 시트 `이메일 검색`(요약) · `상세`(이메일별) · `로그`(단계별) · `안내` 로 나뉩니다.

## HTTP API · 테스트 화면

```bash
email-search serve --port 8000          # 또는  uvicorn email_search.web:app --port 8000
```

| 경로 | 설명 |
|---|---|
| `GET /` | **테스트 화면**. 이름·소속·기술분야를 넣으면 API 를 호출해 좌측에 answer, 우측에 규격대로 그린 표·카드·텍스트(fields·order·link·highlight·format·note 처리), 아래에 원본 JSON 을 보여 줌 |
| `GET /search?name=&affiliation=&field=` | 한 사람. 도구 호출·브라우저 테스트 겸용 |
| `POST /search` | `{"name","affiliation","field"}` |
| `POST /search/batch` | `{"people":[{"name","affiliation","field"}, …]}` 최대 50명 → 표 한 장에 여러 행 |
| `GET /health` | 상태(OpenAlex 키·예산 소진 여부·DART) |
| `GET /docs` | OpenAPI 문서 |

응답은 위 규격 JSON 그대로입니다. 한 사람에 30~90초 걸리므로(공개 출처를 순서대로 조회) 호출 측 타임아웃을 120초 이상으로 두십시오.

## 어떻게 찾나

| 단계 | 내용 | 출처 |
|---|---|---|
| 1 이름 형태 | 로마자 표기(특허청 대문자 표기는 EPO 성-앞 / USPTO 성-뒤 두 해석). 한글만 있으면 로마자 **추정** 후보(RR + 문헌 변형, 표준 조합부터 16개) | — |
| 2 소속 확장 | 별칭 표 → DART 영문 상호·홈페이지 → Wikidata 레이블·공식 웹사이트(P856) → 약어 풀기(INST→institute …) → ROR(대표 이름 일치 우선·소속 매칭) → OpenAlex 기관. 표기는 별칭 등록소에 등록, 홈페이지 호스트는 **공식 도메인** | ROR · Wikidata · OpenDART · OpenAlex |
| 3 저자 연결 | 이름 일치 + 소속(현재·과거) 일치, 기술분야 주제 일치 가점. 유일하면 식별자 확정. 여럿이면 상위 2명, 추정 표기는 압도적 후보(20편 이상·2위의 3배)만 | OpenAlex |
| 4 ORCID | 저자 레코드의 ORCID 또는 공개 검색(유일·소속 일치). 고용 기관이 소속과 전혀 겹치지 않으면 동명이인으로 **보류**. 공개 이메일·연구자 URL·저작물 DOI | ORCID |
| 5 문서 | Europe PMC 서지(저자 소속란) → 전문 JATS XML(저자 태그로 연결된 교신저자 이메일) → bioRxiv/medRxiv JATS → OA PDF(OpenAlex → Unpaywall → Semantic Scholar → CORE; 봇 차단이 드문 호스트 먼저, PDF 대신 온 HTML 본문도 읽음) → 개인 홈페이지 | Europe PMC · bioRxiv · Unpaywall · Semantic Scholar · CORE |
| 6 귀속·검증 | 귀속: 계정에 이름 조각(4자+)·성+이니셜, 원문 근접(160자, 사이에 다른 이메일·이름 없음), JATS 저자 태그. 검증: 소속 공식 도메인 일치(서브·형제 도메인 포함) 또는 ORCID 본인 레코드. 도메인이 없으면 이메일 도메인 홈페이지에서 기관명 확인 | — |

기업 발명자는 논문이 없어 이메일이 나오지 않는 경우가 많습니다. 그때도 회사 공식 도메인·홈페이지는 제시됩니다(간접 창구).

## 한도·주의

- OpenAlex 무료 키에는 **일일 예산**이 있고 IP 기준 익명 예산도 있습니다(UTC 자정 초기화). 대량 실행은 로컬에서, 하루 수백 명 이내로.
- 공용 IP(클라우드) 에서는 출판사 PDF 가 자주 차단(403·봇 페이지)됩니다. 리포지터리·PMC·arXiv 를 먼저 열도록 되어 있습니다.
- 이메일은 저자가 학술 교신 목적으로 공개한 값입니다. 개별 협력 문의에 쓰고 대량 광고 발송에는 쓰지 마십시오(정보통신망법 영리 광고 규제). 이 문구는 응답의 `notice` 로도 나갑니다.

## 개발

```bash
pytest -q
```

MIT License.
