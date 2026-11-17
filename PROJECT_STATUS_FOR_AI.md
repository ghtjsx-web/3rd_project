> 이 문서는 덧붙이지 말고 매번 전체를 다시 쓴다.

# FigIndex 프로젝트 종합 현황서 (AI 분석·인수인계용)

---

## 0. 지금 상황 (Current Status)

1. **현재 단계**: 4a/4b 전면 완료 후 sparse 토큰 결정론화(crc32) 및 v2 교체 완료, 중복 정리 및 지표 비교 매트릭스 고도화 단계
2. **방금 한 일과 결과**: Docker 환경 A8 단위 테스트 실패 2건(extractor primary_model 접근, parse_rpt_filename company 키) 원인 규명 및 코드 수정, A8 단위 테스트 156건 100% 통과(FAIL 0 달성)
3. **다음 할 일**: KEYWORD_MISS 13건 검토(재색인으로 CAP_LIMIT에서 이동한 건 포함)
4. **막힌 것**: 없음
5. **팀장 결정 대기**: `MetricType` Enum의 `schemas.py` 이전 승인 대기

---

## 1. 핵심 숫자 (Key Metrics)

<!-- AUTO:START -->
| 항목 | 측정값 | 측정 시각 |
| :--- | :--- | :--- |
| **Git 브랜치** | `ryu` | 2026-11-17 15:49:11 KST |
| **Git 최신 커밋** | `280072f - feat: 파일명 우선 메타데이터, 미색인 일괄 색인, 비교 엔진 1차 (/compare, 매트릭스 점검)` | 2026-11-17 15:49:11 KST |
| **Git 미커밋 변경 파일** | `19개 파일` | 2026-11-17 15:49:11 KST |
| **Qdrant 컬렉션 (`v2`) 포인트** | `618` (승인: `532`, 검수대기: `86`) | 2026-11-17 15:49:11 KST |
| **Qdrant 색인 고유 문서** | `136개 문서` | 2026-11-17 15:49:11 KST |
| **원문 PDF 총계** | `141개 PDF` | 2026-11-17 15:49:12 KST |
| **미색인 원문 PDF 목록** | 5건: RPT_20261105_KB금융_미확인.pdf, RPT_20261105_우리금융지주_미확인.pdf, 논문_20260825_드론자력탐사오차보정_Geophysics.pdf, 보고서20261111휴머노이드로봇RD투자전략개방형_한국과학기술기획평가원.pdf, 보도자료_20260702_OECD한국경제보고서_재정경제부.pdf | 2026-11-17 15:49:12 KST |
| **동일 종목 비교 그룹** | `10개 그룹` (`compare_pairs.json`) | 2026-11-17 15:49:12 KST |
| **도표 비교 매칭 성공** | 총 69건 (TARGET_PRICE: 15건, ANNUAL_ESTIMATE: 28건, QUARTERLY_RESULT: 26건) | 2026-11-17 15:49:12 KST |
| **도표 비교 미매칭 원인** | 총 21건 (ABSENT: 8건, KEYWORD_MISS: 13건) | 2026-11-17 15:49:12 KST |
| **상태 검사기 (`check_state`)** | `PASS=6  WARN=2  CHANGED=0  FAIL=0  SKIP=0` | 2026-11-17 15:49:12 KST |
| └ **검사 경고(WARN) 항목** | A1. Git 변경 범위, A6. 모델 중복 정의 | 2026-11-17 15:49:12 KST |
| └ **검사 생략(SKIP) 항목** | 없음 | 2026-11-17 15:49:12 KST |
| └ **검사 실패(FAIL) 항목** | 없음 | 2026-11-17 15:49:12 KST |
<!-- AUTO:END -->

---

## 2. 최근 작업 로그 (Recent Logs - 최근 5건)

