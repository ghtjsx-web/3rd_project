# FigIndex 용어집

> 이름의 원본은 `figindex/shared/schemas.py`입니다. 이 문서와 schemas.py가 다르면 schemas.py가 맞고, 이 문서를 고칩니다.
> 새 용어·필드가 필요하면 두 파일을 함께 고치는 PR을 올리고 팀장 승인을 받습니다.

## 1. 데이터 단위

| 한글 용어 | 코드명 | 정의 |
| --- | --- | --- |
| 등록 작업 | `Batch`, `batch_id` | 한 번에 올린 PDF 묶음. 진행률·재시도의 기준 단위 |
| 컬렉션 | `Collection`, `collection_id` | 문서 묶음(폴더). 문서는 0~1개 컬렉션에 속함 |
| 문서 | `Document`, `doc_id` | 등록된 PDF 1건 |
| 문서 해시 | `doc_hash` | 파일 내용의 SHA-256(16진수 소문자). 같은 해시면 중복 |
| 페이지 | `Page`, `page_number` | PDF 파일상 순서, 1부터. 문서에 인쇄된 쪽번호가 아님 |
| 탐지 결과 | `Detection`, `detection_id` | YOLO가 낸 원시 박스 1개. 크롭 전 단계, 요소가 아님 |
| 요소 | `Element`, `element_id` | 문서에서 추출한 표·차트·다이어그램 1개. 시스템의 기본 단위 |
| 셀 | `TableData.rows`의 값 | 표 안의 값 1칸 |
| 검수 이력 | `ReviewLog`, `review_id` | 검수 1회의 기록. 지우지 않고 쌓기만 함 |

- **"도표"라는 말은 코드·문서에서 쓰지 않습니다.** 표·차트·다이어그램을 통틀어 부를 때는 **요소**라고 합니다.
- 흐름: 등록 작업 → 문서 → 페이지 → 탐지 결과 → (병합·크롭) → 요소 → 검수 이력

## 2. 요소 유형 (`ElementType`)

| 코드값 | 한글 | 정의 | 애매한 경우 |
| --- | --- | --- | --- |
| `TABLE` | 표 | 행·열 격자로 된 수치/텍스트 | 표 안에 작은 막대가 있어도 격자가 주인이면 TABLE |
| `CHART` | 차트 | 수치를 그림으로 그린 것(막대·선·원·분산 등) | 차트 아래 데이터 표가 붙어 있으면 CHART 1개 |
| `DIAGRAM` | 다이어그램 | 구조·흐름·관계도, 수치 없음 | 지도·조직도는 DIAGRAM |

**요소로 저장하지 않는 것(노이즈)**: 사진, 로고, 표지 장식, 머리말·꼬리말, 아이콘.

**몇 개로 셀지**
- 캡션 하나에 묶인 그림 안의 여러 차트(a, b, c…) → **요소 1개**
- 여러 페이지에 걸친 표 → **페이지마다 요소 1개씩** (MVP 기준)

## 3. 탐지 클래스 (`LayoutClass`)와 요소 대응

DocLayout-YOLO의 클래스 이름은 모델 출력 그대로 씁니다. 1단계에서 사용하는 체크포인트의 `model.names`와 일치하는지 확인합니다.

| 탐지 클래스 | 처리 |
| --- | --- |
| `table` | 요소 → `TABLE` |
| `figure` | 요소 → `CHART` 또는 `DIAGRAM` (Vision LLM이 결정) |
| `table_caption`, `table_footnote`, `figure_caption` | 인접한 본 박스에 병합(Union BBox) |
| `title`, `plain text`, `abandon`, `isolate_formula`, `formula_caption` | 버림 (요소가 되지 않음) |

대응표 코드: `LAYOUT_TO_ELEMENT`, `MERGE_CLASSES`.

## 4. "추출"의 범위

| 항목 | 코드명 | 대상 |
| --- | --- | --- |
| 크롭 이미지 | `image_path` | 모든 요소 |
| 캡션 | `caption` | 모든 요소 (원문 그대로) |
| 요약 | `summary` | 모든 요소 (AI 생성 2~3줄) |
| 검색 태그 | `hashtags` | 모든 요소 (`#` 없이 저장) |
| 고유명사 | `entities` | 모든 요소 (사전에 있으면 대표 이름으로) |
| 수치 데이터 | `table_data` | **TABLE만**. 차트의 수치 읽기는 MVP 범위 밖 |

## 5. 상태값 (두 종류, 섞지 않음)

**문서 처리 상태** `DocStatus` → 필드 `doc_status`

| 코드값 | 화면 표기 | 의미 |
| --- | --- | --- |
| `UPLOADED` | 업로드됨 | 파일 저장 완료, 처리 대기 |
| `PROCESSING` | 처리 중 | 추출 진행 중 |
| `COMPLETED` | 완료 | 모든 요소 추출 끝 |
| `FAILED` | 실패 | `doc_error`에 사유 |
| `DUPLICATE` | 중복 | 같은 `doc_hash`가 이미 있음. `doc_error`에 기존 `doc_id` |

