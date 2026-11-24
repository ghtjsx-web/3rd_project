> 이 문서는 덧붙이지 말고 매번 전체를 다시 쓴다.

# FigIndex 프로젝트 종합 현황서 (AI 분석·인수인계용)

---

## 0. 지금 상황 (Current Status)

1. **현재 단계**: 11-24 마감. **팀장은 11-25(수)부터 부재**. `main`은 PR #54(`276a47a`, YOLO 크롭 연결 + 겹치는 박스 합치기)까지. `ryu`에 `PIPELINE_VERSION` 0.2.0 PR 대기. 팀원3 탐지 정답셋 PR #50은 `reviewed: false` 4쪽 수정 대기(팀원3 목요일 복귀)
2. **방금 한 일과 결과 (11-24)**: ① PR #49·#51·#52 병합 ② 표 재측정(팀장 PC): `cell_accuracy` **749/790 = 0.948**(목표 0.95, 남은 41칸은 대체 모델 이름 오독 T16·T18·T30), `gt_table_coverage` 30/30, `table_valid_rate` 0.992 ③ 탐지 정답셋 추가 기준 공지(요소 없는 쪽 `[]`, 패널 여러 개는 캡션 단위 1개, 사진 노이즈, 상자·화살표 개념도는 DIAGRAM, 본문·각주 줄 제외) ④ 팀원4 잘림 13건: YOLO 해결 12 + 부분 1. LG화학 상상인 p.2 행 이름 누락은 크롭에서 표 왼쪽이 잘린 것 ⑤ `eval_crops.py`(팀원4 PC, 26쪽·61요소, 준비 실행 후): 지금 방식 `crop_recall` **0.361** 10쪽 9.0초, YOLO **0.951** 10쪽 **14.7초** ⑥ **YOLO 연결**(PR #53): `cropper.detect_page_candidates()` + `CROP_METHOD`(기본 `yolo`, 실패 시 규칙 방식), `orchestrator`가 YOLO `detection_score`를 그대로 씀 ⑦ **팀장 PC 시험 업로드**(DB손해보험 리포트, `figindex_test_upload`): worker `크롭 yolo` 확인, 1쪽 표 5·차트 1 크롭, 확신도 69.0~99.5%로 퍼짐(예전 0.984·0.9733 몰림 해소), 낮은 3개 PENDING_REVIEW. **같은 표가 두 번 크롭됨** → `detection_gt.merge_duplicate_mains`(70% 이상 겹치면 하나로 합침) 추가, 테스트 1건(pipeline 253 통과)
3. **크롭 방식 결정 (팀장, 11-24)**: **YOLO 확정**(결정 30 세 기준 모두 통과). 기존 925개는 재색인 안 함(새 업로드부터 YOLO). 알려진 약점: YOLO가 사진(저자 사진·시편 사진)을 figure로 잡아 CHART 후보로 넘김, 모식도 유형은 Vision LLM이 정함 — `crop_recall`은 쓸데없는 박스를 세지 않아 점수에 안 나타남
4. **다음 할 일 (팀원)**: ① 팀원4: 시험 컬렉션(worker 기본 `figindex_test_upload`)에 PDF 1건 올려 크롭 그림 확인, 사진 카드·유형 보고 ② 팀원3(목요일): PR #50 4쪽 수정 → 병합 → 50쪽으로 `eval_crops.py` 최종 숫자 ③ 발표 자료: PPT 숫자(`cell_accuracy` 0.948, `crop_recall` 0.36 → 0.95, 목표주가 매칭 15 → 11), 시연 영상, 느낀 점 ④ (선택) 팀원2·3 검색어 판정
5. **막힌 것**: 팀장 부재 중 PR 병합 권한·대리 미정. `PIPELINE_VERSION`은 팀장 요청으로 0.2.0(결정 32). `scripts/add_missing_elements.py`처럼 기존 박스와 겹침으로 '빠진 요소'를 찾는 도구는 규칙 방식 박스 기준이라, YOLO로 돌리면 같은 요소를 새것으로 볼 수 있음 → 기존 데이터에 쓸 때는 `CROP_METHOD=rule`
6. **팀장 결정 대기**: ① `main.py`의 비교 응답 모델 3개와 `MetricType`을 `schemas.py`로 옮길지 ② 대체 모델 47개 재추출 여부(Claude 권장: 안 함, 발표에서 설명) ③ `evaluator.py`의 `self_consistency` 미실행 시 1.0 처리(AGENTS 5절 '적용 안 한 신호는 None'과 다름, 고치면 `PIPELINE_VERSION` 올림 대상, 발표 후 권장)

