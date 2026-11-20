> 이 문서는 덧붙이지 말고 매번 전체를 다시 쓴다.

# FigIndex 프로젝트 종합 현황서 (AI 분석·인수인계용)

---

## 0. 지금 상황 (Current Status)

1. **현재 단계**: 11-20 저녁. A안(표 행·열 이름을 검색 벡터에 반영) 코드·데이터 적용 완료, PR #42(검색 재정렬)·#43(업로드 화면) 병합, 새 데이터 zip(`figindex_data_20261120.zip`) 배포. `ryu`를 main에 올리는 중(A안 코드)
2. **방금 한 일과 결과 (2026-11-20)**: v2 표 500개 벡터를 `reembed_table_vectors.py --apply`로 다시 계산(payload·point id 그대로, 618건 유지). 검색 정답셋 20개 `precision_at_5`: main 0.900 → A만 0.932 → A+B(재정렬) **0.945**. 1~3번 뺀 17개는 네 경우 모두 0.971, 떨어진 검색어 0개
3. **다음 할 일**: ① 팀장 PC에서 `python scripts/update_status.py`로 1절 숫자 갱신 ② 팀원2 튜닝용 검색어 10개 추가 후 A+B 대 B만·`RERANK_SHIFT` 재평가(팀원2·팀원3 두 명 판정) ③ 0.1.3 재색인(기존 요소 유지) 뒤 데이터 zip 한 번 더 ④ 팀원4 합류(크롭·YOLO 비교)
4. **막힌 것**: 없음
5. **팀장 결정 대기**: ① `main.py`의 비교 응답 모델 3개(`MatchedDocComparison`, `AlignedComparisonRow`, `CompareApiResponse`)와 `MetricType`을 `schemas.py`로 옮길지

---

## 1. 핵심 숫자 (Key Metrics)

> 아래 표는 `python scripts/update_status.py`가 자동으로 다시 쓴다. 측정 시각이 11-20 16:29이면 아직 갱신 전이다(이 문서는 팀장 PC 밖에서 다시 썼다).

<!-- AUTO:START -->
| 항목 | 측정값 | 측정 시각 |
| :--- | :--- | :--- |
| **Git 브랜치** | `ryu` | 2026-11-20 16:29:20 KST |
| **Git 최신 커밋** | `34a5720 - feat: 색인 글자에 표 행·열 이름 추가 (A안 1단계, shared/index_text.py)` | 2026-11-20 16:29:20 KST |
| **Git 미커밋 변경 파일** | `4개 파일` | 2026-11-20 16:29:20 KST |
| **Qdrant 컬렉션 (`v2`) 포인트** | `618` (승인: `593`, 검수대기: `8`, 반려: `17`) | 2026-11-20 16:29:20 KST |
| **Qdrant 색인 고유 문서** | `136개 문서` | 2026-11-20 16:29:20 KST |
| **원문 PDF 총계** | `141개 PDF` | 2026-11-20 16:29:20 KST |
| **미색인 원문 PDF 목록** | 5건: RPT_20261105_KB금융_미확인.pdf, RPT_20261105_우리금융지주_미확인.pdf, 논문_20260825_드론자력탐사오차보정_Geophysics.pdf, 보고서20261111휴머노이드로봇RD투자전략개방형_한국과학기술기획평가원.pdf, 보도자료_20260702_OECD한국경제보고서_재정경제부.pdf | 2026-11-20 16:29:20 KST |
| **동일 종목 비교 그룹** | `10개 그룹` (`compare_pairs.json`) | 2026-11-20 16:29:20 KST |
| **도표 비교 매칭 성공** | 총 69건 (TARGET_PRICE: 15건, ANNUAL_ESTIMATE: 28건, QUARTERLY_RESULT: 26건) | 2026-11-20 16:29:20 KST |
| **도표 비교 미매칭 원인** | 총 21건 (ABSENT: 8건, KEYWORD_MISS: 13건) | 2026-11-20 16:29:20 KST |
| **상태 검사기 (`check_state`)** | `PASS=6  WARN=1  CHANGED=0  FAIL=1  SKIP=0` | 2026-11-20 16:29:20 KST |
| └ **검사 경고(WARN) 항목** | A6. 모델 중복 정의 | 2026-11-20 16:29:20 KST |
| └ **검사 생략(SKIP) 항목** | 없음 | 2026-11-20 16:29:20 KST |
| └ **검사 실패(FAIL) 항목** | A3. 직접 쓴 상태 문자열 | 2026-11-20 16:29:20 KST |
<!-- AUTO:END -->