등록 작업의 진행률은 따로 저장하지 않고, 소속 문서의 `doc_status`를 세어 계산합니다.

**요소 검수 상태** `ReviewStatus` → 필드 `review_status`

| 코드값 | 화면 표기 | 의미 |
| --- | --- | --- |
| `APPROVED` | 승인 | 검색에 노출 |
| `PENDING_REVIEW` | 검수 대기 | `confidence_score` < 0.80 |
| `REJECTED` | 반려 | 검색 제외 |

**검수 행동** `ReviewAction` → 필드 `review_action`

| 코드값 | 화면 표기 | 결과 상태 |
| --- | --- | --- |
| `APPROVE` | 승인 | `APPROVED` |
| `EDIT` | 수정 후 승인 | `APPROVED` |
| `REJECT` | 반려 | `REJECTED` |

임계값은 상수 `CONFIDENCE_THRESHOLD = 0.80` 하나만 씁니다.

## 6. 확신도 신호 (`ConfidenceSignals`)

| 신호 | 코드명 | 값 | 적용 조건 | 기본 가중치 |
| --- | --- | --- | --- | --- |
| 1 | `detection_score` | 0~1 | 모든 요소 | 0.20 |
| 2 | `schema_valid` | 0 또는 1 | 모든 요소 | 0.25 |
| 3 | `numeric_consistency` | 0~1 | TABLE | 0.25 |
| 4 | `self_consistency` | 0~1 | TABLE, 또는 1차 확신도 0.70~0.85 | 0.15 |
| 5 | `text_match` | 0~1 | TABLE이면서 `has_text_layer` = true | 0.15 |

적용하지 않은 신호는 `None`으로 두고, 적용한 신호의 가중치 합이 1이 되도록 재정규화합니다. 가중치 코드: `SIGNAL_WEIGHTS`.

## 7. 메타데이터

| 구분 | 위치 | 필드 |
| --- | --- | --- |
| 문서 메타데이터 | `Document` | `doc_name`, `doc_title`, `doc_type`, `domain`, `source_org`, `authors`, `publish_date`, `page_count` |
| 페이지 정보 | `Page` | `width_pt`, `height_pt`, `has_text_layer` |
| 요소 메타데이터 | `Element` | `caption`, `summary`, `hashtags`, `entities` |
| 처리 버전 | `Element` | `pipeline_version`, `model_name` |
| 확장 메타데이터 | `Document`, `Element`의 `extra_metadata` | 도메인별 추가 필드 (예: 증권사 리포트 `ticker`) |

- `pipeline_version`: 프롬프트나 후처리 로직을 바꾸면 `PIPELINE_VERSION`을 올립니다. 재처리 대상은 이 값으로 고릅니다.
- `model_name`: 추출 당시 환경변수 `VISION_MODEL` 값을 그대로 저장합니다.
- 검색용 Qdrant payload(`ElementSearchPayload`)는 요소 + 문서 메타데이터(`doc_name`, `doc_title`, `doc_type`, `domain`, `source_org`, `authors`, `publish_date`, `collection_id`)를 합친 것입니다.
- **만드는 곳**: `doc_id` 발급과 문서 메타데이터 추출은 orchestrator가 문서마다 1회 합니다. extractor는 `Element`만 반환하고, orchestrator가 문서 메타데이터를 합쳐 `ElementSearchPayload`를 만듭니다.

## 8. 좌표 (`bbox`)

- 형식: **`[x0, y0, x1, y1]`**, 페이지 크기 대비 **0~1 정규화**, **좌상단 원점**
- `Detection.bbox`는 병합·패딩 **전**, `Element.bbox`는 병합·패딩 **후** 박스입니다.
- PyMuPDF(pt), YOLO(px), 화면(px)과의 변환은 **`figindex/shared/coords.py`의 함수로만** 합니다. 페이지 크기는 `Page.width_pt`, `Page.height_pt`를 씁니다.
- 설계서 v0.4의 `[ymin, xmin, ymax, xmax]`에서 변경했습니다.

## 9. 표 수치 저장 규칙 (`TableData`)

| 원문 | 저장값 | 비고 |
| --- | --- | --- |
| `1,234` | `1234` | 쉼표 제거, 숫자 |
| `△1.2`, `(1.2)`, `-1.2` | `-1.2` | 음수 표기 통일 |
| `12.3%` | `12.3` | 단위는 `unit`에만 |
| `2025E` (열 이름) | `"2025E"` | 기간 라벨은 원문 그대로 |
| `-`, `n/a`, 텍스트 | 원문 문자열 | 숫자로 못 읽으면 그대로 |

`rows`의 키는 `columns` 값과 글자 하나까지 같아야 합니다.

