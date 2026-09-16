# email_search API 설명서

버전 0.2.0 · 기준 URL `https://<호스트>` · 모든 요청·응답은 UTF-8 JSON.

이 API 는 **이름 · 소속 · 기술분야**를 받아 공개·공식 출처에서 그 사람이 스스로 공개한 이메일을 찾고, 결과를 TECH-GPT V2 **「응답 표출 규격서 v1.1」** 형식으로 돌려줍니다. 플랫폼은 응답을 그대로 우측 패널(표·카드·텍스트)과 답변 본문(answer)에 표출할 수 있습니다.

## 1. 빠른 시작

```bash
# 한 사람 (GET)
curl "https://<호스트>/v1/search?name=%EC%9E%A5%EC%A7%84%EC%95%84&affiliation=%ED%8F%AC%ED%95%AD%EA%B3%B5%EA%B3%BC%EB%8C%80%ED%95%99%EA%B5%90&field=3D%20%EB%B0%94%EC%9D%B4%EC%98%A4%ED%94%84%EB%A6%B0%ED%85%85" -H "X-API-Key: <키>"

# 한 사람 (POST)
curl -X POST https://<호스트>/v1/search -H "Content-Type: application/json" -H "X-API-Key: <키>" \
  -d '{"name":"장진아","affiliation":"포항공과대학교","field":"3D 바이오프린팅"}'

# 여러 사람은 비동기 작업으로
curl -X POST https://<호스트>/v1/jobs -H "Content-Type: application/json" -H "X-API-Key: <키>" \
  -d '{"people":[{"name":"장진아","affiliation":"포항공과대학교","field":"3D 바이오프린팅"},{"name":"YONG CHEN","affiliation":"UNIVERSITY OF SOUTHERN CALIFORNIA"}]}'
# → {"job_id":"…","status":"queued","status_url":"/v1/jobs/…","estimated_seconds":120}
curl https://<호스트>/v1/jobs/<job_id> -H "X-API-Key: <키>"
```

한 사람 검색은 **30~90초** 걸립니다(OpenAlex·ORCID·Europe PMC·PDF 를 순서대로 조회). 동기 호출은 타임아웃을 **120초 이상**으로 두고, 2명 이상이면 `/v1/jobs` 를 쓰십시오.

## 2. 인증 · CORS · 한도

| 항목 | 내용 |
|---|---|
| 인증 | 서버에 `EMS_API_KEY` 가 설정된 경우 모든 `/v1/*` 요청에 `X-API-Key: <키>` 헤더 필수. 없으면 `401 {"error":{"code":"unauthorized"}}`. 테스트 화면(`GET /`)은 열려 있고, 화면 안에서 키를 입력해 호출합니다 |
| CORS | `EMS_CORS_ORIGINS` (쉼표 구분, 기본 `*`) |
| 동시성 | `EMS_WORKERS`(기본 2) 개의 작업자가 검색을 처리. 동기·비동기 요청이 같은 풀을 씁니다. 외부 출처 한도(OpenAlex 일일 예산, CORE 분당 10회) 때문에 2~4 를 권장 |
| 배치 상한 | 한 요청 최대 50명 (`422 too_many`) |
| 결과 보관 | 완료된 작업은 `EMS_JOB_TTL`(기본 3600초) 뒤 삭제 |
| 응답 헤더 | `X-Request-ID`(요청 추적, 보낸 값이 있으면 그대로), `X-Elapsed-Seconds` |

## 3. 엔드포인트

### 3.1 `GET /v1/health`
상태. 인증 불필요.
```json
{"status":"ok","version":"0.2.0","auth":true,"workers":2,"jobs":{"total":1,"running":0,"queued":0},
 "sources":{"openalex_key":true,"openalex_key_exhausted":false,"dart":true,"s2_key":false,"core_key":false}}
```
`openalex_key_exhausted: true` 면 그날(UTC 자정까지) OpenAlex 를 익명으로 호출하고 있어 결과가 줄 수 있습니다.

### 3.2 `GET /v1/search` · `POST /v1/search` — 한 사람(동기)

요청(POST 본문 / GET 쿼리):

| 필드 | 필수 | 설명 |
|---|---|---|
| `name` | ✓ | 이름. 한글(`장진아`), 로마자(`Jinah Jang`), 특허청 대문자 표기(`KIM JOUNG HO`, `SARBAJIT K. RAKSHIT`) 모두 가능 |
| `affiliation` | ✓ | 소속. 한글·영문·약어·특허청 표기(`KOREA ADVANCED INST SCI & TECH`) 모두 가능 |
| `field` | | 기술분야. 동명이인 판별(OpenAlex 주제 일치)과 논문 우선순위에 쓰임 |
| `name_variants` | | 추가로 아는 표기 목록(예: 공보 영문 표기) — POST 만 |