---

## 1. 핵심 숫자 (Key Metrics)

> 아래 표는 `python scripts/update_status.py`가 자동으로 다시 쓴다. 측정 시각이 11-20 16:29이면 아직 갱신 전이다(이 문서는 팀장 PC 밖에서 다시 썼다).

<!-- AUTO:START -->
| 항목 | 측정값 | 측정 시각 |
| :--- | :--- | :--- |
| **Git 브랜치** | `ryu` | 2026-11-23 10:22:34 KST |
| **Git 최신 커밋** | `169b518 - feat: yolo_trial 페이지 지정(잘림 13건 확인) + 정답셋 분담 문서화 + 현황서 11-22 결과 반영` | 2026-11-23 10:22:34 KST |
| **Git 미커밋 변경 파일** | `0개 파일` | 2026-11-23 10:22:34 KST |
| **Qdrant 컬렉션 (`v2`) 포인트** | `925` (승인: `895`, 검수대기: `13`, 반려: `17`) | 2026-11-23 10:22:34 KST |
| **Qdrant 색인 고유 문서** | `136개 문서` | 2026-11-23 10:22:34 KST |
| **원문 PDF 총계** | `141개 PDF` | 2026-11-23 10:22:35 KST |
| **미색인 원문 PDF 목록** | 5건: RPT_20261105_KB금융_미확인.pdf, RPT_20261105_우리금융지주_미확인.pdf, 논문_20260825_드론자력탐사오차보정_Geophysics.pdf, 보고서20261111휴머노이드로봇RD투자전략개방형_한국과학기술기획평가원.pdf, 보도자료_20260702_OECD한국경제보고서_재정경제부.pdf | 2026-11-23 10:22:35 KST |
| **동일 종목 비교 그룹** | `10개 그룹` (`compare_pairs.json`) | 2026-11-23 10:22:35 KST |
| **도표 비교 매칭 성공** | 총 69건 (TARGET_PRICE: 15건, ANNUAL_ESTIMATE: 28건, QUARTERLY_RESULT: 26건) | 2026-11-23 10:22:35 KST |
| **도표 비교 미매칭 원인** | 총 21건 (ABSENT: 8건, KEYWORD_MISS: 13건) | 2026-11-23 10:22:35 KST |
| **상태 검사기 (`check_state`)** | `PASS=7  WARN=1  CHANGED=0  FAIL=0  SKIP=0` | 2026-11-23 10:22:35 KST |
| └ **검사 경고(WARN) 항목** | A6. 모델 중복 정의 | 2026-11-23 10:22:35 KST |
| └ **검사 생략(SKIP) 항목** | 없음 | 2026-11-23 10:22:35 KST |
| └ **검사 실패(FAIL) 항목** | 없음 | 2026-11-23 10:22:35 KST |
<!-- AUTO:END -->

수동 기록 (11-22~23, 위 자동 표는 11-23 10:22 팀장 PC 측정)
- v2 **925건**: 11-22에 빠진 요소 307개 추가(`add_missing_elements.py` 260 + 재자원화 p.106용 47, `promote --new-only`, 중복 의심 0). 승인 895, 검수대기 13, 반려 17. 백업: 팀장 PC `C:\workAi\figindex_work\qdrant_backup_20261122`
  - 47개는 Gemini 503으로 대체 모델 `gemini-3.5-flash-lite`가 분석. 재자원화 p.169~178 설문지 10개가 표로 승인됨, p.180 그림이 TABLE·DIAGRAM 두 번, p.181 그림이 TABLE
