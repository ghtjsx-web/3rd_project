# API 변경 내역 (v1 ➔ v2 스키마 통합)

이 문서는 4a 단계(백엔드 및 프론트엔드의 v2 컬렉션 전환 및 스키마 단일화)에 따른 API 변경 내역을 정리한 문서입니다.

## 1. 개요
- 기본 대상 컬렉션: `figindex_elements` ➔ `figindex_elements_v2`
- 응답 스키마 모델: `VisualElementSchema` (legacy) ➔ `ElementSearchPayload` (`shared.schemas.py`)
- 표 구조 모델: `TableStructure` (legacy) ➔ `TableData` (`shared.schemas.py`)

---

## 2. API 응답 키 변경 (ElementSearchPayload)

| 이전 키 (v1 / legacy) | 새 키 (v2 / 표준) | 타입 | 설명 |
|---|---|---|---|
| `title_or_caption` | `caption` | `str` | 도표/차트의 제목 또는 캡션 (기본값: `""`) |
| `structured_data` | `table_data` | `Optional[TableData]` | 복원된 표 구조 데이터 (`TableData` 스키마) |
| `entities` | (제거 / BaseDocument) | - | 메타데이터 정규화에 통합 |
| `extra_metadata` | (제거 / 상속 필드) | - | `doc_title`, `doc_type`, `source_org`, `authors`, `publish_date` 등 상속 필드로 직접 평탄화 |

---

## 3. 새로 추가된 응답 키

| 필드명 | 타입 | 기본값 / 설명 |
|---|---|---|
| `doc_id` | `str` | 원문 문서의 SHA-256 기반 16자리 고유 식별자 |
| `signals` | `Optional[ConfidenceSignals]` | 확신도 산출에 사용된 4대 신호 (`layout`, `ocr`, `clip`, `text_match`) |
| `pipeline_version` | `str` | 색인 생성에 사용된 파이프라인 버전 (예: `"0.2.0"`) |
| `model_name` | `Optional[str]` | 추출/요약에 사용된 LLM 모델명 |
| `table_data.unit_by_row` | `Dict[str, str]` | 표 행 라벨(첫 열 값)별 단위 맵 (예: `{"매출액": "십억원"}`) |
| `table_data.unit_by_column` | `Dict[str, str]` | 표 열 이름별 단위 맵 (예: `{"2023": "억원"}`) |

---

## 4. API 요청 모델 변경 (`POST /api/review/{element_id}`)

### `ReviewActionRequest`
검수 승인/반려 시 요청 페이로드가 `shared.schemas.py`의 표준 규격으로 단일화되었습니다.

| 이전 요청 키 | 새 요청 키 | 필수 여부 | 설명 |
|---|---|---|---|
| `action` | `review_action` | **필수** | `"APPROVE"` 또는 `"REJECT"` |
| `title_or_caption` | `caption` | 선택 | 수정된 도표 제목/캡션 |
| `structured_data` | `table_data` | 선택 | 수정된 표 구조 데이터 (`TableData` 형식) |
| `element_type` | `element_type` | 선택 | 수정된 요소 유형 (`TABLE`, `CHART`, `DIAGRAM`) |
| `summary` | `summary` | 선택 | 도표 요약 텍스트 |

---

## 5. 영향받는 엔드포인트 목록
- `GET /api/elements`: 응답 목록 모델 `List[ElementSearchPayload]`
- `GET /api/search`: 응답 목록 모델 `List[ElementSearchPayload]`
- `GET /api/review/elements`: 응답 목록 모델 `List[ElementSearchPayload]`
- `GET /api/elements/{element_id}`: 단일 응답 모델 `ElementSearchPayload`
- `POST /api/review/{element_id}`: 단일 응답 모델 `ElementSearchPayload`, 요청 모델 `ReviewActionRequest`

## 6. PDF 묶음 업로드
- POST /api/batches: multipart/form-data의 files 항목으로 PDF 여러 개를 받습니다.
- 응답은 List[Document]이며 각 문서의 batch_id, doc_id, doc_hash, doc_name, doc_status를 반환합니다.
- 파일과 Batch·Document 정보는 data/pdfs/와 data/metadata.sqlite3에 저장합니다.
- 같은 doc_hash가 이미 등록되어 있으면 doc_status=DUPLICATE, doc_error에 기존 doc_id를 반환합니다.
- 기존 파일명과 다른 내용이 충돌하면 파일을 덮지 않고 doc_status=FAILED로 기록합니다.
- 이 API는 업로드와 중복 판정만 하며 파이프라인을 실행하지 않습니다.