응답: 4절의 규격 JSON(`answer`·`email_table`·`email_cards`·`notice`). 이메일을 못 찾아도 `200` 이며 표의 `status` 가 `미발견` 이고 공식 도메인·홈페이지가 채워집니다.

### 3.3 `POST /v1/search/batch` — 여러 사람(동기)
`{"people":[{"name","affiliation","field"}, …]}` 최대 50명. 응답은 표 한 장에 여러 행. 사람 수 × 최대 90초가 걸리므로 5명 이상이면 3.4 를 권장.

### 3.4 `POST /v1/jobs` → `GET /v1/jobs/{job_id}` — 비동기
등록: `202 {"job_id","status":"queued","total","status_url","estimated_seconds"}`
조회:
```json
{"job_id":"…","status":"running","progress":{"done":1,"total":2},"created_at":…,"started_at":…,"elapsed_seconds":48.2,
 "people":[{"name":"…","affiliation":"…","field":"…"}]}
```
`status` 는 `queued → running → done | error`. `done` 이면 `result` 에 규격 JSON 이 들어 있습니다. `error` 여도 그때까지의 결과가 `result` 에 있을 수 있습니다. `DELETE /v1/jobs/{job_id}` 로 삭제. 폴링 간격은 10초 이상을 권장합니다.

### 3.5 별칭
`/search`, `/search/batch`, `/health` 는 `/v1/…` 와 같습니다(초기 연동 호환). `GET /docs` 에서 OpenAPI 문서, `GET /` 에서 테스트 화면.

## 4. 응답 형식 (응답 표출 규격 v1.1)

최상위 키마다 `{ "type": ..., "data": ... }`. 키 이름은 소문자. 이 API 는 네 개를 보냅니다.

| 키 | type | 표출 위치 | 내용 |
|---|---|---|---|
| `answer` | `answer` | 답변 본문(모델이 다듬을 수 있음) | "N명 중 M명 발견(검증 K명)" + 사람별 한 줄 |
| `email_table` | `table` | 우측 패널 | 전문가별 한 행 |
| `email_cards` | `card` | 우측 패널 | 전문가별 카드(모든 이메일·검증 설명·귀속 근거·원문 발췌·탐색 로그) |
| `notice` | `text` | 우측 패널 | 이용 안내(공개 출처 원칙·대량 광고 금지·검증의 뜻) |

### 4.1 `email_table`
```json
{"type":"table","data":[{
  "caption":"이메일 검색 결과",
  "fields":{"rank":"순위","name":"전문가","affil":"소속","field":"기술분야","email":"이메일","status":"검증","source":"출처","attribution":"귀속 근거","ids":"식별자","domains":"공식 도메인","homepage":"소속 홈페이지"},
  "order":["rank","name","affil","field","email","status","source","attribution","ids","domains","homepage"],
  "link":["email","source","ids","homepage"],
  "highlight":["email","status"],
  "note":"검증 = 이메일 도메인이 소속 공식 도메인과 일치(ORCID 본인 레코드는 검증 불필요). 미검증 = 출처 문서에 실린 값 그대로.",
  "rows":[{
    "rank":1,"name":"홍길동","affil":"A대학교","field":"수소 촉매",
    "email":[{"text":"gildong.hong@a-univ.ac.kr","url":"mailto:gildong.hong@a-univ.ac.kr"}],
    "status":"검증됨",
    "source":[{"text":"Europe PMC 전문 XML(저자 태그)","url":"https://europepmc.org/article/PMC/0000000"}],
    "attribution":"전문 XML 저자 태그 'Gildong Hong' (교신저자)",
    "ids":[{"text":"ORCID 0000-0000-0000-0000","url":"https://orcid.org/0000-0000-0000-0000"},{"text":"ROR 00abc1234","url":"https://ror.org/00abc1234"}],
    "domains":"a-univ.ac.kr",
    "homepage":[{"text":"a-univ.ac.kr (ROR)","url":"https://www.a-univ.ac.kr"}]
  }]
}]}
```
- `link` 컬럼의 값은 `{text, url}` 배열. 이메일은 `mailto:`, 나머지는 `https:`.
- 미검증 이메일은 `text` 에 ` (미검증)` 이 붙습니다. 여러 이메일이 있으면 배열로 이어져 플랫폼이 ", " 로 붙여 그립니다.
- `status`: `검증됨` | `미검증` | `미발견`.
- 값이 없는 컬럼은 `null`(표는 빈칸, 카드는 줄 생략 — 규격 6절).

