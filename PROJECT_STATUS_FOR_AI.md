> 이 문서는 덧붙이지 말고 매번 전체를 다시 쓴다.

# FigIndex 프로젝트 종합 현황서 (AI 분석·인수인계용)

---

## 0. 지금 상황 (Current Status)

1. **현재 단계**: 11-19 저녁. 업로드→파이프라인 연결의 서버 쪽 구현 완료(`feat/upload-pipeline`, PIPELINE_VERSION 0.1.3), 검수 단축키 병합(PR #38), 검수 EDIT 오기록 버그 수정, 시험 컬렉션 스크립트 병합(PR #39). 내일(11/20) 배포
2. **방금 한 일과 결과 (2026-11-19 오후)**: 작업자로 미색인 5건 처리 성공(휴머노이드 27쪽 도표 10개 313.7초, KB금융·우리금융지주·OECD 보도자료 0개는 원래 도표 없음). 드론 논문 0개는 `Fig. N.` 캡션을 규칙이 못 읽어서였고, 캡션 위 이미지를 묶는 규칙을 넣어 후보 0 → 4(3·4·6·7쪽). pipeline 테스트 226건 통과. 목차 거르기 반려 17건 중 16건 건너뜀, 카드 있는 정답 표 14개 중 0개 건너뜀
3. **다음 할 일 (11/20)**: 배포 순서 `ryu` → main → `feat/upload-pipeline` → main(충돌 미리 해결함). 팀장 PC에서 `register_existing_pdfs`, 검수 탭 A키 승인이 ReviewLog에 APPROVE로 남는지 확인, 팀원에게 `figindex_data_20261119.zip` 안내
4. **막힌 것**: 없음
5. **팀장 결정 대기**: ① `main.py`의 비교 응답 모델 3개(`MatchedDocComparison`, `AlignedComparisonRow`, `CompareApiResponse`)와 `MetricType`을 `schemas.py`로 옮길지

---

## 1. 핵심 숫자 (Key Metrics)

> 아래 표는 `python scripts/update_status.py`가 자동으로 다시 쓴다. 측정 시각이 11-17이면 아직 갱신 전이다.

<!-- AUTO:START -->
| 항목 | 측정값 | 측정 시각 |
| :--- | :--- | :--- |
| **Git 브랜치** | `ryu` | 2026-11-19 12:03:05 KST |
| **Git 최신 커밋** | `43345c9 - docs: 현황서 11-19 낮 — 수치 정답셋 첫 측정, 요소 없음 원인(색인 한도), 결정 18·19, PR #37` | 2026-11-19 12:03:05 KST |
| **Git 미커밋 변경 파일** | `1개 파일` | 2026-11-19 12:03:05 KST |
| **Qdrant 컬렉션 (`v2`) 포인트** | `618` (승인: `593`, 검수대기: `8`, 반려: `17`) | 2026-11-19 12:03:05 KST |
| **Qdrant 색인 고유 문서** | `136개 문서` | 2026-11-19 12:03:05 KST |
| **원문 PDF 총계** | `141개 PDF` | 2026-11-19 12:03:05 KST |
| **미색인 원문 PDF 목록** | 5건: RPT_20261105_KB금융_미확인.pdf, RPT_20261105_우리금융지주_미확인.pdf, 논문_20260825_드론자력탐사오차보정_Geophysics.pdf, 보고서20261111휴머노이드로봇RD투자전략개방형_한국과학기술기획평가원.pdf, 보도자료_20260702_OECD한국경제보고서_재정경제부.pdf | 2026-11-19 12:03:05 KST |
| **동일 종목 비교 그룹** | `10개 그룹` (`compare_pairs.json`) | 2026-11-19 12:03:05 KST |
| **도표 비교 매칭 성공** | 총 69건 (TARGET_PRICE: 15건, ANNUAL_ESTIMATE: 28건, QUARTERLY_RESULT: 26건) | 2026-11-19 12:03:05 KST |
| **도표 비교 미매칭 원인** | 총 21건 (ABSENT: 8건, KEYWORD_MISS: 13건) | 2026-11-19 12:03:05 KST |
| **상태 검사기 (`check_state`)** | `PASS=7  WARN=1  CHANGED=0  FAIL=0  SKIP=0` | 2026-11-19 12:03:05 KST |
| └ **검사 경고(WARN) 항목** | A6. 모델 중복 정의 | 2026-11-19 12:03:05 KST |
| └ **검사 생략(SKIP) 항목** | 없음 | 2026-11-19 12:03:05 KST |
| └ **검사 실패(FAIL) 항목** | 없음 | 2026-11-19 12:03:05 KST |
<!-- AUTO:END -->

수동 기록 (2026-11-19 17:10)
- v2 618건: 승인 593, 검수대기 8, 반려 17 (반려는 오분류 점검 '요소 아님', 백업 `reject_backup_*.json`)
- 업로드 DB `data/metadata.sqlite3` (팀장 PC, 11-19 16:20): 141건 모두 COMPLETED. 그중 5건은 작업자가 0.1.3으로 처리(`extra_metadata.element_count`: 휴머노이드 10, 나머지 0), 결과는 시험 컬렉션 `figindex_test_upload`에만 있음
- 검색 정식 측정 (11-18, `eval_search.py`, 검색어 20개): `precision_at_5` 0.900, `search_latency_sec` 0.314. 기업명+지표 검색(1~3번)은 0.6·0.5·0.4로 가장 낮음
- 엔티티 사전 `figindex/data/entity_dictionary.csv`: 65개 (종목 50, 기관 9, 제품 6), 종목은 한국거래소 종목명 기준
- 오분류 점검 88건 완료: 맞음 56, 틀림 32 (요소 아님 17, 잘림 13, 캡션 3, 노이즈 1, 유형 0)
- 표 평가 (11-19 12:00, `eval_tables.py`): `table_valid_rate` 0.998 (488/489, 실패 fig-437d261937fb 표 없음), 저장 규칙 위반 표 2/489, `cell_accuracy` 0.592 (468/790), `gt_table_coverage` 0.467 (14/30), `cell_accuracy_extracted` 1.000 (468/468)
- 수치 정답셋: `figindex/data/gt/table/cells.csv` 표 30개(T01~T30), 숫자 셀 790개. 연결 `links.csv` 30/30 (같은 표 14, 요소 없음 16)
- 테스트 (11-19 17:00, 팀장 PC Docker): pipeline 226건 통과(`feat/upload-pipeline`), 백엔드 업로드 DB 15건 통과, 검수 비교 7건 통과

---

## 2. 최근 작업 로그 (Recent Logs - 최근 5건)

| 시각 | 작업 요청 | 바꾼 파일 | 실행 명령 | 결과 숫자 | 판정 |
| :---: | :--- | :--- | :--- | :--- | :---: |
| **11-19 17:00** | 도표 0개 문서 원인 확인, 논문식 `Fig. N.` 캡션 그림 찾기 (`feat/upload-pipeline`, 0.1.3에 포함) | `scripts/diagnose_zero_elements.py`, `pipeline/cropper.py`, `pipeline/test_fig_caption.py`, `pipeline/pdf_text.py`(0.8 리터럴을 정수 비교로) | `diagnose_zero_elements.py 드론자력탐사 OECD한국경제보고서`, `pytest -q` | 드론 논문 후보 0 → 4, OECD는 원문에 표·그래프 없음(정상), 226건 통과 | **PASS** |
| **11-19 17:02** | PR #39 병합 (팀원3 시험 컬렉션 생성 스크립트) | `scripts/create_test_review_collection.py` | — | 대상 이름 검사: v1·v2·`figindex_test_upload`·원본과 같은 이름이면 중단(팀장 검토 때 `figindex_test_upload` 추가), 병합 `00ef508` | **PASS** |
| **11-19 15:24** | 검수 승인이 EDIT로 기록되던 버그 수정 (팀원1 단축키 시험에서 발견) | `backend/app/main.py`, `backend/app/review_compare.py`, `backend/app/test_review_compare.py` | `python -m unittest backend/app/test_review_compare.py` | 7건 통과. 고치지 않은 표·빈 캡션이 형식 차이로 '바뀜'으로 잡히던 것 | **PASS** |
| **11-19 15:14** | PR #38 병합 (팀원1 검수 탭 A/R 단축키) | `frontend/app/components/ReviewTab.tsx` | — | 34줄, 팀원1이 시험 컬렉션에서 3건 확인, 병합 `be645c2`. 같은 기능의 팀원3 `sun` 브랜치는 v2 검수를 막는 코드가 있어 병합하지 않음 | **PASS** |
| **11-19 14:23** | 업로드→파이프라인 연결 서버 쪽 구현 (`feat/upload-pipeline`) | `shared/upload_db.py`, `pipeline/worker.py`, `pipeline/orchestrator.py`(`index_document`), `pipeline/pdf_text.py`(목차 판단), `shared/schemas.py`(0.1.3), `backend/app/main.py`(retry API), `backend/app/upload_store.py`, `docker-compose.yml`(worker), 테스트 | `pytest`, `check_toc_filter.py`, 작업자 실제 처리 | 목차 거르기 16/17·정답 표 0/14, 미색인 5건 처리, 테스트 통과 | **PASS** |

---

## 3. 완료 이력 (Historical Summary)

1. **단일 스키마 기준 확립**: `shared/schemas.py`, `coords.py` 중심으로 스키마 단일화, 엄격 금지 이름 0건.
2. **백엔드/프론트엔드 v2 전환**: 백엔드 컬렉션 기본값 `figindex_elements_v2`, `CONFIDENCE_THRESHOLD` 적용, 프론트 타입 연동.
3. **파이프라인 새 스키마 전환**: `orchestrator`, `extractor`, `evaluator` 구 스키마 제거, `schemas_legacy.py` 삭제.
4. **동일 종목 비교쌍 (`compare_pairs.json`)**: 10개 종목 그룹(30개 문서).
5. **파일명 우선 메타데이터**: `parse_rpt_filename()`로 `RPT_YYYYMMDD_종목_증권사.pdf` 파싱.
6. **Rate Limiter·원자적 색인 (`ingest_missing.py`)**: 분당 14회 공용 `GeminiRateLimiter`, 문서 단위 upsert·롤백.
7. **비교 엔진 2종**: ① 비교 화면용 `shared/compare.py` + `GET /api/compare`, `/api/compare/metrics` ② 종목·지표 매칭 엔진 `figindex/compare/` + `GET /api/compare/company`.
8. **결정론적 sparse·point id (crc32/uuid5)**, v2 sparse IDF modifier 켬.
9. **검색 (팀원2)**: Kiwi 형태소 + BM25 sparse + dense 하이브리드, 엔티티 사전 65개, `/api/search` 필터, 검색 정답셋, `scripts/eval_search.py`.
10. **표 파싱 정리 (0.1.1~0.1.2)**: `pipeline/table_parse.py`의 `coerce_table_data`, `parse_cell_value`(`.802` 포함), `align_row_keys`(공백만 다른 행 키).
11. **데이터 작업 도구 (dry-run 기본, 백업·되돌리기)**: `reextract_empty_tables.py`, `promote_test_to_service.py`, `fix_metadata_from_filename.py`, `restore_tables_from_v1.py`, `list_review_candidates.py`, `diagnose_empty_tables.py`, `recoerce_tables.py`.
12. **PDF 묶음 업로드 (팀원1)**: `POST /api/batches`, 화면 '📄 PDF 업로드' 탭(여러 PDF, 상태·진행률 표시), SHA-256 `doc_hash` 중복 판정, 기존 PDF 등록(`register_existing_pdfs`, #37), ReviewLog 저장(#36).
13. **표지 기반 메타데이터 (11-18, #35)**: 파일명 형식이 아니면 표지에서 종목·증권사·발행일을 찾음. 못 찾으면 None.
14. **표 평가 (11-19)**: `scripts/eval_tables.py`. `table_valid_rate`, `cell_accuracy`, 보조 지표 `gt_table_coverage`·`cell_accuracy_extracted`. 행·열 이름은 NFKC·따옴표 통일 후 비교.
15. **예전 표 저장 형태 정리 (11-19)**: 297개 + 0.1.2 후 8개.
16. **업로드→파이프라인 연결 (11-19, `feat/upload-pipeline`)**: 백엔드는 `UPLOADED`로 등록만, pipeline 이미지의 작업자(`pipeline/worker.py`, compose 프로필 `worker`)가 업로드 DB에서 가장 오래된 `UPLOADED` 1건씩 `PROCESSING` → `COMPLETED`/`FAILED`. 함수는 `shared/upload_db.py`(`claim_next_document`, `mark_document_completed`, `mark_document_failed`, `reset_processing_documents`, `retry_document`)와 `orchestrator.index_document(pdf_path, doc_id)`. 작업자는 파일 내용(`doc_hash`)을 확인하고, 업로드 DB의 `doc_id`를 Qdrant에 그대로 씀. `POST /api/documents/{doc_id}/retry`(FAILED만, 404/409). 설계서: Claude 문서 '업로드→파이프라인 연결 설계 (팀장 지시서)'.
17. **목차 거르기 (0.1.3)**: `pdf_text.is_toc_page` — 점선 지시줄, 목차 제목 + 쪽번호 줄, 번호 항목 위주 페이지. `scripts/check_toc_filter.py`로 확인.
18. **논문식 캡션 (0.1.3)**: 블록 맨 앞 `Fig. N.` 캡션이면 캡션 바로 위 이미지와 위로 쌓인 칸을 묶어 CHART 후보. 기존 `그림`·`Figure` 규칙은 그대로.
19. **검수 단축키 (팀원1, #38)**: 검수 탭 A 승인, R 반려, 입력 칸에서는 동작 안 함.
20. **검수 변경 판단 (11-19)**: `backend/app/review_compare.py`. 저장값도 `TableData`로 맞춘 뒤 비교, 캡션 None과 ""는 같게 봄. 실제로 바뀐 경우에만 덮어쓰고 EDIT로 기록.

---

## 4. 팀장 결정 기록 (Decisions)

1. **파일명 우선 메타데이터**: 파일명의 발행일자·증권사·종목명을 표지·LLM 값보다 우선. 증권사가 '미확인'일 때만 LLM에 위임.
2. **CAP_LIMIT 문서 v2 재색인 허용 (사전 스냅샷 필수, 11-17)**: 23건 한정, `--max-elements 8`.
3. **TARGET_PRICE 표 우선순위**: 캡션에 산출·산정·적정주가가 있는 표 1순위, 요약 박스형은 대안.
4. **결정론적 sparse 토큰·고정 point id 전환 (11-17)**: v2 622건 sparse 교체(사전 스냅샷 생성).
5. **중복 포인트 4건 삭제 (11-17)**: 이력 `data/migration/dedup_20261117.csv`.
6. **종목 키 표준 `extra_metadata.target` (11-17)**: 빈 target 31건 백필.
7. **비교 수치 정답셋 1차본 28건 (11-17)**: `data/eval/compare_numbers_check.csv`.
8. **v2 쓰기는 시험 컬렉션을 거친다 (11-18)**: 재추출은 `figindex_test_<이름>`에만 쓰고, 미리보기 확인 후 `promote_test_to_service.py --apply`(백업 자동)로 v2에 반영.
9. **종목명은 엔티티 사전의 entity_name으로 저장 (11-18)**.
10. **PIPELINE_VERSION 0.1.0 → 0.1.1 (11-18)**: 표 파싱·캐시 후처리 변경.
11. **ryu → main 통합 (11-18)**: ryu 브랜치는 계속 사용. `/api/compare`는 비교 화면용 엔진, ryu 엔진은 `/api/compare/company`.
12. **저장소 정리 (11-18)**: 병합된 PR 브랜치 자동 삭제 설정 켬. 데이터 zip에 entity_dictionary.csv를 넣지 않음(git 관리).
13. **'요소 아님' 17건 반려 (11-18, v2 쓰기)**: 목차·장 제목·초록으로 판정된 요소. 확신도 신호가 목차를 거르지 못함.
14. **현황서 갱신 규칙 (11-18)**: AGENTS.md 8절.
15. **업로드 파일 이름 규칙을 강제하지 않음 (11-18)**: 표지에서 메타데이터를 찾고, 못 찾으면 비워 둔다.
16. **예전 표 297개 저장 형태 정리 (11-19, v2 쓰기)**: 숫자 문자열 15,123칸을 숫자로. pipeline_version은 그대로.
17. **PIPELINE_VERSION 0.1.1 → 0.1.2 (11-19)**: ① 표지 기반 메타데이터(#35) ② `.802` 소수 ③ 공백만 다른 행 키.
18. **수치 정답셋 측정 방식 (11-19)**: `cell_accuracy`는 용어집 정의대로, 보조 지표 `gt_table_coverage`·`cell_accuracy_extracted`를 함께 보고(용어집 12절). 정답 표는 추출 결과에 맞춰 바꾸지 않는다.
19. **색인 한도 조정과 재색인은 다음 주 (11-19)**: 요소 없음 16개의 원인은 `run_index.py` 기본값(앞 12쪽, 도표 4개). 11/25~26에 0.1.3 규칙으로 13개 문서 재색인.
20. **업로드 처리는 별도 작업자 (11-19)**: 백엔드 `BackgroundTasks`가 아니라 pipeline 이미지의 작업자가 처리(백엔드 이미지에 PyMuPDF·Gemini 없음). 한 번에 1건, 자동 재시도 없음(실패는 [다시 시도]로만), 도표 0개도 `COMPLETED`(`element_count` 0). 작업자는 필요할 때만 켜고(`docker compose --profile worker up -d worker`), 기본 저장 컬렉션은 `figindex_test_upload`, 서비스 전환 때만 `WORKER_COLLECTION=figindex_elements_v2`. 서버·DB·파이프라인·작업자는 팀장, 팀원1은 업로드 화면만.
21. **PIPELINE_VERSION 0.1.3 (11-19)**: 목차 거르기, 업로드 문서 전체 쪽·도표 40개, doc_id 그대로 사용, 논문식 `Fig. N.` 캡션. `Fig.` 캡션은 0.1.3이 아직 main·서비스에 쓰이지 않아 버전을 올리지 않고 0.1.3에 포함(팀장 결정). 0.1.3으로 처리된 것은 시험 컬렉션 5건뿐.
22. **재색인은 기존 요소를 유지하고 빠진 요소만 추가 (11-19)**: `element_id`는 색인할 때마다 무작위(`cropper.py` uuid)라, 문서를 통째로 다시 색인하면 수치 정답셋 연결 14개가 깨진다. 팀원3은 재색인 뒤 '요소 없음' 16행만 다시 확인.
23. **브랜치 정리 원칙 (11-19)**: 병합 후 지우는 것은 팀장 브랜치뿐이고, 팀원 개인 브랜치는 남긴다. 단 `sun`(v2 검수를 막는 보호 코드 포함)과 `seung-test-collection-guard`(PR #39와 중복)는 병합하지 않는다.
24. **검수 단축키는 팀원1 버전 (11-19)**: 같은 기능이 두 벌(팀원1 #38, 팀원3 `sun`) 올라와 #38을 병합.

---

## 5. 열린 문제·넘길 일 (Open Issues)

| 문제 / 이슈 | 담당 | 상태 | 상세 내용 |
| :--- | :---: | :---: | :--- |
| **업로드 화면 남은 2가지** | 업로드(팀원1) | 열림 | 완료 문서에 `element_count`("도표 N개"/"도표 없음"), 실패 문서에 [다시 시도](`POST /api/documents/{doc_id}/retry`, 409면 사유 표시). 11/20 배포 뒤 main에서 새 브랜치, 목표 11/24 |
| **색인 한도로 뒤쪽 표 누락** | 파이프라인 | 진행 중 | 수치 정답셋 30개 중 16개 카드 없음. 0.1.3 규칙(전체 쪽, 도표 40개, 목차 거르기)으로 11/25~26 재색인(결정 19·22). 드론 논문도 재색인 대상(지금 COMPLETED 0개라 [다시 시도] 불가) |
| **드론 논문 `Fig.` 크롭 영역 확인** | 파이프라인 | 열림 | 후보 4개는 확인, 잘린 영역이 그림을 정확히 감싸는지는 재색인 후 카드로 확인 |
| **HWP 변환 PDF의 이미지 조각** | 파이프라인 | 참고 | OECD 보도자료는 쪽마다 이미지 100~200개(장식·글자 조각)였고 원문에 표·그래프 없음. 이런 문서에 실제 표가 있으면 캡션 규칙으로 못 잡음 → YOLO 검토 대상 |
| **목차 페이지가 표로 잘림** | 파이프라인 | 해결(0.1.3) | 반려 17건 중 16건 건너뜀, 정답 표 0/14 손실. 기존 v2 카드에는 재색인 때 반영 |
| **검수 승인이 EDIT로 기록** | 백엔드 | 해결 | `review_compare.py` (11-19). 배포 뒤 A키 승인이 APPROVE로 남는지 확인 |
| **빈 표 1건 (BERT p.8, fig-437d261937fb)** | 정답셋 | 열림 | 실제 표가 있으나 캡션 틀림, 표 데이터 없음. 검수대기 |
| **오분류 '잘림'(제목·단위·주석) 다수** | 크롭(팀원4) | 열림 | 틀림 32건 중 잘림 13건. 크롭 여백 비교 자료 |
| **비교 응답 모델·MetricType의 schemas.py 이전** | 백엔드/스키마 | 결정 대기 | check_state A6 경고 원인 |
| **엔티티 정규화 (AGENTS.md 5절)** | 파이프라인 | 일부 완료 | 색인 시 entities 전체를 사전으로 바꾸는 처리는 아직 |
| **기업명+지표 검색 약함** | 검색(팀원2) | 열림 | 1~3번 검색어 0.4~0.6. 다음 주 검색 개선 우선순위 |
| **증권사 목록이 코드에 있음** | 파이프라인 | 열림 | `BROKER_ALIASES` → 사전으로 옮길지 검토 |
| **CAP_LIMIT 문서 재색인 실행** | 파이프라인 | 대기 | 승인된 23건. 결정 19 재색인과 합칠지 확인 |
| **잘못된 크롭 (KT&G 유안타 p.10)** | 크롭 | 열림 | 같은 캡션에 다른 크롭 박스 |
| **캡션 오배정 (HeritageJ p.2)** | 정답셋 | 열림 | 같은 캡션이 2개 요소에 |
| **표 셀 값이 문자열로 남은 2개** | 파이프라인 | 열림 | fig-38347d0364c8(SK텔레콤 SK p.1), fig-ebfa3b5c97da(삼성전자 IBK p.4). columns에 없는 열에 값. 원문 확인 후 재추출 또는 수동 수정 |
| **섞인 단위 문자열 (`unit: '십억원, %'`)** | 파이프라인 | 열림 | `unit_for`가 % 아닌 행에 '십억원, %'를 돌려줌. 비교 엔진 단위 환산 영향 확인 필요 |
| **정답값 원문 대조** | 정답셋(팀원3) | 열림 | `cell_accuracy_extracted` 1.000이라 정답셋이 AI 결과를 보고 만들어지지 않았는지 원문 PDF로 표 2~3개 확인 |
| **check_state 테스트 2건 실패** | 인프라 | 열림 | `test_check_state_a2.py`의 legacy_allowed_files 2건 (Docker 밖 실행 시) |
| **doc_latency_sec 목표** | 파이프라인 | 열림 | 용어집 ≤ 15초(10쪽)는 Gemini 분당 14회 한도로 도표 3개 넘으면 불가. 실측 휴머노이드 27쪽 도표 10개 313.7초. 목표 재설정 필요 |

---

## 6. 알려진 함정 (Known Pitfalls)

1. **PowerShell에서 `&&` 사용 불가**: `;` 또는 줄 나눠 실행. `python -c` 안에 `\"`와 `$`를 쓰지 않는다.
2. **100MB 초과 파일 Git push 불가**: 스냅샷·zip은 저장소 밖(`C:\workAi\figindex_work`)에 둔다.
3. **색인 한도**: `run_index.py` 기본값은 앞 12쪽·도표 4개(0.1.2까지). 업로드 작업자(`index_document`)는 전체 쪽·도표 40개.
4. **Gemini 무료 티어 분당 14회**: 공용 `GeminiRateLimiter`는 프로세스마다 따로다. 작업자가 도는 동안 `run_index.py`나 재추출 스크립트를 함께 돌리면 합산 한도를 넘으므로 `docker compose stop worker` 후 실행.
5. **승격 후 메타데이터 보정 순서**: `promote_test_to_service.py`는 payload 전체를 덮어쓴다. 메타데이터 보정은 승격 뒤에.
6. **확신도가 높아도 요소가 아닐 수 있음**: 목차 페이지도 0.95까지 나왔다(0.1.3에서 거름). 대량 반영 후에는 오분류 점검.
7. **Windows 콘솔 cp949**: 파이썬에서 git을 부를 때 `encoding="utf-8"`.
8. **git pull 실패·브랜치 꼬임**: 로컬 브랜치가 원격과 갈라지면 pull이 충돌로 멈춘다(11-19 팀장 PC `ryu`). 로컬 작업이 원격에 다 있으면 `git merge --abort` 후 `git switch -C <브랜치> origin/<브랜치>`. 받은 스크립트·zip은 저장소 밖에.
9. **실행 위치**: `scripts\*.py`는 저장소 루트, `docker compose`는 `figindex/`에서.
10. **PowerShell 한글 깨짐**: Windows PowerShell 5.1은 BOM 없는 UTF-8과 REST 응답 한글을 깨뜨려 보여 준다(데이터는 정상).
11. **Gemini 캐시를 끄지 않는다** (`extractor.py`).
12. **작업자는 `-d`로 켠다**: `docker compose up`을 앞에 띄운 채 Ctrl+C를 누르면 모든 컨테이너가 멈춘다. 멈췄으면 `docker compose up -d`.
13. **pipeline 이미지는 코드를 복사해 둔다**: pull 뒤 `docker compose --profile index build pipeline`을 하지 않으면 예전 코드로 돈다. 테스트 수(11-19 기준 226)로 확인.
14. **`init_collection.py`는 새 컬렉션을 만들 때 `/data/crops`를 비운다**: 시험 컬렉션은 작업자나 `create_test_review_collection.py`로 만든다.
15. **도표 찾기 규칙의 한계**: 지금 파이프라인은 YOLO가 아니라 PyMuPDF 표 탐지 + 캡션 규칙(`그림 N.`, `Figure N.`, `Fig. N.`)이다. `<그림 1>`, `[표 1-1]`, 선 없는 표, 이미지 조각으로 된 표는 놓칠 수 있다. 도표 0개 문서는 `scripts/diagnose_zero_elements.py`로 확인.

---

## 7. 기준 파일·실행 환경

### 5대 기준 파일 (Single Source of Truth)
1. **`figindex/shared/schemas.py`**: 유일한 표준 스키마 (`Element`, `ElementSearchPayload`, `TableData`, `ConfidenceSignals`, `Document`, `Batch`, `ReviewLog`, `ComparisonResult` 등).
2. **`figindex/shared/coords.py`**: bbox `[x0, y0, x1, y1]`(좌상단 원점, 0~1)와 좌표 변환.
3. **`docs/glossary.md`**: 확신도 신호(6절), 메타데이터(7절), 좌표(8절), 표 수치 저장 규칙(9절), 엔티티 사전(10절), 평가 지표(12절), 문서 간 비교(14절).
4. **`AGENTS.md`**: 쓰지 않는 이름(2절), 수정 금지 파일(7절) 등. 파이프라인은 `figindex/pipeline/AGENTS.md`, 백엔드는 `figindex/backend/AGENTS.md`도 따른다.
5. **`figindex/pipeline/pdf_text.py`**: PDF 글자 읽기와 목차 판단(`is_toc_page`).

### 실행 환경 (`figindex/docker-compose.yml`)
- `figindex-qdrant`, `figindex-backend`, `figindex-frontend` (`QDRANT_COLLECTION=figindex_elements_v2`).
- `pipeline` 서비스는 `profiles: ["index"]`, `worker` 서비스는 `profiles: ["worker"]`(`feat/upload-pipeline`, 11/20 배포 후 main).
- Qdrant: 서비스 `figindex_elements_v2`(618), 구버전 `figindex_elements`(525), 시험 `figindex_test_upload`(작업자 결과), `figindex_test_coerce`, `figindex_test_review`. v2·v1 쓰기는 팀장 승인 필요. 데이터 zip은 `figindex_test_*`를 넣지 않는다.
- 브랜치: `main`(배포), `ryu`(팀장 작업), `feat/upload-pipeline`(팀장, 11/20 병합 후 삭제). 팀원 개인 브랜치는 남긴다(결정 23).
- 관리자 검수 API: `POST /api/review/{element_id}` (헤더 `X-Admin-Password`). 처리할 때마다 ReviewLog 1줄 추가. 다시 시도 API: `POST /api/documents/{doc_id}/retry` (`docs/migration/api_changes.md` 8절).

---

## 8. 로드맵 (Roadmap)

- **11/20(금)**: 배포(ryu → main → `feat/upload-pipeline` → main), 팀장 PC `register_existing_pdfs`, 시험 컬렉션에서 업로드 연결 확인, 팀원 데이터 zip 안내.
- **11/23~24**: 팀원1 업로드 화면 2가지, 팀원4 합류(크롭·YOLO 비교).
- **11/25~26**: 0.1.3 규칙으로 13개 문서 + 드론 논문 재색인(기존 요소 유지, 결정 22), 수치 정답셋 다시 측정(`gt_table_coverage`), 팀원3 '요소 없음' 16행 재연결, 정답값 원문 대조.
- **11/27**: 기능 개발 마감, 업로드 작업자 서비스 v2로 전환.
- **11/30~12/2**: 지표 측정·버그 수정.
- **12/3**: 시연 리허설.