- 검색 (11-22, 925건, `eval_search.py`): `precision_at_5` **0.922**, `search_latency_sec` 0.285. 20번(KDI 실효지급준비율) 1/5·17번(한국은행 수출물가) 1/5는 새 카드가 정답 목록에 없어서일 수 있음 → 두 명 재판정
- 데이터 zip: **`figindex_data_20261122.zip`** (약 1.07GB, 925건). 초안 그림·`compare_pairs.json`은 없음(11-23 확인)
- 11-20 기록: 표 500개는 A안 벡터(색인 글자 = 기존 글자 + 표 열·행 이름 최대 40개). 11-22에 추가된 307개는 처음부터 A안 글자로 색인됨
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
- 테스트 (11-23, 팀장 PC Docker): pipeline 245건 통과, scripts `test_add_missing_elements.py`·`test_promote_test_to_service.py` 12건 중 11건(1건은 경로 문제, `056ed45`에서 수정). 이번 변경으로 `test_detection_gt.py` 3건 추가(Docker 밖 9/9 통과)

---

## 2. 최근 작업 로그 (Recent Logs - 최근 5건)

| 시각 | 작업 요청 | 바꾼 파일 | 실행 명령 | 결과 숫자 | 판정 |
| :---: | :--- | :--- | :--- | :--- | :---: |
| **11-23 17:50** | 표 숫자 재측정 + 빠진 칸 원인 확인, 채점 이름 맞추기에 가운뎃점 통일 (Claude, 팀장 승인) | `scripts/eval_tables.py`(`norm_label`: ⋅ ・ ∙ → ·), `scripts/test_eval_tables.py`(+1건) | 팀장 PC `eval_tables.py`, Docker 밖 pytest | `gt_table_coverage` 30/30 = 1.000, `cell_accuracy` 741/790 = 0.938(빠진 49칸 모두 '칸 없음', '값 다름' 0). 원인: T24 가운뎃점 문자 차이(8칸, 이번 수정으로 맞음 → 예상 0.948), T30 '지준율'→'기준율'·T18 '발전량'→'발전력'·'링쾨빙'→'링퀴빙'·T16 행 이름 단위 분리(41칸, 원문 확인 결과 정답셋 맞음, AI 오류). 문제 표 4개 모두 대체 모델 `gemini-3.5-flash-lite` 추출분. pytest 12/12 | **확인 필요** (팀장 PC 재측정) |
| **11-23 14:45** | T16 재연결 + T17 확인: 팀장이 상세 화면에서 `fig-6cdcce96e35f`(수소 p.33)가 정답 <표 3-1>과, `fig-aa836cb4581d`(고용동향 p.12)가 정답 표와 같은 표임을 확인 | `figindex/data/gt/table/links.csv`, 정답셋 작업 시트 '수치표_연결' 17행 | - | 같은 표 30/30. 행 이름 겹침 0.286은 표기 차이로 보임 → `eval_tables.py` 상세 CSV에서 T16 셀이 이름 불일치로 빠지는지 확인. | **확인 필요** (`eval_tables.py`) |
| **11-23 13:10** | 팀장 PC에서 `check_table_quality.py` 실행 → 수치 정답셋 '요소 없음' 15행 재연결 (Claude, 팀장 승인) | `figindex/data/gt/table/links.csv`, 정답셋 작업 시트 '수치표_연결' F·H·I·J열(G열 링크 수식 유지, 이전 메모는 [이전 메모]로 남김) | `check_table_quality.py` | 행 이름 누락 의심 18개(캡션상 대부분 순위·번호·척도처럼 첫 열이 원래 숫자인 표, 진짜 의심은 TLB IBK p.1·LG화학 상상인 p.2 정도). 재연결 후보 16개 중 12개 점수 1.0, T17 0.915·T18 0.9·T21 0.917 → 15행 '같은 표'로 반영(29/30), T16(행 이름 겹침 0.286)은 '요소 없음' 유지 | **확인 필요** (T16·T17 사람 확인, `eval_tables.py`) |
| **11-23 12:40** | 표 품질 점검 스크립트(읽기 전용): 행 이름 열 누락 의심 표 + 수치 정답셋 '요소 없음' 16행 재연결 후보 (Claude) | `scripts/check_table_quality.py`, `scripts/test_check_table_quality.py`(3건) | Docker 밖 pytest, 팀장 PC SK하이닉스 iM 응답(8개 표)으로 실행 | 3/3 통과, 수정 전 `fig-6086b1030698`을 누락 의심으로 잡음. 팀장 PC v2 전체 실행은 아직 | **확인 필요** |
| **11-23 11:00** | 목표주가 매칭 전후 비교 + 화면 값 읽기 보완 (팀장 실행, Claude 분석) | `frontend/app/compare/TargetPriceView.tsx`("이름: 값" 한 칸 읽기, 단위는 행 이름 괄호 단위 아니면 "원") | `run_compare_matrix.py` 전(`d550f0d` 이전)·후, 응답으로 `findTargetPrice` 실행 | TARGET_PRICE 매칭 15 → 11. 빠진 4건(KT&G·삼양식품·코스맥스 한화, SK하이닉스 iM)은 모두 목표주가 값이 없던 표, 삼성전자 iM은 'Valuation Table'로 바뀌어 369,407원(캡션 36.9만원과 일치). 연간 29·분기 27 변화 없음. 화면 목표주가 값 9/15 → **11/11** | **PASS** |
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
25. **빠진 요소만 추가 (11-22, 실행 완료: v2 618 → 925)**: `process_pdf(existing_bboxes=, doc_overrides=)` — 기존 요소와 IoU ≥ 0.5이거나 후보의 3/4 이상이 기존 박스 안이면 크롭·Gemini 없이 건너뜀(`pipeline/element_match.py`), 새 요소는 기존 doc_id와 문서 메타데이터를 물려받음. `scripts/add_missing_elements.py`는 기본 미리보기, `--apply`는 `figindex_test_*`에만 씀(v1·v2·`figindex_test_upload` 거부), 시험 컬렉션 요소도 기존으로 봐서 이어 돌리기 가능, 기존 요소 없는 문서는 건너뜀. `--from-gt`는 수치 정답셋 '요소 없음' 13개 문서. v2 반영은 `promote_test_to_service.py --new-only`(서비스에 없는 element_id만 추가, 같은 point id면 건너뜀, 백업에 추가 ID를 남기고 `--rollback`은 그 포인트를 지움). 11-22 추가: 같은 문서·페이지의 기존 요소(반려 포함)와 IoU ≥ 0.3이거나 한쪽 넓이 절반 이상 겹치면 "중복 의심"으로 건너뜀(`--include-overlaps`로 해제). 11-22 미리보기: 13개 문서 새 후보 260개(약 19분), 정답셋 16쪽 중 15쪽 도달, 재자원화 p.106만 상한(40) 밖.
26. **탐지 정답셋 초안·`crop_recall` (11-22, 초안 50쪽 생성·커밋, 검수 0, 분담 팀원4 26·팀원3 24)**: `pipeline/make_detection_drafts.py --pick 50`이 문서 종류를 돌아가며 PDF 15개·50페이지를 고르고, 지금 방식과 YOLO 박스를 합친 초안(같은 요소면 감싸는 박스, 출처 표시 없음, 위→아래 번호)을 `data/gt/detection/{doc_name}_p{n}.json`(`"reviewed": false`)과 `_images/`(0.1 눈금)에 만든다. 기존 JSON은 덮어쓰지 않음. `pipeline/eval_crops.py`는 `reviewed: true`만으로 두 방식의 `crop_recall`(두 방식 모두 crop_and_save와 같은 패딩)과 페이지당 탐지 시간을 낸다. 역할 문서 `docs/roles/4_크롭.md` 4·5단계 갱신.
27. **비교 화면 목표주가 (11-22, 11-23 수정: 매칭 11/11 값 표시)**: `/compare` 지표 칩 맨 앞 '목표주가 (표 단위)' → `/api/compare/company?metric=TARGET_PRICE`. 리포트별 목표주가(근거 표의 목표주가·적정주가 행 또는 열의 첫 숫자, 상승여력·괴리율 줄 제외)와 근거 표·페이지, 차이, [원본 표 나란히 보기], 원문 PDF 뷰어. `compare_pairs.json` 그룹에 없는 종목은 안내 문구. 11-23: 목표주가 이름에 `주당가치`(적정주당가치) 추가, 단위는 행·열 이름의 괄호 단위 → 행·열별 단위 → 표 단위(여러 개면 그중 "원") 순, 근거 표에 목표주가 줄이 없으면 "표에 목표주가 없음 · 원문 확인". 코스맥스 한화투자증권은 캡션에 "목표주가"가 있어 골라졌지만 표에는 재무 항목만 있음(목표주가는 표 밖) 11-23 백엔드: 매칭 엔진이 캡션만 보고 고르던 것을, 표의 행·열 이름에 {목표주가, 적정주가, 적정가치, 주당가치, 적용, Target} 중 하나가 있어야 고르도록 함. 이 검사 함수는 11-17에 만들어졌으나 호출되지 않고 있었음. 백엔드는 `--reload-dir`에 compare가 없어 `docker compose restart backend` 필요 화면은 한 칸에 "적정주가: 36,000"처럼 이름과 값이 붙은 경우도 읽고(카카오 메리츠), 단위는 행·열 이름의 괄호 단위가 없으면 "원"(롯데쇼핑 LS가 "억원"으로 보이던 문제).
28. **잘림 사례 페이지 비교 (11-23)**: `yolo_trial.py --pages-file /data/gt/crop_cut_cases.txt`(또는 `--page "파일명.pdf:쪽"`). 지정 페이지마다 `_old_crop.png`(지금 방식 후보)와 `_yolo_crop.png`(YOLO 표·그림 + 캡션·각주 병합)를 `padded_like_cropper`로 같은 여백을 붙여 그림 → 결정 30 ②(잘림 13건 중 9건 이상 해결)를 눈으로 판정. 잘림 13건은 정답셋에 넣지 않음(IoU 0.5 `crop_recall`로는 제목 한 줄 잘림이 안 잡힘).

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
32. **크롭 방식 YOLO 확정 + PIPELINE_VERSION 0.1.3 → 0.2.0 (11-24, 팀장)**: 결정 30 세 기준 통과(`crop_recall` 0.361 → 0.951, 10쪽 14.7초, 잘림 12+부분 1). 새 업로드부터 DocLayout-YOLO 크롭(`CROP_METHOD`, 실패 시 규칙 방식), YOLO `detection_score` 사용, 겹치는 본 박스 합치기. 기존 925개(0.1.3 이하)는 재색인하지 않음 → `pipeline_version`으로 구분. 기존 데이터에 '빠진 요소' 도구를 쓸 때는 `CROP_METHOD=rule`