| 시각 | 작업 요청 | 바꾼 파일 | 실행 명령 | 결과 숫자 | 판정 |
| :---: | :--- | :--- | :--- | :--- | :---: |
| **15:40** | Docker A8 단위 테스트 2건 실패(extractor, parse_rpt_filename) 코드 수정 및 전량 통과 | `orchestrator.py`, `extractor.py`, `PROJECT_STATUS_FOR_AI.md` | `python scripts/check_state.py --quick` | 단위 테스트 156건 100% 통과 (PASS=6, FAIL=0) | **PASS** |
| **15:35** | v2 sparse 벡터 실제 교체, 중복 4건 삭제 정리, 매트릭스 재실행 및 현황 갱신 | `rebuild_sparse_vectors.py`, `dedup_points.py`, `PROJECT_STATUS_FOR_AI.md` | `python scripts/run_compare_matrix.py` | 교체 622건(실패 0), 삭제 4건(잔여 618건), 매칭 69건(직전 61건 대비 +8) | **PASS** |
| **15:20** | 결정론적 sparse 토큰(crc32) 및 uuid5 고정 point_id 전환, 재계산 스크립트 작성 및 dry-run | `shared/sparse.py`, `orchestrator.py`, `extractor.py`, `rebuild_sparse_vectors.py`, `test_sparse_and_point_id.py` | `pytest figindex/pipeline/test_sparse_and_point_id.py` | 622건 대상 dry-run 완료, 중복 6그룹 발견, pytest 2종 통과 | **PASS** |
| **13:03** | TARGET_PRICE 내용 검증 해제, Forecast/earning 제외 및 산출 우선순위 유지, 가정 제외 유지 | `matcher.py`, `run_compare_matrix.py`, `PROJECT_STATUS_FOR_AI.md` | `python scripts/run_compare_matrix.py` | 매칭 61건 (TP 13, AE 25, QR 23), 미매칭 29건 | **PASS** |
| **12:55** | TARGET_PRICE 내용 검증 및 우선순위, 가정 제외, 공통 최근 분기 실적 열 정렬 | `metrics.py`, `matcher.py`, `service.py`, `run_compare_matrix.py` | `python scripts/run_compare_matrix.py` | 매칭 56건 (TP 8, AE 25, QR 23), 미매칭 34건 | **PASS** |

---

## 3. 완료 이력 (Historical Summary)

1. **단일 스키마 기준 확립**: `shared/schemas.py`, `coords.py`를 중심으로 스키마를 단일화하고 엄격 금지 이름 114건을 완전 박멸(0건 달성).
2. **백엔드/프론트엔드 v2 전환 (4a)**: 백엔드 `main.py` 컬렉션 기본값을 `figindex_elements_v2`로 전환하고 `CONFIDENCE_THRESHOLD` 적용 및 프론트엔드 타입 연동 완료.
3. **파이프라인 새 스키마 전환 (4b)**: `orchestrator`, `extractor`, `evaluator`에서 구 스키마를 전면 제거하고 역할 분리 완료, `schemas_legacy.py` 영구 삭제.
4. **동일 종목 비교쌍 생성 (`compare_pairs.json`)**: Qdrant `company` 기준으로 10개 종목 그룹(30개 문서) 자동 생성 및 동일 발행일자 식별 완료.
5. **파일명 메타데이터 파싱 강화**: `parse_rpt_filename()` 구현으로 `RPT_YYYYMMDD_종목_증권사.pdf` 파일명 우선 추출 및 기존 10개 문서 메타데이터 일괄 보정.
6. **호출 단위 Rate Limiter 및 원자적 색인 (`ingest_missing.py`)**: 분당 최대 14회 공용 `GeminiRateLimiter`, 문서 단위 원자적 upsert 및 실패 롤백 구축.
7. **도표 비교(Compare) 엔진 및 API 구축**: `MetricType` 3개 지표(`TARGET_PRICE`, `ANNUAL_ESTIMATE`, `QUARTERLY_RESULT`), FastAPI `GET /compare`, 나란히 정렬 엔진 구현.
8. **도표 비교 매칭 규칙 고도화**: 공백 제거, 연간 실적 추정 연도(`2026E` 등) 검증, 분기 실적 캡션 우선 및 기간 라벨 폴백, 오탐 제외 키워드 필터링 적용.

