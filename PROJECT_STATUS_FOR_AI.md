> 이 문서는 덧붙이지 말고 매번 전체를 다시 쓴다.

# FigIndex 프로젝트 종합 현황서 (AI 분석·인수인계용)

---

## 0. 지금 상황 (Current Status)

1. **현재 단계**: 11-18 마감. 데이터 정리·통합 완료, 업로드(진행률·ReviewLog·기존 PDF 등록)와 검색 측정까지 끝남. 다음은 업로드→파이프라인 연결과 수치 정답셋 측정
2. **방금 한 일과 결과 (2026-11-18)**: 빈 표 정리·'요소 아님' 17건 반려·종목명 사전 기준 통일(거래소 종목명, #34 포함) 후 새 zip 배포. 표지 기반 메타데이터(#35), 업로드 진행률·ReviewLog·기존 PDF 등록(#36) 병합. 검색 정식 측정 P@5 0.900·응답 0.314초. 오분류 점검 88건 완료
3. **다음 할 일 (11-19)**: 수치표 30개를 v2 요소와 대조하고 팀원3용 예시 만들기 → `cell_accuracy`·`table_valid_rate` 계산 스크립트, PIPELINE_VERSION 결정, 팀원1 보완 PR(doc_id를 Qdrant와 맞추기, 미색인 5개 UPLOADED) 검토. 팀원2는 11-19 결근
4. **막힌 것**: 없음
5. **팀장 결정 대기**: ① PIPELINE_VERSION 0.1.1 → 0.1.2 (표지 메타데이터, #35) ② `main.py`의 비교 응답 모델 3개(`MatchedDocComparison`, `AlignedComparisonRow`, `CompareApiResponse`)와 `MetricType`을 `schemas.py`로 옮길지

---

## 1. 핵심 숫자 (Key Metrics)

> 아래 표는 `python scripts/update_status.py`가 자동으로 다시 쓴다. 측정 시각이 11-17이면 아직 갱신 전이다.

<!-- AUTO:START -->
| 항목 | 측정값 | 측정 시각 |
| :--- | :--- | :--- |
| **Git 브랜치** | `ryu` | 2026-11-18 18:08:37 KST |
| **Git 최신 커밋** | `알 수 없음` | 2026-11-18 18:08:37 KST |
| **Git 미커밋 변경 파일** | `0개 파일` | 2026-11-18 18:08:37 KST |
| **Qdrant 컬렉션 (`v2`) 포인트** | `618` (승인: `593`, 검수대기: `8`, 반려: `17`) | 2026-11-18 18:08:37 KST |
| **Qdrant 색인 고유 문서** | `136개 문서` | 2026-11-18 18:08:37 KST |
| **원문 PDF 총계** | `141개 PDF` | 2026-11-18 18:08:37 KST |
| **미색인 원문 PDF 목록** | 5건: RPT_20261105_KB금융_미확인.pdf, RPT_20261105_우리금융지주_미확인.pdf, 논문_20260825_드론자력탐사오차보정_Geophysics.pdf, 보고서20261111휴머노이드로봇RD투자전략개방형_한국과학기술기획평가원.pdf, 보도자료_20260702_OECD한국경제보고서_재정경제부.pdf | 2026-11-18 18:08:37 KST |
| **동일 종목 비교 그룹** | `10개 그룹` (`compare_pairs.json`) | 2026-11-18 18:08:37 KST |
| **도표 비교 매칭 성공** | 총 69건 (TARGET_PRICE: 15건, ANNUAL_ESTIMATE: 28건, QUARTERLY_RESULT: 26건) | 2026-11-18 18:08:37 KST |
| **도표 비교 미매칭 원인** | 총 21건 (ABSENT: 8건, KEYWORD_MISS: 13건) | 2026-11-18 18:08:37 KST |
| **상태 검사기 (`check_state`)** | `PASS=7  WARN=1  CHANGED=0  FAIL=0  SKIP=0` | 2026-11-18 18:08:37 KST |
| └ **검사 경고(WARN) 항목** | A6. 모델 중복 정의 | 2026-11-18 18:08:37 KST |
| └ **검사 생략(SKIP) 항목** | 없음 | 2026-11-18 18:08:37 KST |
| └ **검사 실패(FAIL) 항목** | 없음 | 2026-11-18 18:08:37 KST |
<!-- AUTO:END -->

수동 기록 (2026-11-18 18:10)
- v2 618건: 승인 593, 검수대기 8, 반려 17 (반려는 오분류 점검 '요소 아님', 백업 `reject_backup_*.json`)
- 검색 정식 측정 (새 zip, `eval_search.py`, 검색어 20개): `precision_at_5` 0.900, `search_latency_sec` 0.314 (첫 실행, 1번 검색어 1.66초 포함). 기업명+지표 검색(1~3번)은 0.6·0.5·0.4로 가장 낮음
- 엔티티 사전 `figindex/data/entity_dictionary.csv`: 65개 (종목 50, 기관 9, 제품 6), 종목은 한국거래소 종목명 기준
- 오분류 점검 88건 완료: 맞음 56, 틀림 32 (요소 아님 17, 잘림 13, 캡션 3, 노이즈 1, 유형 0)
- 수치 정답셋: 정답셋 작업 시트 '수치표' 탭에 표 30개(T01~T30), 셀 약 800개. 아직 v2 요소 ID와 연결 전
- 업로드 DB `data/metadata.sqlite3`: 기존 PDF 141개 등록 (PC마다 `docker compose exec backend python -m app.register_existing_pdfs` 1회)
- 상태 검사기 (11-18 16:00, Docker 포함): PASS=7, WARN=1(A6), FAIL=0, 단위 테스트 200건 통과
---

## 2. 최근 작업 로그 (Recent Logs - 최근 5건)

| 시각 | 작업 요청 | 바꾼 파일 | 실행 명령 | 결과 숫자 | 판정 |
| :---: | :--- | :--- | :--- | :--- | :---: |
| **11-18 18:06** | 검색 정식 측정 (팀원2 결근 대신 팀장) | 없음 | `python scripts/eval_search.py` | P@5 0.900, 응답 0.314초(첫 실행)·0.024초(캐시) | **PASS** |
| **11-18 17:46** | 팀원1 진행률·ReviewLog·기존 PDF 등록(#36) 병합, 거래소 종목명(#34) 재정규화 | `backend/app/upload_store.py` 등, (데이터) v2 16포인트 | `python -m app.register_existing_pdfs`, `fix_metadata_from_filename.py` | 기존 PDF 141개 등록, 씨엠티엑스 5·씨에스윈드 5·LIG디펜스앤에어로스페이스 6 | **PASS** |
| **11-18 17:30** | 업로드 PDF 이름이 형식과 달라도 표지에서 종목·증권사·발행일 채우기, 현황서 반려 건수 분리 | `pipeline/orchestrator.py`, `pipeline/test_cover_metadata.py`, `scripts/update_status.py` | `pytest pipeline/test_cover_metadata.py pipeline/test_metadata_generalization.py` | 새 테스트 7건·기존 메타데이터 테스트 통과 | **PASS** |
| **11-18 16:57** | 팀원1 PDF 묶음 업로드(#11) 병합, main을 ryu에 합침 | `backend/app/main.py`, `backend/app/upload_store.py`, `frontend/app/components/UploadPanel.tsx` 등 | 업로드 저장 로직 직접 시험 | 처음 등록·중복·같은 이름 충돌·묶음 내 중복 5가지 기대대로 | **PASS** |
| **11-18 16:40** | 비교 가능성 점검의 종목명 하드코딩 제거 (사전만 사용) | `pipeline/analyze_comparability.py`, `pipeline/test_analyze_comparability_entity.py` | `pytest pipeline/test_analyze_comparability_entity.py` | 3건 통과, 하드코딩 맵 2개 삭제(종목 25·별칭 7) | **PASS** |

---

## 3. 완료 이력 (Historical Summary)

1. **단일 스키마 기준 확립**: `shared/schemas.py`, `coords.py` 중심으로 스키마 단일화, 엄격 금지 이름 0건.
2. **백엔드/프론트엔드 v2 전환**: 백엔드 컬렉션 기본값 `figindex_elements_v2`, `CONFIDENCE_THRESHOLD` 적용, 프론트 타입 연동.
3. **파이프라인 새 스키마 전환**: `orchestrator`, `extractor`, `evaluator` 구 스키마 제거, `schemas_legacy.py` 삭제.
4. **동일 종목 비교쌍 (`compare_pairs.json`)**: 10개 종목 그룹(30개 문서).
5. **파일명 우선 메타데이터**: `parse_rpt_filename()`로 `RPT_YYYYMMDD_종목_증권사.pdf` 파싱.
6. **Rate Limiter·원자적 색인 (`ingest_missing.py`)**: 분당 14회 공용 `GeminiRateLimiter`, 문서 단위 upsert·롤백.
7. **비교 엔진 2종**: ① 비교 화면용 `shared/compare.py` + `GET /api/compare`, `/api/compare/metrics` (glossary 14절) ② 종목·지표 매칭 엔진 `figindex/compare/` + `GET /api/compare/company` (`MetricType` 3종).
8. **결정론적 sparse·point id (crc32/uuid5)**, v2 sparse IDF modifier 켬.
9. **검색 (팀원2)**: Kiwi 형태소 + BM25 sparse + dense 하이브리드, 엔티티 사전 65개, `/api/search` 문서 유형·증권사·발행일 필터, 검색 정답셋 `figindex/data/gt/search/queries.json`, `scripts/eval_search.py`.
10. **표 파싱 정리 (PIPELINE_VERSION 0.1.1)**: `pipeline/table_parse.py`의 `coerce_table_data`(행 키를 columns에 맞춤, 셀 숫자 변환, % 단위는 unit_by_row), `model_name`에 실제 응답 모델 기록, 빈 표 결과를 Gemini 캐시에 미리 채우지 않음.
11. **데이터 작업 도구 (모두 dry-run 기본, 백업·되돌리기 지원)**: `reextract_empty_tables.py`(시험 컬렉션 전용), `promote_test_to_service.py`, `fix_metadata_from_filename.py`, `restore_tables_from_v1.py`, `list_review_candidates.py`, `diagnose_empty_tables.py`.
12. **PDF 묶음 업로드 (팀원1, #11)**: `POST /api/batches`, 화면 '📄 PDF 업로드' 탭. SHA-256 `doc_hash`로 중복 판정, `data/metadata.sqlite3`에 Batch·Document 저장. 파이프라인 실행은 아직 연결 안 함.
13. **표지 기반 메타데이터 (11-18)**: 파일명 형식이 아니면 표지에서 종목(사전 종목코드 → 사전 이름·별칭), 증권사(`BROKER_ALIASES`, '증권'·'투자' 들어간 표기만, 표지 → 마지막 페이지), 발행일(표지 → 파일명 YYYYMMDD → 끝 MMDD)을 찾음. 못 찾으면 None.

---

## 4. 팀장 결정 기록 (Decisions)

1. **파일명 우선 메타데이터**: 파일명의 발행일자·증권사·종목명을 표지·LLM 값보다 우선. 증권사가 '미확인'일 때만 LLM에 위임.
2. **CAP_LIMIT 문서 v2 재색인 허용 (사전 스냅샷 필수, 11-17)**: 23건 한정, `--max-elements 8`.
3. **TARGET_PRICE 표 우선순위**: 캡션에 산출·산정·적정주가가 있는 표 1순위, 요약 박스형은 대안.
4. **결정론적 sparse 토큰·고정 point id 전환 (11-17)**: v2 622건 sparse 교체(사전 스냅샷 생성).
5. **중복 포인트 4건 삭제 (11-17)**: 이력 `data/migration/dedup_20261117.csv`.
6. **종목 키 표준 `extra_metadata.target` (11-17)**: 빈 target 31건 백필.
7. **비교 수치 정답셋 1차본 28건 (11-17)**: `data/eval/compare_numbers_check.csv`. 카카오 지배주주순이익 편차 29%는 증권사 추정치 차이로 시연 후보.
8. **v2 쓰기는 시험 컬렉션을 거친다 (11-18)**: 재추출은 `figindex_test_<이름>`에만 쓰고, 미리보기 확인 후 `promote_test_to_service.py --apply`(백업 자동)로 v2에 반영. 표가 여전히 비었거나 유형이 바뀐 요소는 승격하지 않음.
9. **종목명은 엔티티 사전의 entity_name으로 저장 (11-18)**: 파일명 표기(CJENM, KTnG, LNF, TLB)는 사전 별칭으로 대조해 `CJ ENM`, `KT&G`, `엘앤에프`, `티엘비`로 저장. 결정 7의 'KTnG' 그룹도 이제 `KT&G`. 코드에 종목명을 직접 적지 않는다.
10. **PIPELINE_VERSION 0.1.0 → 0.1.1 (11-18)**: 표 파싱·캐시 후처리 변경.
11. **ryu → main 통합 (11-18)**: ryu 전체를 main에 병합하고 ryu 브랜치는 계속 사용. `/api/compare`는 비교 화면용 엔진을 정식으로 두고, ryu 엔진은 `/api/compare/company`로 분리 (백엔드 `/compare` 별칭 제거).
12. **저장소 정리 (11-18)**: 병합된 PR 브랜치 자동 삭제 설정 켬. 데이터 zip에 entity_dictionary.csv를 넣지 않음(git 관리).
13. **'요소 아님' 17건 반려 (11-18, v2 쓰기)**: 오분류 점검에서 목차·장 제목·초록으로 판정된 요소를 관리자 검수 API로 반려. 그중 12건은 오늘 승격으로 자동 승인됐던 것(확신도 0.94~0.954) → 확신도 신호가 목차를 거르지 못함.
14. **현황서 갱신 규칙 (11-18)**: AGENTS.md 8절. ryu 작업은 현황서 전체를 다시 쓰고 `update_status.py` 실행, 팀원 브랜치는 이 파일을 고치지 않음.
15. **업로드 파일 이름 규칙을 강제하지 않음 (11-18)**: 증권사에서 받은 이름 그대로 올려도 되도록 파이프라인이 표지에서 메타데이터를 찾는다(팀장 처리). 발행일·종목을 못 찾으면 오늘 날짜나 파일명 조각으로 채우지 않고 비워 둔다. 파일명 형식이 맞으면 결정 1대로 파일명이 우선.

---

## 5. 열린 문제·넘길 일 (Open Issues)

| 문제 / 이슈 | 담당 | 상태 | 상세 내용 |
| :--- | :---: | :---: | :--- |
| **목차 페이지가 표로 잘림** | 파이프라인·크롭 | 열림 | 에너지경제연구원 보고서 등 목차·장 제목 17건이 TABLE로 색인됐고 확신도도 높게 나옴. 크롭·추출 단계에서 목차 페이지를 거르는 조건 필요 (지금은 17건 반려로 대응) |
| **빈 표 1건 (BERT p.8, fig-437d261937fb)** | 정답셋 | 열림 | 실제 표가 있으나 캡션 "M th d"로 틀림, 표 데이터 없음. 검수대기 |
| **오분류 '잘림'(제목·단위·주석) 다수** | 크롭(팀원4) | 열림 | 오분류 시트 틀림 33건 중 잘림 14건 안팎. 크롭 여백 비교 자료로 사용 |
| **비교 응답 모델·MetricType의 schemas.py 이전** | 백엔드/스키마 | 결정 대기 | check_state A6 경고 원인. 옮길 때 `match_status` 문자열도 Enum으로 |
| **엔티티 정규화 (AGENTS.md 5절)** | 파이프라인 | 일부 완료 | 문서 종목명(target)·`analyze_comparability.py`는 사전 기준으로 맞춤. 색인 시 entities 전체를 사전으로 바꾸는 처리는 아직 (사전에 없는 값 345종, 대부분 일반 단어·증권사명) |
| **사전 이름 기준** | 검색(팀원2) | 해결 | 한국거래소 종목명 기준으로 통일(#34), v2 재정규화 완료 |
| **기업명+지표 검색 약함** | 검색(팀원2) | 열림 | 정식 측정에서 1~3번(SK하이닉스·삼성전자·카카오)이 0.4~0.6. 서비스 핵심 시나리오라 다음 주 검색 개선 우선순위 |
| **오분류 점검** | 정답셋(팀원3) | 해결 | 88건 완료. 다음은 수치표 30개 요소 ID 연결 (11-19 예시 제공) |
| **업로드 DB의 기존 PDF doc_id·상태** | 업로드(팀원1) | 요청함 | 기존 PDF 등록은 됨(#36). doc_id를 Qdrant와 맞추기, 미색인 5개는 UPLOADED로 등록 요청 |
| **업로드 → 파이프라인 연결** | 팀장·팀원1 | 열림 | 연결 시 표지 기반 메타데이터 사용. 증권사 목록은 아직 코드(`BROKER_ALIASES`)에 있음 → 사전으로 옮길지 검토 |
| **KB금융·우리금융지주 도표 0개** | 파이프라인 | 열림 | 텍스트 중심 리포트 |
| **CAP_LIMIT 문서 재색인 실행** | 파이프라인 | 대기 | 승인된 23건 |
| **잘못된 크롭 (KT&G 유안타 p.10)** | 크롭 | 열림 | 같은 캡션에 다른 크롭 박스 |
| **캡션 오배정 (HeritageJ p.2)** | 정답셋 | 열림 | 같은 캡션이 2개 요소에 |
| **현황서 1절 반려 건수** | 인프라 | 해결 | `update_status.py`가 승인·검수대기·반려를 따로 셈 (전에는 반려가 검수대기에 섞임) |
| **check_state 테스트 2건 실패** | 인프라 | 열림 | `test_check_state_a2.py`의 legacy_allowed_files 2건 (예전부터, Docker 밖 실행 시) |

---

## 6. 알려진 함정 (Known Pitfalls)

1. **PowerShell에서 `&&` 사용 불가**: `;` 또는 줄 나눠 실행.
2. **100MB 초과 파일 Git push 불가**: 스냅샷·zip은 `.gitignore`.
3. **문서당 도표 상한 기본값 4**: 후반부 표 누락(CAP_LIMIT) 주의.
4. **Gemini 무료 티어 분당 14회**: 공용 `GeminiRateLimiter` 경유. 3.8-flash 503 시 lite로 대체되며 lite도 429 한도 있음. `reextract_empty_tables.py --reuse-cache`는 Gemini 호출 없이 후처리만 다시 함.
5. **승격 후 메타데이터 보정 순서**: `promote_test_to_service.py`는 payload 전체를 덮어쓴다. 메타데이터 보정은 승격 뒤에 다시 돌린다.
6. **확신도가 높아도 요소가 아닐 수 있음**: 목차 페이지도 표로 읽히면 0.95까지 나와 자동 승인됨. 승격·대량 반영 후에는 오분류 점검으로 한 번 더 본다.
7. **git pull 실패 (untracked 파일)**: 저장소에 새로 들어올 파일과 같은 이름의 로컬 파일이 있으면 pull이 멈춘다. 받은 스크립트·zip·ps1은 `C:\workAi\figindex_work`에 둔다.
8. **실행 위치**: `scripts\*.py`는 저장소 루트, `docker compose`는 `figindex/`에서.
9. **PowerShell 한글 깨짐**: Windows PowerShell 5.1은 BOM 없는 UTF-8 ps1과 REST 응답의 한글을 깨뜨려 보여 준다(데이터는 정상). ps1은 BOM 붙여 저장.
10. **Gemini 캐시를 끄지 않는다** (`extractor.py`).

---

## 7. 기준 파일·실행 환경

### 5대 기준 파일 (Single Source of Truth)
1. **`figindex/shared/schemas.py`**: 유일한 표준 스키마 (`Element`, `ElementSearchPayload`, `TableData`, `ConfidenceSignals`, `Document`, `Batch`, `ReviewLog`, `ComparisonResult` 등).
2. **`figindex/shared/coords.py`**: bbox `[x0, y0, x1, y1]`(좌상단 원점, 0~1)와 좌표 변환.
3. **`docs/glossary.md`**: 확신도 신호(6절), 메타데이터(7절), 좌표(8절), 표 수치 저장 규칙(9절), 엔티티 사전(10절), 평가 지표(12절), 문서 간 비교(14절).
4. **`AGENTS.md`**: 쓰지 않는 이름(2절), 수정 금지 파일(7절) 등 에이전트 규칙. 파이프라인 작업은 `figindex/pipeline/AGENTS.md`도 따른다.
5. **`figindex/pipeline/pdf_text.py`**: PDF 텍스트를 2차원 좌표 순서로 읽는 단일 함수.

### 실행 환경 (`figindex/docker-compose.yml`)
- `figindex-qdrant`, `figindex-backend`, `figindex-frontend` (`QDRANT_COLLECTION=figindex_elements_v2`). backend는 kiwipiepy 포함 빌드 필요.
- `pipeline` 서비스는 `profiles: ["index"]`.
- Qdrant: 서비스 `figindex_elements_v2`(618), 구버전 `figindex_elements`(525), 시험 `figindex_test_ryu`. v2·v1 쓰기는 팀장 승인 필요.
- 브랜치: `main`(배포), `ryu`(팀장 작업, 11-18 오후 기준 main과 같게 맞춤), 팀원 브랜치는 PR 병합 시 자동 삭제.
- 관리자 검수 API: `POST /api/review/{element_id}` (헤더 `X-Admin-Password`, `review_action` APPROVE/REJECT). 지금은 ReviewLog를 남기지 않음(팀원1 담당).

---

## 8. 로드맵 (Roadmap)

- **이번 주 (~11/20)**: 금요일 배포(ryu → main 포함), 수치 정답셋 연결·측정 시작, 업로드→파이프라인 연결 설계, PIPELINE_VERSION 결정.
- **11/23~27**: 비교 엔진 구현·정리(두 엔진 역할 정리, 모델 schemas.py 이전 결정), 추출 품질 조정(목차 거르기, 색인 시 entities 전체 사전 정규화), 팀원4 합류 후 크롭(YOLO) 비교(오분류 '잘림' 사례 활용). 11/27 기능 개발 마감.
- **11/30~12/2**: 지표 측정·버그 수정.
- **12/3**: 시연 리허설.