---

## 5. 열린 문제·넘길 일 (Open Issues)

| 문제 / 이슈 | 담당 | 상태 | 상세 내용 |
| :--- | :---: | :---: | :--- |
| **A+B 대 B만, `RERANK_SHIFT` 재평가** | 검색(팀원2) | 열림 | 튜닝용 검색어 10개 추가, 두 명 판정(결정 29). `RERANK_SHIFT = 5`는 A 전 데이터에서 고른 값 |
| **색인 한도로 뒤쪽 표 누락** | 파이프라인 | 해결(11-22) | v2에 307개 추가, 정답셋 16쪽 모두 카드 생김. 남은 일: 팀원3이 '요소 없음' 16행에 새 element_id 연결 → `eval_tables.py`로 `gt_table_coverage` 다시 측정. 아래는 11-22 이전 기록: | 수치 정답셋 30개 중 16개 카드 없음(13개 문서). 도구 준비됨: `add_missing_elements.py --from-gt`(완료 이력 25). A안은 PR #44로 main 반영 완료. 미리보기에서 정답 페이지가 '새 후보 없음'이면 규칙이 못 찾는 표(선 없는 표 등) → 크롭 개선 대상. 드론 논문은 미색인 문서라 이 도구 대상 아님(업로드 작업자나 `ingest_missing.py`) |
| **재색인 뒤 데이터 zip 다시 배포** | 팀장 | 공지 대기 | `figindex_data_20261122.zip`(925건) 드라이브 업로드 완료, 팀 공지 아직 |
| **탐지 정답셋 그림 배포** | 팀장 | 진행 중 | 그림은 git 제외·데이터 zip에도 없음. 팀원 PC에서 `--pick 50`을 다시 돌리면 같은 페이지를 "이미 있음"으로 건너뛰어 그림이 안 생김 → 팀장 PC 그림 50장을 `detection_images.zip`으로 드라이브에 |
| **검색어 20·17번 정답 재판정** | 검색(팀원2)·정답셋(팀원3) | 열림 | 925건 뒤 1/5. 새 카드가 관련 있으면 정답 목록 추가(두 명 판정, 결정 29) |
| **새 요소 품질** | 파이프라인 | 참고 | 대체 모델로 분석된 47개, 재자원화 설문지 10개(APPROVED), p.180·181 그림 오분류. 확신도 값이 0.859·0.984·0.9733에 몰림(발표 질문 대비) |
| **탐지 정답셋 검수 0/50 (초안 50 완료)** | 크롭(팀원4)·정답셋(팀원3) | 열림 | 분담 팀원4 26쪽·팀원3 24쪽(`4_크롭.md` 4단계 표). 끝나면 `eval_crops.py` → 크롭 방식 결정 |
| **`compare_pairs.json`이 git·데이터 zip에 없음** | 팀장 | 결정 대기 | 11-22 zip에도 없음(11-23 확인). | `figindex/data/`라 git 제외. 팀원 PC에서 `/api/compare/company`(목표주가 칩)가 빈 결과일 수 있음. zip에 넣거나 `data/gt`처럼 git에 올릴지 결정 |
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
| **목표주가 매칭 수 변화 확인** | 팀장 | 해결(11-23) | 15 → 11, 빠진 4건은 목표주가 값 없는 표, 삼성전자 iM은 올바른 표로 바뀜. 매칭된 11건 모두 화면에 목표주가 값이 나옴 |
| **SK하이닉스 iM 'Valuation Table' 미매칭** | 팀장 | 원인 확인(11-23) | `fig-6086b1030698`의 table_data에 행 이름 열(BPS, Target PB, 적정주가, 목표주가, 현재주가, 상승여력)이 빠지고 숫자만 남음. 매칭 엔진 문제 아님. 검수 API(`POST /api/review/fig-6086b1030698`, EDIT)로 원문대로 고침 → ReviewLog에 남음. 검수 수정은 payload만 바꾸므로 이 요소의 검색 벡터는 예전 글자 기준 |
| **행 이름 열이 빠진 표가 더 있는지** | 팀장 | 도구 준비 | `python scripts/check_table_quality.py`(읽기 전용) → 첫 열 값의 75% 이상이 숫자인 표 목록 CSV. 같은 실행에서 수치 정답셋 '요소 없음' 16행의 재연결 후보(같은 문서·페이지 TABLE을 캡션 유사도·정답 행 이름 겹침으로 순위)도 CSV로 냄 → 사람이 확인 후 `links.csv` 반영 → `eval_tables.py` |
| **섞인 단위 문자열 (`unit: '십억원, %'`)** | 파이프라인 | 열림 | `unit_for`가 % 아닌 행에 '십억원, %'를 돌려줌. 비교 엔진 단위 환산 영향 확인 필요. 11-23: 목표주가 화면은 행 이름 괄호 단위로 우회, 비교 엔진 쪽은 그대로 |
| **정답값 원문 대조** | 정답셋(팀원3) | 열림 | 원문 PDF로 표 2~3개 확인 |
| **check_state 테스트 2건 실패** | 인프라 | 열림 | `test_check_state_a2.py`의 legacy_allowed_files 2건 (Docker 밖 실행 시) |
| **doc_latency_sec 목표** | 발표 | 정리됨 | ≤ 15초(10쪽)는 Gemini 무료 티어 분당 14회 한도로 불가. 발표에서는 모델(유료·다른 모델) 변경 시 해결되는 발전 방향으로 설명(11-22 팀장) |

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
- Qdrant: 서비스 `figindex_elements_v2`(925, 11-22 추가분 포함 모두 A안 색인 글자), 구버전 `figindex_elements`(525), 시험 `figindex_test_upload`(작업자 결과), `figindex_test_coerce`, `figindex_test_review`. v2·v1 쓰기는 팀장 승인 필요. 데이터 zip은 `figindex_test_*`를 넣지 않는다.
- 데이터 zip: 최신 `figindex_data_20261122.zip`(925건). 탐지 정답셋 그림은 별도 `detection_images.zip`.
- 브랜치: `main`(배포), `ryu`(팀장 작업). 팀원 브랜치 `young-search-rerank`(팀원2), `seung-upload-retry`·`seung-test-collection-guard`(팀원1), `sun`(팀원3)은 남긴다(결정 23). GitHub 병합 후 자동 삭제는 꺼져 있다.
- 팀 구성: 팀장(비교 엔진·통합·파이프라인), 팀원1 업로드 화면, 팀원2 검색, 팀원3 오분류·정답셋(주 3일), 팀원4 크롭(11/23 합류).
- 관리자 검수 API: `POST /api/review/{element_id}` (헤더 `X-Admin-Password`). 처리할 때마다 ReviewLog 1줄 추가. 다시 시도 API: `POST /api/documents/{doc_id}/retry` (`docs/migration/api_changes.md` 8절). 검색 결과 순서: `api_changes.md` 9절.