---

## 4. 팀장 결정 기록 (Decisions)

1. **파일명 우선 메타데이터**: 파일명(`RPT_YYYYMMDD_종목_증권사.pdf`)에 명시된 발행일자, 증권사, 종목명을 표지 텍스트나 LLM 추출값보다 최우선 적용. 증권사 자리가 '미확인'인 경우에만 LLM에 위임.
2. **CAP_LIMIT 문서에 한한 v2 재색인 허용 (사전 스냅샷 필수)**: `compare_matrix.json`에서 `reason=CAP_LIMIT`으로 판정된 문서(23건)에 한해 `--max-elements 8`로 재색인 허용. 사전 Qdrant 스냅샷 필수 생성(`figindex_elements_v2-1851693946944154-2026-11-17-03-32-47-0.snapshot` 생성 완료) 및 새 포인트 검증 성공 시에만 원자적 교체 삭제.
3. **TARGET_PRICE 표 우선순위**: 캡션에 `{산출, 산정, 적정주가}`가 있는 표를 1순위(`rank=3`)로 채택하고, '요약' 박스형 표는 산출표가 없을 때만 대안(`rank=1`)으로 선택.
4. **결정론적 Sparse 토큰(crc32) 및 고정 Point ID 전환, v2 재계산 쓰기 예외 허용 (2026-11-17)**: `PYTHONHASHSEED`에 따라 달라지던 `hash()` 기반 sparse 토큰과 point ID를 각각 `zlib.crc32` 및 `uuid.uuid5` 기반으로 전환. 사전 Qdrant 스냅샷(`figindex_elements_v2-1851693946944154-2026-11-17-06-28-08-3.snapshot`) 생성 후 v2 컬렉션 622건 sparse 벡터 전량 교체 완료(실패 0건).
5. **중복 포인트 4건 정리 허용 (2026-11-17, v2 쓰기 예외)**: (doc_name, page_number, caption)이 중복된 4개 그룹(그린광학 p.3, BGF리테일 p.2 2건, 롯데렌탈 p.2)에서 bbox 면적이 작은 포인트 4건 선별 삭제 완료(삭제 전 이력 보존: `data/migration/dedup_20261117.csv`).
6. **종목 키 표준 extra_metadata.target 확정 및 31건 백필 허용 (2026-11-17, v2 쓰기 예외)**: 종목 키의 표준을 `extra_metadata.target`으로 확정. v2 컬렉션 618건 중 `target`이 비어있던 31건에 대해 `company` 값을 `target`에 채워 넣음(기존 company 보존). 스크립트 4종(`make_compare_pairs.py`, `service.py`, `check_extraction.py`, `fix_metadata_from_filename.py`)이 target을 우선 읽도록 수정.

---

## 5. 열린 문제·넘길 일 (Open Issues)

| 문제 / 이슈 | 담당 | 상태 | 상세 내용 |
| :--- | :---: | :---: | :--- |
| **KB금융·우리금융지주 도표 0개** | 파이프라인 | 열림 | 텍스트 중심 리포트로 도표 추출이 0건이므로 본문 요약 테이블 추가 추출 또는 예외 처리 필요 |
| **table_data None 표 (코스맥스·유진 p.4, 카카오·SK p.1)** | 파이프라인 | 열림 | 크롭 이미지는 존재하나 표 파싱 데이터가 누락된 포인트에 대한 재추출/보정 필요 |
| **A8 단위 테스트 검사** | 인프라/테스트 | 해결 완료 | Docker 환경 pytest 156건 전량 통과 (PASS=6, FAIL=0 달성) |
| **CAP_LIMIT 문서 재색인 실행** | 파이프라인 | 대기 | 팀장 결정으로 승인된 23건 CAP_LIMIT 대상 문서에 대해 `ingest_missing.py --reindex-from` 실제 구동 대기 |
| **MetricType의 schemas.py 이전 검토** | 백엔드/스키마 | 검토 중 | `compare/metrics.py`의 `MetricType` Enum을 표준 스키마(`shared/schemas.py`)로 공식 승격할지 여부 |
| **잘못된 크롭 (KT&G 유안타 p.10)** | 크롭 | 열림 | 동일 캡션(추정재무제표)에 대해 서로 다른 크롭 박스가 생성된 중복 건으로 크롭 범위 점검 필요 |
| **캡션 오배정 (HeritageJ p.2)** | 오분류·정답셋 | 열림 | 동일 캡션(그림 2 <아리랑 고개> 서명 부분)이 2개 요소에 부여된 건으로 정답셋/캡션 보정 필요 |