수동 기록 (2026-11-20 18:00)
- v2 618건: 승인 593, 검수대기 8, 반려 17. **표 500개는 A안 벡터**(색인 글자 = 기존 글자 + 표 열·행 이름 최대 40개), 나머지 118개는 그대로. 되돌리기 기준 백업은 팀장 PC `qdrant_backup_before_A`(저장소 밖)
- 데이터 zip: `figindex_data_20261120.zip` (약 1.03GB, 드라이브 FigIndex_data). A안 벡터 포함
- 검색 정식 측정 (11-20 17:37~17:47, 팀원2, 새 zip, cold 기준, 켬/끔 각 3회 재현)

| 지표 | main | B만 | A만 | A+B (지금 main + 이 데이터) |
| --- | --- | --- | --- | --- |
| `precision_at_5` (20개) | 0.900 | 0.945 | 0.932 | **0.945** |
| 1~3번 뺀 17개 | 0.971 | 0.971 | 0.971 | 0.971 |
| 1·2·3번 | 0.6·0.5·0.4 | 1.0·1.0·0.4 | 0.8·0.75·0.6 | 0.8·1.0·0.6 |
| 튜닝용 10개 (상위 5개 맞은 수) | 29/50 | 32/50 | 30/50 | 30/50 |
| `search_latency_sec` | 0.271 | 0.232 | 0.229 | 0.270 |

- 엔티티 사전 `figindex/data/entity_dictionary.csv`: 65개 (종목 50, 기관 9, 제품 6)
- 오분류 점검 88건 완료: 맞음 56, 틀림 32 (요소 아님 17, 잘림 13, 캡션 3, 노이즈 1, 유형 0)
- 표 평가 (11-19 12:00, `eval_tables.py`): `table_valid_rate` 0.998 (488/489), `cell_accuracy` 0.592 (468/790), `gt_table_coverage` 0.467 (14/30), `cell_accuracy_extracted` 1.000 (468/468)
- 수치 정답셋: `figindex/data/gt/table/cells.csv` 표 30개, 숫자 셀 790개. 연결 `links.csv` 30/30 (같은 표 14, 요소 없음 16)
- 테스트 (11-20, 팀장 PC Docker): pipeline 231건 통과(`test_index_text.py` 5건 포함), `scripts/test_reembed_table_vectors.py` 4건, `backend/app/test_search_rerank.py` 7건

---

## 2. 최근 작업 로그 (Recent Logs - 최근 5건)

