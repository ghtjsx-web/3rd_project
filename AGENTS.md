# AI 코딩 규칙 (FigIndex)

이 저장소에서 코드를 작성·수정하는 모든 AI 에이전트는 작업 전에 이 파일, `figindex/shared/schemas.py`, `docs/glossary.md`를 읽고 따른다.

## 1. 이름은 만들지 말고 가져다 쓴다
- 필드명, 상태값, 요소 유형, ID 이름은 `figindex/shared/schemas.py`에 정의된 것만 사용한다.
- 모델과 Enum은 `from shared.schemas import ...`로 가져온다. 같은 모델을 다른 파일에 다시 정의하지 않는다.
- `"APPROVED"`, `"TABLE"` 같은 문자열을 직접 쓰지 않고 `ReviewStatus.APPROVED`, `ElementType.TABLE`을 쓴다.
- 확신도 임계값은 `CONFIDENCE_THRESHOLD`만 쓴다. `0.8`을 직접 쓰지 않는다.
- 필요한 이름이 schemas.py에 없으면 **새로 만들지 말고 작업을 멈추고** "schemas.py에 추가가 필요한 항목"으로 보고한다.
- `shared/schemas_legacy.py`는 임시 호환용이며 새 코드에서 import하지 않는다.

## 2. 쓰지 않는 이름
| 쓰지 말 것 | 대신 쓸 것 |
| --- | --- |
| `figure`, `chart_item`, `visual`, `item` | `element` |
| `pdf_id`, `file_id`, `document_id` | `doc_id` |
| `filename`, `file_name` | `doc_name` |
| `page`, `page_idx`, `page_no` | `page_number` (1부터) |
| `type`, `category`, `kind` (요소 유형) | `element_type` |
| `status` (단독) | `doc_status` 또는 `review_status` |
| `title`, `title_or_caption` | 문서는 `doc_title`, 요소는 `caption` |
| `tags` | `hashtags` |
| `structured_data`, `table_json` | `table_data` |
| `confidence`, `score` | `confidence_score` |
| `done`, `success`, `completed`(소문자) | `DocStatus.COMPLETED` |
| `job`, `job_id`, `upload_id`, `task_id` (등록 묶음) | `batch_id` |
| `checksum`, `md5`, `file_hash` | `doc_hash` (SHA-256) |
| `box`, `prediction`, `yolo_result` | `Detection` |
| `label`, `cls` (탐지 클래스) | `layout_class` |
| `conf`, `yolo_score` | `detection_score` |
| `history`, `audit_log`, `feedback` | `ReviewLog` |
| `action` (검수) | `review_action` |
| `version`, `prompt_version` | `pipeline_version` |
| `model`, `llm_model` | `model_name` |
| `text_layer`, `is_vector` | `has_text_layer` |

## 3. 좌표
- `bbox`는 `[x0, y0, x1, y1]`, 0~1 정규화, 좌상단 원점이다.
- 좌표 변환은 `figindex/shared/coords.py`의 함수만 사용한다. 파일이 없거나 필요한 함수가 없으면 그 파일에 추가하고, 다른 파일에서 직접 계산하지 않는다.

## 4. 표 수치
- `TableData`의 셀 값 규칙(쉼표 제거, 음수 통일, 단위는 `unit`에만, 못 읽으면 원문 문자열)은 `docs/glossary.md` 7절을 따른다.
- `rows`의 키는 `columns` 값과 정확히 같아야 한다.

## 5. 그 밖의 고정 규칙
- 추출 로직(프롬프트·후처리)을 바꾸면 `PIPELINE_VERSION`을 올리라고 보고한다. 직접 올리지 않는다.
- `ReviewLog`는 추가만 한다. 수정·삭제 코드를 만들지 않는다.
- 확신도 가중치는 `SIGNAL_WEIGHTS`만 쓰고, 적용하지 않은 신호는 `None`으로 둔다.
- YOLO 클래스 처리는 `LAYOUT_TO_ELEMENT`, `MERGE_CLASSES`만 쓴다.
- 고유명사는 엔티티 사전의 `entity_name`으로 바꿔 저장한다.
- 평가 결과의 키는 `docs/glossary.md` 12절의 지표 코드명을 그대로 쓴다.

## 6. 이름 규칙
- Python 식별자, DB 컬럼, API JSON 키: 영어 snake_case.
- 프론트엔드는 API JSON 키를 camelCase로 바꾸지 않고 그대로 쓴다. 타입은 백엔드 OpenAPI 명세에서 생성한다.
- 한글은 화면 문구와 주석에만 쓴다.

## 7. 수정 금지 파일
- `figindex/shared/schemas.py`, `docs/glossary.md`, `AGENTS.md`, `scripts/check_config.json`, `scripts/check_baseline.json`은 사용자가 명시적으로 요청한 경우에만 수정한다. 수정할 때는 관련 파일의 내용이 서로 맞는지 확인한다.
- AI는 `--save-baseline`을 실행하지 않는다. 기준선 저장은 팀장만 한다.

## 8. 작업 보고
작업이 끝나면 다음을 짧게 보고한다.
- 바꾼 파일 목록
- 새로 쓴 schemas.py 항목이 있는지 (있으면 안 됨, 1절 참고)
- schemas.py 추가가 필요하다고 판단한 항목
- `python scripts/check_state.py --quick --expect "바꾼 파일 목록"` 결과 요약 (FAIL이 있으면 고친 뒤 다시 실행)