### 단위 규칙
- **표 전체가 한 단위**: `unit`에만 기록합니다.
- **행마다 단위가 다름**: `unit_by_row`(행 라벨 ➔ 단위)에 기록하고, 이때 `unit`은 비웁니다(`None`).
- **열마다 단위가 다름**: `unit_by_column`(열 이름 ➔ 단위)에 기록하고, 이때 `unit`은 비웁니다(`None`).
- **셀 단위 구하기**: 다른 코드에서 직접 단위를 판단하지 않고 반드시 `TableData.unit_for(row_label, column)` 메서드로만 구합니다 (`unit_by_row` ➔ `unit_by_column` ➔ `unit` 순 탐색).
- **예시 (실적표)**:
  - `unit_by_row = {"매출액": "십억원", "영업이익률": "%", "EPS": "원"}`
  - `unit = None`
  - 셀 단위 조회: `td.unit_for("매출액", "2025E")` ➔ `"십억원"`, `td.unit_for("EPS", "2025E")` ➔ `"원"`

## 10. 엔티티 사전 (`EntityEntry`)

- 파일: `data/entity_dictionary.csv` (UTF-8), 경로 상수 `ENTITY_DICTIONARY_PATH`
- 열: `entity_name,entity_type,aliases,ticker`
- `aliases`는 `|`로 구분합니다. 예: `SK하이닉스,COMPANY,하이닉스|SK hynix,000660`
- 요소의 `entities`와 검색 필터에는 항상 대표 이름(`entity_name`)을 씁니다.
- `entity_type`: `COMPANY`(기업), `ORG`(기관), `PRODUCT`(제품·기술), `OTHER`

## 11. 데이터셋 용어

| 한글 용어 | 폴더 | 의미 |
| --- | --- | --- |
| 샘플셋 | `data/samples/` | 개발용 PDF (1단계 20건 → 2단계 50건) |
| 시연셋 | `data/demo/` | 시연에 넣을 PDF 100건 |
| 탐지 정답셋 | `data/gt/detection/` | 50페이지의 요소 bbox·유형 정답 |
| 수치 정답셋 | `data/gt/table/` | 표 30개의 `TableData` 정답 |
| 검색 정답셋 | `data/gt/search/` | 검색어 20개와 관련 `element_id` 목록 |

"데이터셋"이라고만 말하지 않고 위 이름 중 하나로 부릅니다. 정답셋 문서는 샘플셋·시연셋과 겹쳐도 되지만, 확신도 가중치 튜닝에 쓴 표는 수치 정답셋 측정에서 빼고 셉니다.

## 12. 평가 지표 정의

| 지표 | 코드명 | 계산 방법 | 목표 |
| --- | --- | --- | --- |
| 크롭 재현율 | `crop_recall` | 탐지 정답셋 요소 중, IoU ≥ 0.5인 요소가 있는 정답 수 ÷ 정답 요소 수 | ≥ 0.85 |
| 유효 JSON 비율 | `table_valid_rate` | TABLE 요소 중 `TableData` 검증 통과 수 ÷ TABLE 요소 수 | ≥ 0.90 |
| 수치 일치율 | `cell_accuracy` | 수치 정답셋의 숫자 셀 중 값이 같은 셀 수 ÷ 숫자 셀 수. 셀은 (첫 열 행 라벨, 열 이름)으로 맞추고, 못 찾은 셀은 틀린 것으로 셈 | ≥ 0.95 |
| 검색 정확도 | `precision_at_5` | 검색어마다 상위 5개 중 검색 정답셋에 있는 요소 비율, 20개 검색어 평균 | ≥ 0.75 |
| 문서 처리 시간 | `doc_latency_sec` | `UPLOADED` → `COMPLETED`까지 걸린 초, 10페이지 문서 기준 | ≤ 15초 |
| 일괄 처리 시간 | `batch_latency_sec` | 등록 작업 생성 → 소속 문서 전부 `COMPLETED`/`FAILED`/`DUPLICATE`까지 걸린 초 | 측정 후 설정 |
| 검색 응답 시간 | `search_latency_sec` | 검색 API 요청 → 응답, 20개 검색어 평균 | ≤ 1.0초 |
| 토큰 절감률 | `token_saving_rate` | 1 − (크롭 입력 토큰 ÷ 전체 페이지 입력 토큰), 같은 문서 기준 | ≥ 0.80 |

IoU = 두 박스가 겹친 넓이 ÷ 두 박스를 합친 넓이. 평가 코드는 이 표의 코드명을 그대로 결과 키로 씁니다.

## 13. 이름 짓기 규칙

- 코드 식별자·DB 필드·API JSON 키: **영어 snake_case** (프론트엔드도 API 키를 그대로 사용)
- Enum 값: **영어 대문자** (`APPROVED`). 단, `LayoutClass`는 모델 출력 그대로
- 한글은 화면 문구와 주석에만
- ID는 모두 UUIDv4 문자열, 이름은 `{대상}_id`