| 시각 | 작업 요청 | 바꾼 파일 | 실행 명령 | 결과 숫자 | 판정 |
| :---: | :--- | :--- | :--- | :--- | :---: |
| **11-20 17:45** | A안 데이터에서 재정렬 켬/끔 측정 (팀원2) | — (측정만, 끔은 로컬에서 잠시 바꾸고 되돌림) | `eval_search.py` cold 각 1회 + 재현 2회 | A+B 0.945, A만 0.932, 17개 0.971 동일, 켬/끔 응답 차이 0.01초 안팎 | **PASS** |
| **11-20 17:38** | PR #43 병합 (팀원1 업로드 화면: 완료 문서 도표 수, 실패 문서 [다시 시도]) | `frontend/app/components/UploadPanel.tsx` | 작성자 실동작 확인(재시도 성공, 409 메시지, DB 복원) | main `9d9fd30` | **PASS** |
| **11-20 17:00** | A안 2단계: v2 표 500개 벡터 다시 계산 | `scripts/reembed_table_vectors.py`, `scripts/test_reembed_table_vectors.py` | `reembed_table_vectors.py --collection figindex_elements_v2 --apply --confirm-v2` (사전 `data/qdrant` 폴더 백업) | 500/500 교체, 포인트 618 유지, payload 해시 일치, P@5 0.900 → 0.932 | **PASS** |
| **11-20 17:18** | PR #42 병합 (팀원2 검색 재정렬 B) | `backend/app/search_rerank.py`, `backend/app/test_search_rerank.py`, `backend/app/main.py`, `docs/migration/api_changes.md` | 팀장 리뷰, 테스트 7건 | main `31370b9`, P@5 0.900 → 0.945 (A 전) | **PASS** |
| **11-20 16:00** | A안 1단계: 색인 글자에 표 열·행 이름 (`build_index_text`) | `shared/index_text.py`, `pipeline/orchestrator.py`, `scripts/rebuild_sparse_vectors.py`, `pipeline/test_index_text.py` | `docker compose -f figindex/docker-compose.yml run --rm pipeline pytest -q` | 231건 통과, 표 없는 요소는 예전 글자와 완전히 같음 | **PASS** |

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
21. **검색 재정렬 B (11-20, 팀원2, #42)**: `backend/app/search_rerank.py`. 검색어에 기업(COMPANY)이 잡히면 후보 50개 안에서 표 행·열 이름에 검색어의 지표(`shared.normalize` 사전)·연간 열(검색어에 "분기"면 분기 열)이 있는 표를 조건당 `RERANK_SHIFT = 5`칸 당김. 응답 키는 그대로, 순서만 바뀜(`api_changes.md` 9절).
22. **업로드 화면 마무리 (11-20, 팀원1, #43)**: 완료 문서에 "도표 N개"/"도표 없음"(`extra_metadata.element_count`가 있을 때만), 실패 문서에 [다시 시도]와 실패 사유·409 사유 표시.
23. **A안: 색인 글자에 표 이름 (11-20, 팀장)**: `shared/index_text.py`의 `build_index_text(payload)`를 `orchestrator.index_element_to_qdrant`와 `scripts/rebuild_sparse_vectors.py`가 함께 씀(식이 한 곳). 표가 없거나 빈 표면 예전 글자와 완전히 같음.
24. **기존 표 벡터 다시 계산 (11-20, 팀장)**: `scripts/reembed_table_vectors.py`. 기본 dry-run, v2는 `--apply --confirm-v2`. 임베딩 실패 시 가짜 벡터 없이 멈춤(멱등, 다시 돌리면 됨). 실행 전 스냅샷을 만들지만 컨테이너 안에만 저장되므로 되돌리기 기준은 `data/qdrant` 폴더 복사.

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
12. **저장소 정리 (11-18, 11-20 변경)**: 데이터 zip에 entity_dictionary.csv를 넣지 않음(git 관리). 병합된 PR 브랜치 자동 삭제는 **11-20에 끔**(팀원 브랜치가 지워져 결정 23과 어긋났음). 팀장 브랜치는 병합 후 직접 지운다.
13. **'요소 아님' 17건 반려 (11-18, v2 쓰기)**: 목차·장 제목·초록으로 판정된 요소. 확신도 신호가 목차를 거르지 못함.
14. **현황서 갱신 규칙 (11-18)**: AGENTS.md 8절.
15. **업로드 파일 이름 규칙을 강제하지 않음 (11-18)**: 표지에서 메타데이터를 찾고, 못 찾으면 비워 둔다.
16. **예전 표 297개 저장 형태 정리 (11-19, v2 쓰기)**: 숫자 문자열 15,123칸을 숫자로. pipeline_version은 그대로.
17. **PIPELINE_VERSION 0.1.1 → 0.1.2 (11-19)**: ① 표지 기반 메타데이터(#35) ② `.802` 소수 ③ 공백만 다른 행 키.
18. **수치 정답셋 측정 방식 (11-19)**: `cell_accuracy`는 용어집 정의대로, 보조 지표 `gt_table_coverage`·`cell_accuracy_extracted`를 함께 보고. 정답 표는 추출 결과에 맞춰 바꾸지 않는다.
19. **색인 한도 조정과 재색인은 다음 주 (11-19)**: 요소 없음 16개의 원인은 `run_index.py` 기본값(앞 12쪽, 도표 4개). 0.1.3 규칙으로 13개 문서 재색인.
20. **업로드 처리는 별도 작업자 (11-19)**: pipeline 이미지의 작업자가 처리. 한 번에 1건, 자동 재시도 없음, 도표 0개도 `COMPLETED`(`element_count` 0). 기본 저장 컬렉션 `figindex_test_upload`, 서비스 전환 때만 `WORKER_COLLECTION=figindex_elements_v2`. 서버·DB·파이프라인·작업자는 팀장, 팀원1은 업로드 화면만.
21. **PIPELINE_VERSION 0.1.3 (11-19)**: 목차 거르기, 업로드 문서 전체 쪽·도표 40개, doc_id 그대로 사용, 논문식 `Fig. N.` 캡션.
22. **재색인은 기존 요소를 유지하고 빠진 요소만 추가 (11-19)**: `element_id`는 색인할 때마다 무작위라, 통째로 다시 색인하면 수치 정답셋 연결 14개가 깨진다.
23. **브랜치 정리 원칙 (11-19)**: 병합 후 지우는 것은 팀장 브랜치뿐이고, 팀원 개인 브랜치는 남긴다. 단 `sun`과 `seung-test-collection-guard`는 병합하지 않는다.
24. **검수 단축키는 팀원1 버전 (11-19)**: #38을 병합.
25. **검색 정답 기준: 연간과 분기는 다른 지표 (11-20)**: IBK 분기별 표(`fig-441fb8fd772a`)는 "삼성전자 2025년 매출액 영업이익"의 정답이 아님. 정답셋은 검색 결과에 맞춰 고치지 않는다.
26. **검색 개선은 A+B 둘 다 유지 (11-20)**: B(재정렬) 채택, A(표 이름 벡터) 유지. C(sparse 가중치 올리기)는 하지 않음(sparse 글자에도 표 내용이 없었음). 공정한 숫자(17개·튜닝용)로는 A의 효과를 가르지 못해(17개 동일, 튜닝 B만 32 → A+B 30) 튜닝용 검색어를 늘려 다시 본다.
27. **"실적"은 지표 사전에 넣지 않는다 (11-20)**: 사전에 넣으면 `실적(3Q26P)` 같은 열 이름을 비교 엔진이 매출액으로 읽을 위험. 검색 쪽 별도 목록도 만들지 않음(사전 하나 원칙). A만으로 3번 0.4 → 0.6.
28. **채점용 검색어에 맞춘 조정 금지 (11-20)**: A+B에서 1번이 1.0 → 0.8로 내려간 것은 검색 코드로 되돌리지 않는다. 조정은 튜닝용 검색어로만.
29. **튜닝용 검색어 판정은 두 명, 출처 가리고 (11-20)**: 원인 분석에 쓰지 않은 '기업+지표+연도' 검색어 10개 추가. 기준을 먼저 적고, A+B·B만 결과를 섞어 출처를 가린 채 팀원2·팀원3이 각자 판정, 판정이 갈린 건수도 보고.
30. **크롭 방식 결정 기준 (11-20)**: ① 10페이지 크롭 15초 이내 ② 잘림 13건 중 9건 이상 해결 ③ `crop_recall`이 지금 방식 이상, 셋 다 넘으면 YOLO 연결. 아니면 지금 방식 유지 + 규칙 2개 수정(제목 박스를 제목 줄 실제 좌표로, 주석 접두어에 "Note"·"주."·"출처"·"*" 추가). `crop_recall`은 용어집 정의(IoU 0.5) 그대로, 잘림 해결 수는 보고서에만.
31. **기존 벡터 갱신은 재색인이 아니라 벡터만 교체 (11-20)**: `element_id`·payload를 지키기 위해 `update_vectors`만 쓴다. 되돌리기 기준은 `data/qdrant` 폴더 복사(Qdrant 스냅샷은 컨테이너 안에만 남음).

---

## 5. 열린 문제·넘길 일 (Open Issues)

| 문제 / 이슈 | 담당 | 상태 | 상세 내용 |
| :--- | :---: | :---: | :--- |
| **A+B 대 B만, `RERANK_SHIFT` 재평가** | 검색(팀원2) | 열림 | 튜닝용 검색어 10개 추가, 두 명 판정(결정 29). `RERANK_SHIFT = 5`는 A 전 데이터에서 고른 값 |
| **색인 한도로 뒤쪽 표 누락** | 파이프라인 | 진행 중 | 수치 정답셋 30개 중 16개 카드 없음. 0.1.3 규칙으로 재색인(결정 19·22). 드론 논문도 대상. **재색인은 A안 코드가 main에 들어간 뒤**(아니면 옛 방식 벡터가 섞임) |
| **재색인 뒤 데이터 zip 다시 배포** | 팀장 | 대기 | 11-20 zip은 A안까지만 반영 |
| **크롭 품질 (팀원4)** | 크롭(팀원4) | 열림 | 잘림 13건(표 제목 9, 하단 주석·출처 5, 단위 1, 차트·다이어그램 2), 상단 본문 노이즈 15건. 원인 추정: `cropper.py`의 제목 위 25pt 고정, 주석 접두어 4개뿐, 차트 높이 180pt 고정. 전달 자료·점검표 전달 완료 |
| **배포 후 확인 2건** | 팀장 | 결과 미기록 | 팀장 PC `register_existing_pdfs`(기대: 141개 확인, 신규 0), 검수 탭 A키 승인이 ReviewLog에 APPROVE로 남는지(시험 컬렉션 `figindex_test_review`로 확인, 시험 후 DB 복원) |
| **팀원 PC의 미색인 5건 '업로드됨'** | 참고 | 참고 | 작업자 처리 기록(`element_count`)이 팀장 PC에만 있어 팀원 PC에서는 UPLOADED. 팀원이 작업자를 켜면 시험 컬렉션에 처리됨 |
| **SK증권 카카오 요소 4개 entities에 카카오 없음** | 파이프라인 | 열림 | `fig-8038b3e077c6`·`fig-0c4438112aa8`·`fig-65dc461722d9`·`fig-902e8159e118`, entities가 `['주요주주','SK증권','외국인지분율','시가총액']`. `extra_metadata.target`으로만 필터 통과. 엔티티 정규화 때 함께 |
| **표 셀 값이 문자열로 남은 3개** | 파이프라인 | 열림 | fig-38347d0364c8(SK텔레콤 SK p.1), fig-ebfa3b5c97da(삼성전자 IBK p.4), fig-2223a70c7ef2(KIEP 표 1-1, `'3.41)'` 각주 표시라 원문이 맞을 수 있음) |
| **`rebuild_sparse_vectors.py`의 옛 스냅샷 재사용** | 인프라 | 열림 | 이름에 `2026-11-17-06-28-08`이 든 스냅샷이 있으면 새로 만들지 않고 재사용. 다시 쓰기 전에 지울 것 |
| **드론 논문 `Fig.` 크롭 영역 확인** | 파이프라인 | 열림 | 재색인 후 카드로 확인 |
| **HWP 변환 PDF의 이미지 조각** | 파이프라인 | 참고 | 캡션 규칙으로 못 잡음 → YOLO 검토 대상 |
| **빈 표 1건 (BERT p.8, fig-437d261937fb)** | 정답셋 | 열림 | 실제 표가 있으나 캡션 틀림, 표 데이터 없음. 검수대기 |
| **비교 응답 모델·MetricType의 schemas.py 이전** | 백엔드/스키마 | 결정 대기 | check_state A6 경고 원인 |
| **엔티티 정규화 (AGENTS.md 5절)** | 파이프라인 | 일부 완료 | 색인 시 entities 전체를 사전으로 바꾸는 처리는 아직 |
| **증권사 목록이 코드에 있음** | 파이프라인 | 열림 | `BROKER_ALIASES` → 사전으로 옮길지 검토 |
| **CAP_LIMIT 문서 재색인 실행** | 파이프라인 | 대기 | 승인된 23건. 결정 19 재색인과 합칠지 확인 |
| **잘못된 크롭 (KT&G 유안타 p.10)** | 크롭 | 열림 | 같은 캡션에 다른 크롭 박스 |
| **캡션 오배정 (HeritageJ p.2)** | 정답셋 | 열림 | 같은 캡션이 2개 요소에 |
| **섞인 단위 문자열 (`unit: '십억원, %'`)** | 파이프라인 | 열림 | `unit_for`가 % 아닌 행에 '십억원, %'를 돌려줌. 비교 엔진 단위 환산 영향 확인 필요 |
| **정답값 원문 대조** | 정답셋(팀원3) | 열림 | 원문 PDF로 표 2~3개 확인 |
| **check_state 테스트 2건 실패** | 인프라 | 열림 | `test_check_state_a2.py`의 legacy_allowed_files 2건 (Docker 밖 실행 시) |
| **doc_latency_sec 목표** | 파이프라인 | 열림 | ≤ 15초(10쪽)는 Gemini 분당 14회 한도로 도표 3개 넘으면 불가. 목표 재설정 필요 |

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
16. **`get_dense_embedding`은 실패하면 가짜 벡터를 넣는다**: `orchestrator.py`는 OpenAI 호출이 실패하면 경고만 찍고 결정론적 대체 벡터를 쓴다. 기존 데이터 갱신 스크립트에서는 이 함수를 쓰지 말고 직접 호출해 실패 시 멈춘다(`reembed_table_vectors.py` 방식).
17. **Qdrant 스냅샷은 컨테이너 안에만 남는다**: `/qdrant/snapshots`는 PC 폴더에 연결돼 있지 않아 `docker compose down`이면 사라진다. 되돌리기 기준은 `docker compose stop qdrant` 후 `data/qdrant` 폴더 복사.
18. **팀원 PC와 팀장 PC 검색 점수가 다를 수 있다**: v2 벡터를 바꾸면 데이터 zip을 다시 배포하기 전까지 팀원 PC 점수가 다르게 나온다. 측정 기록에는 사용한 zip 이름을 적는다.

---

## 7. 기준 파일·실행 환경

### 5대 기준 파일 (Single Source of Truth)
1. **`figindex/shared/schemas.py`**: 유일한 표준 스키마.
2. **`figindex/shared/coords.py`**: bbox `[x0, y0, x1, y1]`(좌상단 원점, 0~1)와 좌표 변환.
3. **`docs/glossary.md`**: 확신도 신호(6절), 메타데이터(7절), 좌표(8절), 표 수치 저장 규칙(9절), 엔티티 사전(10절), 평가 지표(12절), 문서 간 비교(14절).
4. **`AGENTS.md`**: 쓰지 않는 이름(2절), 수정 금지 파일(7절) 등. 파이프라인은 `figindex/pipeline/AGENTS.md`, 백엔드는 `figindex/backend/AGENTS.md`도 따른다.
5. **`figindex/pipeline/pdf_text.py`**: PDF 글자 읽기와 목차 판단(`is_toc_page`).

검색 색인 글자는 `figindex/shared/index_text.py`(`build_index_text`) 한 곳에서만 만든다.

### 실행 환경 (`figindex/docker-compose.yml`)
- `figindex-qdrant`, `figindex-backend`, `figindex-frontend` (`QDRANT_COLLECTION=figindex_elements_v2`).
- `pipeline` 서비스는 `profiles: ["index"]`, `worker` 서비스는 `profiles: ["worker"]`.
- Qdrant: 서비스 `figindex_elements_v2`(618, 표 500개 A안 벡터), 구버전 `figindex_elements`(525), 시험 `figindex_test_upload`(작업자 결과), `figindex_test_coerce`, `figindex_test_review`. v2·v1 쓰기는 팀장 승인 필요. 데이터 zip은 `figindex_test_*`를 넣지 않는다.
- 데이터 zip: 최신 `figindex_data_20261120.zip`.
- 브랜치: `main`(배포), `ryu`(팀장 작업). 팀원 브랜치 `young-search-rerank`(팀원2), `seung-upload-retry`·`seung-test-collection-guard`(팀원1), `sun`(팀원3)은 남긴다(결정 23). GitHub 병합 후 자동 삭제는 꺼져 있다.
- 팀 구성: 팀장(비교 엔진·통합·파이프라인), 팀원1 업로드 화면, 팀원2 검색, 팀원3 오분류·정답셋(주 3일), 팀원4 크롭(11/23 합류).
- 관리자 검수 API: `POST /api/review/{element_id}` (헤더 `X-Admin-Password`). 처리할 때마다 ReviewLog 1줄 추가. 다시 시도 API: `POST /api/documents/{doc_id}/retry` (`docs/migration/api_changes.md` 8절). 검색 결과 순서: `api_changes.md` 9절.

---

## 8. 로드맵 (Roadmap)

- **11/20(금)**: 완료 — PR #42·#43 병합, A안 적용(v2 표 500개), 새 데이터 zip, `ryu` → main.
- **11/23~24**: 팀원4 합류(PC 세팅, 잘림 사례 확인, YOLO 비교 시작). 팀원2·팀원3 튜닝용 검색어 10개와 두 명 판정.
- **11/25~26**: 0.1.3 규칙으로 13개 문서 + 드론 논문 재색인(기존 요소 유지, 결정 22, A안 색인 글자 적용), 데이터 zip 다시 배포, 수치 정답셋 다시 측정(`gt_table_coverage`), 팀원3 '요소 없음' 16행 재연결, 정답값 원문 대조.
- **11/27**: 기능 개발 마감, 크롭 방식 결정(결정 30), 업로드 작업자 서비스 v2로 전환.
- **11/30~12/2**: 지표 측정·버그 수정, (YOLO로 결정되면) 크롭 연결.
- **12/3**: 시연 리허설.