---

## 6. 알려진 함정 (Known Pitfalls)

1. **PowerShell에서 `&&` 사용 불가**: 세미콜론(`;`)을 사용하거나 별도 명령으로 분리 실행.
2. **100MB 초과 파일 Git push 불가**: Qdrant 스냅샷 및 `data.zip` 등 대용량 파일은 `.gitignore`에 등록하여 관리.
3. **문서당 도표 상한 기본값 4 (`--max-elements 4`)**: 기본 상한으로 인해 후반부 중요 표(3Q Review, Valuation 등)가 누락되는 CAP_LIMIT 발생 주의.
4. **Gemini 무료 티어 분당 14회 (15 RPM 제한)**: 공용 `GeminiRateLimiter(max_rpm=14.0)`를 경유하지 않는 임의 병렬 호출 시 429 ResourceExhausted 발생.

---

## 7. 기준 파일·실행 환경

### 5대 기준 파일 (Single Source of Truth)
1. **`figindex/shared/schemas.py`**: 프로젝트의 유일한 표준 스키마 기준 (`Element`, `ElementSearchPayload`, `TableData`, `ConfidenceSignals`, `Document`, `Batch`, `ReviewLog` 등 11개 표준 모델 및 Enum).
2. **`figindex/shared/coords.py`**: 바운딩 박스 정규화 `[x0, y0, x1, y1]`(좌상단 원점, 0~1) 및 좌표 변환(pt/px, IoU, 패딩)의 유일한 계산 기준.
3. **`docs/glossary.md`**: 표 셀 수치 규칙(7절), 좌표계(8절), 단위 규칙 4원칙(9절), 확신도 가중치(10절), 평가 지표(12절)의 정의 기준.
4. **`AGENTS.md`**: 쓰지 않는 이름 표(2절), schemas.py 필드명 준수, 수정 금지 파일 등 AI 에이전트의 절대 행동 규칙.
5. **`figindex/pipeline/pdf_text.py`**: 증권 리포트 글자 드로잉 순서 꼬임을 해결하기 위해 PDF 텍스트 레이어를 2차원 좌표 순서로 정렬하여 읽는 단일 추출 함수 기준.

### 실행 환경 (`figindex/docker-compose.yml`)
- `figindex-qdrant`, `figindex-backend`, `figindex-frontend` 3개 서비스가 로컬 Docker에서 가동 (`QDRANT_MODE=server`, `QDRANT_COLLECTION=figindex_elements_v2`).
- `pipeline` 서비스는 `profiles: ["index"]`로 분리되어 독립 컨테이너 실행 지원.

---

## 8. 로드맵 (Roadmap)

- **1단계 (진행 중)**: `compare_matrix.json` 23건 CAP_LIMIT 대상 문서 재색인 및 매칭 완성도 극대화.
- **2단계**: DocLayout-YOLO 파이프라인 정식 이식 및 본 크로퍼 연동.
- **3단계**: 확신도 5개 신호 정규화(`pdf_text.py` 2차원 좌표 정렬 텍스트 기반) 및 ReviewLog 누적 불변화.
- **4단계**: 지표·기간 정규화 사전 엔진 탑재 및 프론트엔드 나란히 비교 UI 정식 연동.