### 4.2 `email_cards`
`title: "name"`, `subtitle: "affil"`. 컬럼: `name, affil, field, emails(link), verification, attribution, source(link), snippet, ids(link), affil_names, domains, homepage(link), log, elapsed`. `log` 는 줄바꿈(`\n`)으로 이어진 단계별 기록입니다(마크다운 목록).

### 4.3 `answer` 예
```
2명 중 이메일을 찾은 사람 1명(검증 1명).
- 홍길동 (A대학교): gildong.hong@a-univ.ac.kr [검증 · Europe PMC 전문 XML(저자 태그)]
- 김철수 (B기업): 공개 출처에서 이메일을 찾지 못함 · 공식 도메인 b-corp.com
```

## 5. 오류 형식

```json
{"error":{"code":"invalid_input","message":"각 항목에 name 과 affiliation 이 필요합니다","item":{...}}}
```

| HTTP | code | 뜻 |
|---|---|---|
| 401 | `unauthorized` | `X-API-Key` 없음/불일치 |
| 404 | `not_found` | 작업 없음(보관 기간 지남) |
| 422 | `invalid_input` | 필수 입력 누락·형식 오류 |
| 422 | `too_many` | 50명 초과 |
| 500 | (예외 이름) | 서버 오류. `X-Request-ID` 를 알려 주면 로그에서 추적 |

외부 출처 장애(OpenAlex 한도 등)는 오류가 아니라 **결과 안의 탐색 로그**에 남고(`email_cards.rows[].log`, 예: "OpenAlex 저자 검색 실패 · HTTP 429 (일일 예산 소진 — UTC 자정 초기화)"), 나머지 출처로 계속 진행합니다.

## 6. 검증·귀속의 뜻 (표시 값 해석)

- **귀속 근거**: 이 이메일이 이 사람의 것이라고 본 이유. `이메일 계정에 이름 'jinah' 포함` / `성 'han'+이니셜 'ss' 포함` / `원문에서 이름 바로 뒤` / `전문 XML 저자 태그 '…' (교신저자)` / `Europe PMC 저자란 이름 일치` / `ORCID 본인 레코드`. 이 근거가 없는 이메일은 아예 표시하지 않습니다(공저자·부서 계정 제외).
- **검증**: 이메일 도메인이 소속 기관의 **공식 도메인**(ROR·DART·Wikidata·OpenAlex 기관 레코드의 홈페이지 호스트, 서브·형제 도메인 포함)과 일치. ORCID 본인 레코드의 이메일은 도메인 검증 없이 인정. 도메인을 어디서도 못 얻으면 이메일 도메인의 홈페이지를 열어 기관명이 있는지 확인합니다.
- **미검증**: 개인 메일(gmail 등) 또는 소속과 다른 기관 도메인(이전 소속·겸직 가능). 출처 문서에 실린 값을 그대로 보인 것이므로 사용 전 확인이 필요합니다.

## 7. 운영 참고

- 환경변수: `EMS_CONTACT_EMAIL`(권장), `EMS_API_KEY`, `EMS_OPENALEX_API_KEY`, `EMS_DART_API_KEY`, `EMS_S2_API_KEY`, `EMS_CORE_API_KEY`, `EMS_WORKERS`, `EMS_CORS_ORIGINS`, `EMS_JOB_TTL`, `EMS_PDF_BUDGET`, `EMS_CACHE_DIR`. 모든 키는 무료·선택입니다.
- 배포: `Dockerfile`(uvicorn, 포트 `$PORT`), `render.yaml`(Render Blueprint). 무료 인스턴스는 유휴 시 꺼져 첫 요청이 30초 이상 걸릴 수 있습니다.
- 캐시: 외부 조회 결과를 `EMS_CACHE_DIR/cache.sqlite3` 에 보관해 같은 사람·문서를 다시 묻지 않습니다. 컨테이너 디스크가 초기화되면 캐시도 사라집니다(동작에는 영향 없음).
- 개인정보: 응답의 `notice` 문구를 화면에 함께 표시하십시오. 이메일은 학술·기술 협력 문의 목적의 개별 연락에 쓰고 대량 광고 발송에는 쓰지 마십시오.
