# 스키마 통합 사전 조사 보고서 (프롬프트 1)

> 작성일: 2026-11-12  
> 작업 브랜치: `refactor/schema-unify`  
> 목적: `figindex/` 실행 앱을 `app/schemas.py` 기준으로 통합하기 전 현재 코드·데이터·Qdrant 상태 조사 (코드 수정 없음)

---

## 1. Git 브랜치 상태
- 새 브랜치 `refactor/schema-unify` 생성 및 체크아웃 완료 (`HEAD` 기준 커밋 `2864055`)

---

## 2. Qdrant 컬렉션 백업 스냅샷
- 대상: `http://qdrant:6333` (`figindex_elements`, 525 points)
- 저장 경로: `figindex/data/backup/figindex_elements-1851693946944154-2026-11-12-08-04-40-1.snapshot`
- 파일 크기: `1,319,749,632 bytes` (약 `1.23 GiB`)

---

## 3. `bbox` 실제 값 확인 및 판정

### 3.1 무작위 표본 10건 (`TABLE` 4건, `CHART` 3건, `DIAGRAM` 3건, `seed=42`)

| # | `element_type` | `element_id` | `doc_name` | `page_number` | `bbox` 원본 값 | PDF 페이지 크기 (`pt`) | 렌더 페이지 크기 (`px`, 200 DPI) | 크롭 이미지 크기 (`px`) | `[ymin, xmin, ymax, xmax]` 예상 크기 (`px`) | 시각화 파일 (`figindex/data/backup/bbox_check/`) |
| --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- |
| 1 | `TABLE` | `fig-b5f2a281f03a` | `보고서20251231해상풍력보급확대를위한지자체역할_에너지경제연구원.pdf` | 6 | `[0.1551, 0.1408, 0.9141, 0.8577]` | `468.0 × 666.0` | `1300 × 1850` | `932 × 1404` | `932 × 1404` | `01_TABLE_fig-b5f2_p6.png` |
| 2 | `TABLE` | `fig-c85253bda89a` | `보고서202607302024년도세계RD투자상위기업_한국과학기술기획평가원.pdf` | 8 | `[0.0449, 0.2116, 0.2304, 0.8053]` | `595.32 × 841.92` | `1654 × 2339` | `982 × 434` | `982 × 434` | `02_TABLE_fig-c852_p8.png` |
| 3 | `TABLE` | `fig-f6a9c3714ff3` | `논문_2026_패션크라우드펀딩스토리텔링_FashionBusiness.pdf` | 4 | `[0.4758, 0.1422, 0.8639, 0.8742]` | `595.0 × 841.0` | `1653 × 2337` | `1210 × 907` | `1210 × 907` | `03_TABLE_fig-f6a9_p4.png` |
| 4 | `TABLE` | `fig-4244a837f874` | `RPT_20261109_파마리서치_IBK투자증권.pdf` | 2 | `[0.5626, 0.0937, 0.7401, 0.9111]` | `595.32 × 841.92` | `1654 × 2339` | `1352 × 415` | `1352 × 415` | `04_TABLE_fig-4244_p2.png` |
| 5 | `CHART` | `fig-e24f14c09106` | `논문_20260810_생성형AI문화유산감정_HeritageJ.pdf` | 2 | `[0.3335, 0.4952, 0.5896, 0.9401]` | `595.28 × 841.89` | `1654 × 2339` | `736 × 599` | `736 × 599` | `05_CHART_fig-e24f_p2.png` |
| 6 | `CHART` | `fig-e5ca7d30704c` | `논문_20260925_청소년도박연구계량서지분석_KPAGeneral.pdf` | 6 | `[0.4382, 0.3942, 0.6943, 0.8386]` | `595.22 × 842.0` | `1654 × 2339` | `735 × 599` | `735 × 599` | `06_CHART_fig-e5ca_p6.png` |
| 7 | `CHART` | `fig-44600a79ee70` | `RPT_20261109_삼양식품_LS증권.pdf` | 3 | `[0.0881, 0.0641, 0.3442, 0.9401]` | `595.32 × 841.92` | `1654 × 2339` | `1449 × 599` | `1449 × 599` | `07_CHART_fig-4460_p3.png` |
| 8 | `DIAGRAM` | `fig-ab6512140c66` | `논문_202610_음성민감정보탐지마스킹_IEMEK.pdf` | 3 | `[0.8477, 0.101, 0.9671, 0.7011]` | `595.0 × 841.0` | `1653 × 2337` | `992 × 279` | `992 × 279` | `08_DIAGRAM_fig-ab65_p3.png` |
| 9 | `DIAGRAM` | `fig-3673b4dba211` | `RPT_20261106_삼진식품_한국IR협의회.pdf` | 3 | `[0.5994, 0.3017, 0.8162, 0.9057]` | `595.32 × 841.92` | `1654 × 2339` | `999 × 507` | `999 × 507` | `09_DIAGRAM_fig-3673_p3.png` |
| 10 | `DIAGRAM` | `fig-ff95cbcfbe9c` | `RPT_20261109_PI첨단소재_iM증권.pdf` | 2 | `[0.6836, 0.3349, 0.9393, 0.8247]` | `595.32 × 841.92` | `1654 × 2339` | `810 × 598` | `810 × 598` | `10_DIAGRAM_fig-ff95_p2.png` |