---

## 8. 로드맵 (Roadmap)

- **11/20(금)**: 완료 — PR #42·#43 병합, A안 적용(v2 표 500개), 새 데이터 zip, `ryu` → main.
- **11/22(일)**: 완료 — 빠진 요소 307개 v2 추가(925), 검색 0.922, 데이터 zip 1122, 탐지 정답셋 초안 50쪽.
- **11/23~24**: 팀원4 합류(PC 세팅, 잘림 13건 원인 분류, `yolo_trial.py` 비교 + `--pages-file`로 잘림 13건 확인). 정답셋 초안 검수 시작(팀원4 26·팀원3 24). 팀 공지(새 zip 교체). 팀원2·팀원3 검색어 판정(튜닝용 10개 + 20·17번 재판정). PR #45 병합 완료.
- **11/25~26**: 팀원3 '요소 없음' 16행 재연결 → `eval_tables.py`(`gt_table_coverage`), 드론 논문 색인(업로드 작업자), 정답값 원문 대조, 정답셋 검수 마감 → `eval_crops.py`.
- **11/27**: 기능 개발 마감, 크롭 방식 결정(결정 30), 업로드 작업자 서비스 v2로 전환.
- **11/30~12/2**: 지표 측정·버그 수정, (YOLO로 결정되면) 크롭 연결.
- **12/3**: 시연 리허설.
