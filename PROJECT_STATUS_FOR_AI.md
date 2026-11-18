> 이 문서는 덧붙이지 말고 매번 전체를 다시 쓴다.

# FigIndex 프로젝트 종합 현황서 (AI 분석·인수인계용)

---

## 0. 지금 상황 (Current Status)

1. **현재 단계**: 추출 품질 정리(빈 표·메타데이터) 완료, main·ryu 통합 완료. 비교 엔진 고도화와 검색·정답셋 측정 단계
2. **방금 한 일과 결과 (2026-11-18)**: 빈 표 82건 → 6건(v1 복원 10건, 재추출 후 승격 66건), source_org 23건·종목명 entity_name 보정, ryu를 main에 병합(#27, #28). main = ryu = `191e08b`, Docker 단위 테스트 200건 통과
3. **다음 할 일**: 비교 화면(`/compare`)에서 KT&G 등 종목 표시 확인, 남은 빈 표 6건 원문 확인, 팀원2 P@5·응답 시간 재측정 결과 받기
4. **막힌 것**: 없음
5. **팀장 결정 대기**: ① `main.py`의 비교 응답 모델 3개(`MatchedDocComparison`, `AlignedComparisonRow`, `CompareApiResponse`)와 `MetricType`을 `schemas.py`로 옮길지 ② 엔티티 사전 entity_name `TLB`·`LNF`(공식명 티엘비·엘앤에프) 유지 여부

---

## 1. 핵심 숫자 (Key Metrics)

> 아래 표는 `python scripts/update_status.py`가 자동으로 다시 쓴다. 측정 시각이 11-17이면 아직 갱신 전이다.

<!-- AUTO:START -->
| 항목 | 측정값 | 측정 시각 |
| :--- | :--- | :--- |
| **Git 브랜치** | `ryu` | 2026-11-17 17:14:31 KST |
| **Git 최신 커밋** | `22123cb - fix: sparse·point id 결정론화(crc32/uuid5), v2 sparse 재계산, 중복 4건 정리, CAP_LIMIT 재색인, 종목 키 target 표준화` | 2026-11-17 17:14:31 KST |
| **Git 미커밋 변경 파일** | `2개 파일` | 2026-11-17 17:14:31 KST |
| **Qdrant 컬렉션 (`v2`) 포인트** | `618` (승인: `532`, 검수대기: `86`) | 2026-11-17 17:14:31 KST |
| **Qdrant 색인 고유 문서** | `136개 문서` | 2026-11-17 17:14:31 KST |
| **원문 PDF 총계** | `141개 PDF` | 2026-11-17 17:14:31 KST |
| **미색인 원문 PDF 목록** | 5건: RPT_20261105_KB금융_미확인.pdf, RPT_20261105_우리금융지주_미확인.pdf, 논문_20260825_드론자력탐사오차보정_Geophysics.pdf, 보고서20261111휴머노이드로봇RD투자전략개방형_한국과학기술기획평가원.pdf, 보도자료_20260702_OECD한국경제보고서_재정경제부.pdf | 2026-11-17 17:14:31 KST |
| **동일 종목 비교 그룹** | `10개 그룹` (`compare_pairs.json`) | 2026-11-17 17:14:31 KST |
| **도표 비교 매칭 성공** | 총 69건 (TARGET_PRICE: 15건, ANNUAL_ESTIMATE: 28건, QUARTERLY_RESULT: 26건) | 2026-11-17 17:14:31 KST |
| **도표 비교 미매칭 원인** | 총 21건 (ABSENT: 8건, KEYWORD_MISS: 13건) | 2026-11-17 17:14:31 KST |
| **상태 검사기 (`check_state`)** | `PASS=7  WARN=1  CHANGED=0  FAIL=0  SKIP=0` | 2026-11-17 17:14:31 KST |
| └ **검사 경고(WARN) 항목** | A6. 모델 중복 정의 | 2026-11-17 17:14:31 KST |
| └ **검사 생략(SKIP) 항목** | 없음 | 2026-11-17 17:14:31 KST |
| └ **검사 실패(FAIL) 항목** | 없음 | 2026-11-17 17:14:31 KST |
<!-- AUTO:END -->

수동 기록 (2026-11-18)
- v2 표 데이터 빈 요소: 82건 → 6건
- 검색 (팀원2 측정, 승격 전 데이터): P@5 0.762, 평균 응답 0.212초 → 새 데이터로 재측정 요청
- 엔티티 사전 `figindex/data/entity_dictionary.csv`: 63개 (종목 48, 기관 9, 제품 6)
- 오분류 점검 후보 시트: 88건 중 11건 판정 (팀원3)
- 상태 검사기 (11-18 16:00, Docker 포함): PASS=7, WARN=1(A6), FAIL=0, 단위 테스트 200건 통과

---

## 2. 최근 작업 로그 (Recent Logs - 최근 5건)

| 시각 | 작업 요청 | 바꾼 파일 | 실행 명령 | 결과 숫자 | 판정 |
| :---: | :--- | :--- | :--- | :--- | :---: |
| **11-18 15:45** | ryu를 main에 병합 (#27, 빠진 #26은 #28), ryu를 main과 같게 맞춤 | `orchestrator.py`(충돌 해결), `backend/app/main.py`(ryu 비교 API를 `/api/compare/company`로), `test_check_state_a1.py` | `python scripts/check_state.py --quick` | main=ryu=`191e08b`, 단위 테스트 200건 통과, FAIL 0 | **PASS** |
| **11-18 15:20** | 메타데이터 보정: 요소마다 비교, 종목명을 entity_name으로 (#25, #26) | `scripts/fix_metadata_from_filename.py`, `scripts/test_fix_metadata_per_point.py` | `python scripts/fix_metadata_from_filename.py` | 66포인트 보정(source_org 23건 포함), 재실행 dry-run 0건, 백업 2개 | **PASS** |
| **11-18 15:19** | 재추출 결과 승격 (#24) | `scripts/promote_test_to_service.py` | `python scripts/promote_test_to_service.py --test-collection figindex_test_ryu --apply` | 66건 반영(검수대기 → 승인, 확신도 0.829~0.954), 6건 건너뜀 | **PASS** |
| **11-18 오후** | 빈 표 72건을 시험 컬렉션에 재추출 (#21, #22, #23) | `pipeline/table_parse.py`, `extractor.py`, `run_index.py`, `scripts/reextract_empty_tables.py`, `schemas.py`(PIPELINE_VERSION 0.1.1) | `docker compose run --rm -e QDRANT_COLLECTION=figindex_test_ryu pipeline python /scripts/reextract_empty_tables.py ...` | 72건 중 66건 표 채움, 셀 숫자 glossary 9절대로 저장 | **PASS** |
| **11-18 12:35** | 빈 표 진단·v1 복원 (#20) | `scripts/diagnose_empty_tables.py`, `restore_tables_from_v1.py`, `inspect_gemini_cache.py` | `python scripts/restore_tables_from_v1.py --apply` | 빈 표 82건 진단, v1에서 10건 복원 | **PASS** |

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
9. **검색 (팀원2)**: Kiwi 형태소 + BM25 sparse + dense 하이브리드, 엔티티 사전 63개, 검색 정답셋 `figindex/data/gt/search/queries.json`, `scripts/eval_search.py`.
10. **표 파싱 정리 (PIPELINE_VERSION 0.1.1)**: `pipeline/table_parse.py`의 `coerce_table_data`(행 키를 columns에 맞춤, 셀 숫자 변환, % 단위는 unit_by_row), `model_name`에 실제 응답 모델 기록, 빈 표 결과를 Gemini 캐시에 미리 채우지 않음.
11. **데이터 작업 도구 (모두 dry-run 기본, 백업·되돌리기 지원)**: `reextract_empty_tables.py`(시험 컬렉션 전용), `promote_test_to_service.py`, `fix_metadata_from_filename.py`, `restore_tables_from_v1.py`, `list_review_candidates.py`, `diagnose_empty_tables.py`.

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
9. **종목명은 엔티티 사전의 entity_name으로 저장 (11-18)**: 파일명 표기(CJENM, KTnG)는 사전 별칭으로 대조해 `CJ ENM`, `KT&G`로 저장. 결정 7의 'KTnG' 그룹도 이제 `KT&G`로 저장됨.
10. **PIPELINE_VERSION 0.1.0 → 0.1.1 (11-18)**: 표 파싱·캐시 후처리 변경.
11. **ryu → main 통합 (11-18)**: ryu 전체를 main에 병합하고 ryu 브랜치는 계속 사용. `/api/compare`는 비교 화면용 엔진을 정식으로 두고, ryu 엔진은 `/api/compare/company`로 분리 (백엔드 `/compare` 별칭 제거).
12. **저장소 정리 (11-18)**: 병합된 PR 브랜치 자동 삭제 설정 켬. 데이터 zip에 entity_dictionary.csv를 넣지 않음(git 관리).

---

## 5. 열린 문제·넘길 일 (Open Issues)

| 문제 / 이슈 | 담당 | 상태 | 상세 내용 |
| :--- | :---: | :---: | :--- |
| **재추출 후에도 남은 빈 표 6건** | 파이프라인·정답셋 | 열림 | 표 비어 있음 5건(fig-437d261937fb, fig-4533959cd998, fig-7c7e2076e72d, fig-c76cd99a9425, fig-9b882a3ba1df), 유형이 DIAGRAM으로 바뀐 1건(fig-a4106b2a65df). 원문 확인 후 처리 |
| **비교 응답 모델·MetricType의 schemas.py 이전** | 백엔드/스키마 | 결정 대기 | check_state A6 경고 원인. 옮길 때 `match_status` 문자열도 Enum으로 |
| **엔티티 정규화 (AGENTS.md 5절)** | 파이프라인 | 일부 완료 | 문서 종목명(target)은 entity_name으로 보정. 색인 시 entities 전체를 사전으로 바꾸는 처리는 아직 |
| **TLB·LNF entity_name 표기** | 검색(팀원2) | 확인 요청 | 공식명은 티엘비·엘앤에프. 바꾸면 `fix_metadata_from_filename.py` 다시 실행 |
| **검색 지표 재측정** | 검색(팀원2) | 요청함 | 66건 승격·메타데이터 보정 후 P@5·응답 시간 |
| **오분류 점검 (88건)** | 정답셋(팀원3) | 진행 중 | 대덕전자 p.5(fig-6386d10c89bf)는 재추출로 38행 채워짐 → 재확인 요청 |
| **PR #11 업로드 UI·API** | 업로드(팀원1) | 검토 대기 | 금요일 배포 전 검토 |
| **KB금융·우리금융지주 도표 0개** | 파이프라인 | 열림 | 텍스트 중심 리포트 |
| **CAP_LIMIT 문서 재색인 실행** | 파이프라인 | 대기 | 승인된 23건 |
| **잘못된 크롭 (KT&G 유안타 p.10)** | 크롭 | 열림 | 같은 캡션에 다른 크롭 박스 |
| **캡션 오배정 (HeritageJ p.2)** | 정답셋 | 열림 | 같은 캡션이 2개 요소에 |
| **check_state 테스트 2건 실패** | 인프라 | 열림 | `test_check_state_a2.py`의 legacy_allowed_files 2건 (예전부터, Docker 밖 실행 시) |

---

## 6. 알려진 함정 (Known Pitfalls)

1. **PowerShell에서 `&&` 사용 불가**: `;` 또는 줄 나눠 실행.
2. **100MB 초과 파일 Git push 불가**: 스냅샷·zip은 `.gitignore`.
3. **문서당 도표 상한 기본값 4**: 후반부 표 누락(CAP_LIMIT) 주의.
4. **Gemini 무료 티어 분당 14회**: 공용 `GeminiRateLimiter` 경유. 3.8-flash 503 시 lite로 대체되며 lite도 429 한도 있음. `reextract_empty_tables.py --reuse-cache`는 Gemini 호출 없이 후처리만 다시 함.
5. **승격 후 메타데이터 보정 순서**: `promote_test_to_service.py`는 payload 전체를 덮어쓴다. 메타데이터 보정은 승격 뒤에 다시 돌린다.
6. **git pull 실패 (untracked 파일)**: 저장소에 새로 들어올 파일과 같은 이름의 로컬 파일이 있으면 pull이 멈춘다. 받은 스크립트·zip·ps1은 `C:\workAi\figindex_work`에 둔다.
7. **실행 위치**: `scripts\*.py`는 저장소 루트, `docker compose`는 `figindex/`에서.
8. **PowerShell 한글 깨짐**: UTF-8 ps1·REST 출력이 깨져 보여도 결과는 정상(표시 문제).
9. **Gemini 캐시를 끄지 않는다** (`extractor.py`).

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
- 브랜치: `main`(배포), `ryu`(팀장 작업, 11-18 기준 main과 같음), 팀원 브랜치는 PR 병합 시 자동 삭제.

---

## 8. 로드맵 (Roadmap)

- **이번 주 (~11/20)**: 금요일 배포(PR #11 포함), 오분류 점검, 남은 빈 표 6건 정리, 검색 재측정.
- **11/23~27**: 비교 엔진 구현·정리(두 엔진 역할 정리, 모델 schemas.py 이전 결정), 추출 품질 조정, 팀원4 합류 후 크롭(YOLO) 비교. 11/27 기능 개발 마감.
- **11/30~12/2**: 지표 측정·버그 수정.
- **12/3**: 시연 리허설.