### 3.2 `bbox` 4가지 판정 결과
- **a) 값의 순서**: **`[ymin, xmin, ymax, xmax]`** (`[x0, y0, x1, y1]`이 아님). 10건 모두 크롭 이미지 픽셀 크기와 `[ymin, xmin, ymax, xmax]` 계산값이 1px 오차도 없이 정확히 일치했고, 시각화 이미지(`01_TABLE_fig-b5f2_p6.png`, `05_CHART_fig-e24f_p2.png` 등)에서도 빨간색(`[ymin, xmin, ymax, xmax]`) 박스가 실제 요소 위치와 일치함.
- **b) 단위**: **`0~1` 정규화** (좌상단 원점, 소수점 4자리 반올림).
- **c) 패딩 포함 여부**: **포함**. `figindex/pipeline/cropper.py`의 `crop_and_save()`가 패딩을 적용한 픽셀 좌표(`x0_pad, y0_pad, x1_pad, y1_pad`)로 크롭한 뒤 그 패딩된 정규화 좌표를 `normalized_box`로 저장함.
- **d) 10건 모두 같은 규칙인지**: **10건 모두 동일 규칙**이며, Qdrant 525건 전체 전수 검사에서도 범위(`0.0 <= v <= 1.0`) 또는 순서(`ymin < ymax`, `xmin < xmax`) 위반 건이 `0건`임.

---

## 4. 옛 이름 사용처 목록 (`figindex/` 및 `scripts/` 총 28개 코드 파일 스캔)

### 4.1 핵심 스키마/좌표 이름
- **`VisualElementSchema`** (총 25줄, 4개 파일):
  - `figindex/backend/app/main.py`: 12줄 (24, 392, 411, 474, 490, 565, 575, 609, 615, 670, 673, 696)
  - `figindex/pipeline/extractor.py`: 6줄 (16, 23, 203, 205, 303, 338)
  - `figindex/pipeline/orchestrator.py`: 6줄 (22, 24, 531, 532, 559, 574)
  - `figindex/shared/schemas.py`: 1줄 (27)
- **`TableStructure`** (총 18줄, 8개 파일):
  - `figindex/backend/app/main.py`: 1줄 (27)
  - `figindex/frontend/app/components/ComparisonModal.tsx`: 2줄 (6, 22)
  - `figindex/frontend/app/components/ReviewTab.tsx`: 2줄 (6, 22)
  - `figindex/frontend/app/elements/[id]/page.tsx`: 2줄 (20, 36)
  - `figindex/frontend/app/page.tsx`: 2줄 (20, 36)
  - `figindex/pipeline/evaluator.py`: 4줄 (3, 5, 33, 104)
  - `figindex/pipeline/extractor.py`: 3줄 (17, 24, 279)
  - `figindex/shared/schemas.py`: 2줄 (19, 36)
- **`title_or_caption`** (총 35줄, 10개 파일):
  - `figindex/backend/app/main.py`: 3줄 (266, 652, 653)
  - `figindex/frontend/app/components/ComparisonModal.tsx`: 9줄 (20, 141, 152, 158, 171, 182, 188, 230, 237)
  - `figindex/frontend/app/components/ReviewTab.tsx`: 8줄 (20, 60, 145, 191, 351, 399, 437, 439)
  - `figindex/frontend/app/elements/[id]/page.tsx`: 3줄 (34, 199, 205)
  - `figindex/frontend/app/page.tsx`: 3줄 (34, 655, 707)
  - `figindex/pipeline/extractor.py`: 4줄 (171, 189, 263, 345)
  - `figindex/pipeline/orchestrator.py`: 2줄 (533, 612)
  - `figindex/pipeline/run_index.py`: 1줄 (48)
  - `figindex/pipeline/test_metadata_generalization.py`: 1줄 (340)
  - `figindex/shared/schemas.py`: 1줄 (34)
- **`structured_data`** (총 37줄, 10개 파일):
  - `figindex/backend/app/main.py`: 3줄 (268, 656, 657)
  - `figindex/frontend/app/components/ComparisonModal.tsx`: 3줄 (22, 65, 66)
  - `figindex/frontend/app/components/ReviewTab.tsx`: 5줄 (22, 147, 148, 193, 464)
  - `figindex/frontend/app/elements/[id]/page.tsx`: 7줄 (36, 225, 234, 236, 245, 253, 255)
  - `figindex/frontend/app/page.tsx`: 1줄 (36)
  - `figindex/pipeline/evaluator.py`: 7줄 (33, 57, 104, 106, 108, 113, 118)
  - `figindex/pipeline/extractor.py`: 7줄 (175, 192, 266, 277, 279, 288, 347)
  - `figindex/pipeline/run_index.py`: 1줄 (51)
  - `figindex/pipeline/test_metadata_generalization.py`: 1줄 (343)
  - `figindex/shared/schemas.py`: 2줄 (20, 36)
- **`bbox` 읽기/쓰기 코드** (총 20줄, 8개 파일):
  - `figindex/pipeline/cropper.py`: 13줄 (70, 89, 102, 113, 121, 149, 155, 165, 170, 211, 295, 296, 299)
  - `figindex/pipeline/extractor.py`: 1줄 (342)
  - `figindex/pipeline/yolo_trial.py`: 1줄 (31)
  - `figindex/shared/schemas.py`: 1줄 (31)
  - `figindex/frontend/app/page.tsx`: 1줄 (31)
  - `figindex/frontend/app/elements/[id]/page.tsx`: 1줄 (31)
  - `figindex/frontend/app/components/ComparisonModal.tsx`: 1줄 (17)
  - `figindex/frontend/app/components/ReviewTab.tsx`: 1줄 (17)

### 4.2 `AGENTS.md` "쓰지 않는 이름" 표 단어 출현 현황 (0건 제외)
*(단어 경계 기준 스캔 결과이며, React/Tailwind/HTTP 상태 등 일반 프레임워크 식별자 포함)*
- `figure`: 4줄 — `yolo_trial.py`(4)
- `visual`: 5줄 — `cropper.py`(2), `orchestrator.py`(2), `run_index.py`(1)
- `item`: 13줄 — `extractor.py`(3), `init_collection.py`(7), `scripts/migrate_source_target.py`(3)
- `filename`: 7줄 — `backend/app/main.py`(6), `yolo_trial.py`(1)
- `file_name`: 15줄 — `rename_reports.py`(12), `yolo_trial.py`(3)
- `page`: 30줄 — `cropper.py`(21), `orchestrator.py`(3), `rename_reports.py`(1), `yolo_trial.py`(5)
- `type`: 39줄 — `backend/app/main.py`(1), `ReviewTab.tsx`(10), `layout.tsx`(1), `page.tsx`(16), `tailwind.config.js`(1), `cropper.py`(1), `run_index.py`(4), `yolo_trial.py`(3), `scripts/concurrency_check.py`(1), `scripts/local_to_server.py`(1)
- `status`: 24줄 — `backend/app/main.py`(7), `ReviewTab.tsx`(2), `page.tsx`(5), `evaluator.py`(3), `scripts/concurrency_check.py`(7)
- `title`: 12줄 — `backend/app/main.py`(1), `ComparisonModal.tsx`(1), `PdfViewer.tsx`(2), `ReviewTab.tsx`(1), `elements/[id]/page.tsx`(1), `layout.tsx`(1), `page.tsx`(2), `test_parse_filename.py`(2), `yolo_trial.py`(1)
- `confidence`: 5줄 — `evaluator.py`(1), `extractor.py`(1), `yolo_trial.py`(3)
- `score`: 5줄 — `evaluator.py`(4), `extractor.py`(1)
- `done`: 3줄 — `select_pdfs.py`(3)
- `success`: 3줄 — `ReviewTab.tsx`(3)
- `md5`: 2줄 — `backend/app/main.py`(1), `orchestrator.py`(1)
- `box`: 1줄 — `cropper.py`(1)
- `label`: 28줄 — `ComparisonModal.tsx`(13), `ReviewTab.tsx`(8), `page.tsx`(4), `yolo_trial.py`(3)
- `cls`: 1줄 — `yolo_trial.py`(1)
- `conf`: 4줄 — `yolo_trial.py`(4)
- `feedback`: 1줄 — `ReviewTab.tsx`(1)
- `action`: 14줄 — `backend/app/main.py`(4), `ReviewTab.tsx`(4), `rename_reports.py`(1), `run_index.py`(2), `select_pdfs.py`(1), `scripts/local_to_server.py`(1), `scripts/migrate_source_target.py`(1)
- `version`: 4줄 — `backend/app/main.py`(3), `PdfViewer.tsx`(1)
- `model`: 13줄 — `backend/app/main.py`(1), `extractor.py`(6), `orchestrator.py`(2), `rename_reports.py`(1), `yolo_trial.py`(3)

---

## 5. Qdrant Payload 실제 필드 목록 (총 525건 전수 조사)

### 5.1 최상위 Payload 키별 등장 횟수
| 키 이름 | 등장 건수 (/525) | `ElementSearchPayload` 대응 여부 |
| --- | ---: | --- |
| `element_id` | 525 | 있음 (필수) |
| `doc_name` | 525 | 있음 (필수) |
| `page_number` | 525 | 있음 (필수) |
| `bbox` | 525 | 있음 (필수, 순서 변환 필요) |
| `element_type` | 525 | 있음 (필수) |
| `image_path` | 525 | 있음 (필수) |
| `confidence_score` | 525 | 있음 (필수) |
| `review_status` | 525 | 있음 |
| `summary` | 525 | 있음 |
| `hashtags` | 525 | 있음 (`#` 제거 확인 필요) |
| `entities` | 525 | 있음 |
| `extra_metadata` | 525 | 있음 |
| `doc_title` | 525 | 있음 |
| `doc_type` | 525 | 있음 |
| `domain` | 525 | 있음 |
| `source_org` | 525 | 있음 |
| `publish_date` | 525 | 있음 |
| `title_or_caption` | 525 | **없음** (`caption`으로 이관 필요) |
| `structured_data` | 524 | **없음** (`table_data`로 이관 필요) |
| `authors` | 525 | **없음** (`extra_metadata["legacy"]` 보관 필요) |

### 5.2 `extra_metadata` 하위 키별 등장 횟수
- `extra_metadata.analyst`: 525
- `extra_metadata.broker`: 525
- `extra_metadata.company`: 525
- `extra_metadata.ticker`: 525
- `extra_metadata.target`: 407
- `extra_metadata.industry`: 303
- `extra_metadata.source`: 222
- `extra_metadata.topic`: 222

### 5.3 `ElementSearchPayload`에는 있으나 현재 Payload에 없는 키 (8개)
- **필수 필드 중 누락 (2개)**: `doc_id`, `model_name`
- **기본값/선택 필드 중 누락 (6개)**: `caption`, `table_data`, `signals`, `pipeline_version`, `created_at`, `collection_id`

---

## 6. Qdrant 벡터 구성 (`figindex_elements`)
- **Points Count**: `525`
- **Named Dense Vector (`vectors`)**:
  - 이름: `"dense"`
  - `size`: `1536`
  - `distance`: `Cosine` (`Distance.COSINE`)
- **Named Sparse Vector (`sparse_vectors`)**:
  - 이름: `"sparse"`
  - `SparseVectorParams(index=SparseIndexParams(on_disk=False))`

---

## 7. 루트 `app/` 폴더 참조 여부 (`figindex/` 및 `scripts/`)
- `figindex/backend/`: 루트 `app/` 직접 참조 없음 (`from shared.schemas import ...` 사용; `uvicorn app.main:app`은 컨테이너 `/app/app` 기준)
- `figindex/pipeline/` (`except ImportError:` 폴백 블록 내 참조):
  - `figindex/pipeline/evaluator.py:5` (`from app.schemas import ReviewStatus, TableStructure, ElementType`)
  - `figindex/pipeline/extractor.py:21, 31` (`from app.schemas import ...`, `from app.pipeline.evaluator import ConfidenceEvaluator`)
  - `figindex/pipeline/orchestrator.py:24, 30, 31` (`from app.schemas import ...`, `from app.pipeline.cropper import PDFCropper`, `from app.pipeline.extractor import MultimodalExtractor`)
- `scripts/`:
  - `scripts/generate_sample_pdf.py:8` (`from app.core.config import settings`)

