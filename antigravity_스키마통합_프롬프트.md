# Antigravity 프롬프트: 스키마 통합 (figindex/ 단일화)

**사용법**
- 프롬프트 1부터 6까지 **순서대로 하나씩** 넣습니다. 한 번에 다 넣지 않습니다.
- 각 프롬프트가 끝나면 보고 내용을 확인하고 커밋한 뒤 다음으로 넘어갑니다.
- 문제가 생기면 그 단계 커밋만 되돌리면 됩니다.
- 프롬프트 1의 조사 결과(특히 bbox)가 이상하면 진행을 멈추고 결과를 먼저 공유합니다.

---

## 프롬프트 1. 준비와 조사 (코드 수정 없음)

```
AGENTS.md, app/schemas.py, docs/glossary.md를 먼저 읽고 따를 것.

목표: figindex/ 앱을 app/schemas.py 기준으로 통합하기 전에 현재 상태를 조사한다. 이 단계에서는 코드를 고치지 않는다.

1. git에서 새 브랜치 refactor/schema-unify를 만든다.
2. Qdrant 서버(http://qdrant:6333)의 figindex_elements 컬렉션 스냅샷을 만들어 figindex/data/backup/ 에 저장한다. 저장 경로와 파일 크기를 보고한다.
3. bbox 실제 값 확인:
   - figindex_elements에서 TABLE, CHART, DIAGRAM 각 3건 이상, 총 10건을 무작위로 뽑는다.
   - 각 건의 bbox 원본 값, page_number, 원본 PDF 페이지 크기(PyMuPDF pt), 크롭 이미지 크기(px)를 표로 정리한다.
   - 원본 PDF 해당 페이지에 bbox를 그려 실제 요소 위치와 맞는지 확인한다. 아래 4가지를 판정한다.
     a) 값의 순서: [ymin, xmin, ymax, xmax]인지 [x0, y0, x1, y1]인지
     b) 단위: 0~1 정규화인지, 0~1000인지, pt인지, px인지
     c) 패딩 포함 여부
     d) 10건 모두 같은 규칙인지 (섞여 있으면 어떤 건이 다른지)
   - 시각화 이미지는 figindex/data/backup/bbox_check/ 에 저장한다.
4. 옛 이름 사용처 목록: figindex/ 전체(pipeline, backend, frontend, shared, scripts, 테스트)에서 아래 이름이 쓰인 파일과 줄 수를 정리한다.
   VisualElementSchema, TableStructure, title_or_caption, structured_data, bbox를 읽거나 쓰는 코드,
   그리고 AGENTS.md "쓰지 않는 이름" 표에 있는 이름 전부.
5. Qdrant payload 실제 필드 목록: 525건 전체의 payload 키를 모아 키별 등장 횟수를 정리한다. app/schemas.py의 ElementSearchPayload에 없는 키와, ElementSearchPayload 필수 필드 중 payload에 없는 키를 따로 표시한다.
6. Qdrant 벡터 구성: 컬렉션의 named vector 이름(dense, sparse)과 설정을 정리한다.
7. 루트 app/ 폴더를 import하거나 참조하는 코드가 figindex/ 안에 있는지 확인한다.

결과를 docs/migration/inventory.md로 저장하고, 마지막에 "bbox 판정 결과"를 3줄로 요약해 보고한다. 코드 파일은 수정하지 않는다.
```

---

## 프롬프트 2. 기준 파일 위치 옮기기

```
AGENTS.md, app/schemas.py, docs/glossary.md를 먼저 읽고 따를 것.
이번 작업은 사용자가 명시적으로 요청한 것이므로 AGENTS.md, docs/glossary.md, schemas.py 수정을 허용한다.

목표: 표준 스키마를 실제 실행 앱(figindex/) 안으로 옮겨 기준을 하나로 만든다.

1. 기존 figindex/shared/schemas.py를 figindex/shared/legacy_schemas.py로 이름을 바꾼다.
   파일 맨 위에 "마이그레이션 스크립트 전용. 다른 코드에서 import 금지" 주석을 단다.
2. app/schemas.py 내용을 figindex/shared/schemas.py로 그대로 옮긴다. 내용은 바꾸지 않는다.
   단, 파일 상단 docstring의 경로 언급만 새 위치에 맞게 고친다.
3. ENTITY_DICTIONARY_PATH가 백엔드·파이프라인 컨테이너 안에서 실제 figindex/data/entity_dictionary.csv를 가리키도록 확인한다. 상대경로로 안 맞으면 환경변수 ENTITY_DICTIONARY_PATH로 덮어쓸 수 있게만 바꾸고, 기본값은 유지한다.
4. 루트 app/ 폴더 전체를 archive/app_v0_3/ 로 옮긴다. (app/schemas.py는 2번에서 옮겼으므로 archive에는 원본 사본으로 남는다)
   루트 data/entity_dictionary.csv가 있으면 figindex/data/entity_dictionary.csv와 비교해 행을 합친 뒤 figindex 쪽만 남긴다.
5. AGENTS.md 수정:
   - 모든 "app/schemas.py" → "figindex/shared/schemas.py"
   - 모든 "app/coords.py" → "figindex/shared/coords.py"
   - import 예시 "from app.schemas import ..." → 실제 figindex 코드에서 동작하는 import 경로로 (backend, pipeline 각각 확인 후 기재)
   - 다음 규칙 추가: "archive/ 폴더의 코드는 읽거나 참고하지 않는다", "legacy_schemas.py는 scripts/migrate_to_v2.py에서만 import한다"
6. docs/glossary.md의 같은 경로 언급도 모두 새 경로로 고친다.
7. 프로젝트 전체에서 "app/schemas.py", "app/coords.py" 문자열이 남아 있는지 검색해 보고한다 (archive/ 제외).
8. docker compose로 backend를 다시 띄워 import 오류 없이 기동되는지 확인한다. (이 시점에는 backend가 아직 legacy 이름을 쓰므로, legacy_schemas.py import로 임시 연결해 기동만 유지한다. 이 임시 연결 위치를 보고한다)

보고: 옮긴 파일 목록, 고친 경로 목록, 임시 연결 위치, backend 기동 결과.
```

---

## 프롬프트 3. 좌표 모듈 만들기

```
AGENTS.md, figindex/shared/schemas.py, docs/glossary.md를 먼저 읽고 따를 것.
docs/migration/inventory.md의 "bbox 판정 결과"를 반드시 읽고 따를 것.

목표: figindex/shared/coords.py를 만든다. 앞으로 모든 좌표 변환은 이 파일 함수로만 한다.

표준: bbox = [x0, y0, x1, y1], 페이지 크기 대비 0~1 정규화, 좌상단 원점.

만들 함수 (이름 그대로):
- pt_to_norm(bbox_pt, width_pt, height_pt) -> BBox      # PyMuPDF pt → 표준
- norm_to_pt(bbox, width_pt, height_pt) -> list[float]  # 표준 → pt (크롭·하이라이트용)
- px_to_norm(bbox_px, img_w, img_h) -> BBox             # YOLO·렌더 이미지 px → 표준
- norm_to_px(bbox, img_w, img_h) -> list[int]           # 표준 → 화면/이미지 px
- legacy_to_norm(legacy_bbox, **필요한 인자) -> BBox      # 기존 Qdrant bbox → 표준. inventory.md 판정 결과대로 구현
- pad_norm(bbox, pad_x, pad_y) -> BBox                  # 정규화 단위 패딩
- union_bbox(boxes: list[BBox]) -> BBox                 # 캡션·각주 병합
- iou(a: BBox, b: BBox) -> float                        # 평가 지표용
- validate_bbox(bbox) -> BBox                           # 0~1 범위로 자르고 x0<x1, y0<y1 확인. 위반 시 ValueError

규칙:
- 반환값은 항상 표준 형식. 0~1 밖의 값은 잘라낸다(clamp).
- 함수마다 docstring에 입력 단위·출력 단위를 적는다.
- BBox 타입은 figindex/shared/schemas.py에서 import한다.

테스트: figindex/shared/test_coords.py
- 왕복 변환(pt→norm→pt, px→norm→px)이 소수점 오차 1e-6 이내로 같은지
- legacy_to_norm: inventory.md의 bbox 확인 10건을 실제 입력·기대값으로 사용
- union_bbox, iou 기본 사례
- validate_bbox의 잘라내기와 ValueError

보고: 함수 목록, 테스트 결과(통과/실패 수).
```

---

## 프롬프트 4. 코드 이름 바꾸기 (파이프라인 → 백엔드 → 프론트)

```
AGENTS.md, figindex/shared/schemas.py, docs/glossary.md, docs/migration/inventory.md를 먼저 읽고 따를 것.

목표: figindex/ 코드가 legacy_schemas.py 대신 schemas.py만 쓰도록 바꾼다. inventory.md 4번의 옛 이름 사용처를 전부 처리한다.
아래 순서대로 진행하고, 각 단계가 끝날 때마다 테스트를 돌린다.

[A. 파이프라인 figindex/pipeline/]
- 결과물을 Element / ElementSearchPayload로 만든다. Qdrant에는 ElementSearchPayload.model_dump(mode="json")을 payload로 쓴다.
- title_or_caption → caption, structured_data → table_data(TableData), 요소 유형은 ElementType, 상태는 ReviewStatus.
- bbox는 coords.py 함수로만 만든다 (PyMuPDF pt → pt_to_norm, YOLO px → px_to_norm).
- 역할 분리: orchestrator가 문서 처리를 시작할 때 Document 객체를 만들어 doc_id(UUIDv4)를 발급하고 문서 메타데이터를 1회 추출한다. extractor는 doc_id를 받아 Element 목록만 반환한다. orchestrator가 Element + Document 메타데이터로 ElementSearchPayload를 만들어 Qdrant에 쓴다. Document는 이번에는 저장하지 않고 메모리에서만 쓴다.
- 새 필드: doc_id(같은 문서의 모든 요소가 공유), model_name(환경변수 VISION_MODEL), pipeline_version(PIPELINE_VERSION), signals(ConfidenceSignals, 지금 계산하는 신호만 채우고 나머지 None).
- hashtags는 '#' 없이 저장.
- 기존 REPORT 하위 호환 필드(company, broker, ticker, analyst)와 target은 extra_metadata 안에만 둔다.
- 확신도 임계값은 CONFIDENCE_THRESHOLD만 쓴다.
- Qdrant 컬렉션 이름은 환경변수 QDRANT_COLLECTION으로 받고, 기본값은 figindex_elements_v2.
- Document, Page, Batch, ReviewLog 저장소는 이번 작업에서 만들지 않는다 (다음 단계).
- 기존 테스트(test_metadata_generalization.py 등)를 새 이름에 맞게 고쳐 모두 통과시킨다.

[B. 백엔드 figindex/backend/]
- 응답 모델과 필터를 schemas.py 이름으로 바꾼다. API JSON 키는 schemas.py 필드명 그대로(snake_case).
- 컬렉션 이름은 QDRANT_COLLECTION 환경변수 (기본 figindex_elements_v2).
- 2단계에서 넣은 legacy_schemas.py 임시 연결을 제거한다.
- 바뀐 API 응답 키 목록(옛 키 → 새 키)을 docs/migration/api_changes.md에 정리한다.

[C. 프론트 figindex/frontend/]
- api_changes.md를 기준으로 타입과 화면 코드의 키를 바꾼다. camelCase로 바꾸지 않는다.
- bbox를 화면에 그리는 코드가 있으면 새 형식([x0, y0, x1, y1], 0~1)에 맞게 고친다.
- docTypeLabels.ts의 라벨 동작은 유지한다.

[마무리]
- figindex/ 전체에서 inventory.md 4번의 옛 이름이 legacy_schemas.py와 scripts/migrate_to_v2.py 외에 남아 있지 않은지 검색해 보고한다.
- docker-compose.yml에 QDRANT_COLLECTION=figindex_elements_v2를 추가한다.

보고: 바꾼 파일 목록, 남은 옛 이름 검색 결과, 테스트 결과, schemas.py에 추가가 필요하다고 판단한 항목.
```

---

## 프롬프트 5. 기존 525건 새 컬렉션으로 옮기기

```
AGENTS.md, figindex/shared/schemas.py, docs/glossary.md, docs/migration/inventory.md를 먼저 읽고 따를 것.

목표: 다시 색인하지 않고(Gemini 호출 0건) 기존 figindex_elements의 525건을 figindex_elements_v2로 옮긴다. 기존 컬렉션은 절대 수정·삭제하지 않는다.

scripts/migrate_to_v2.py를 만든다.
- 옵션: --dry-run(쓰지 않고 변환 결과만 검증), --limit N, --source figindex_elements, --target figindex_elements_v2
- target 컬렉션이 이미 있으면 --force 없이는 중단한다.
- target 컬렉션은 source와 같은 벡터 설정(dense 1536 Cosine + sparse)으로 만든다 (inventory.md 6번).
- source의 모든 point를 벡터 포함(with_vectors=True)으로 읽어, 벡터는 그대로 복사하고 payload만 변환한다. point id도 그대로 쓴다.

payload 변환 규칙 (legacy_schemas.py로 읽고 schemas.py ElementSearchPayload로 검증):
- element_id: 기존 값 유지
- doc_id: uuid5(NAMESPACE_URL, "figindex:" + doc_name) — 같은 문서의 요소가 같은 doc_id를 갖게 한다
- caption ← title_or_caption
- table_data ← structured_data를 TableData로 검증. 실패하면 table_data=None, 원본은 extra_metadata["legacy_structured_data"]에 보관하고 실패 건수를 센다
- bbox ← coords.legacy_to_norm(...)
- hashtags: 앞의 '#' 제거
- signals: 전부 None
- pipeline_version: "0.0.0-legacy"
- model_name: payload에 모델 정보가 있으면 그 값, 없으면 "legacy-unknown"
- confidence_score, review_status, element_type, page_number, image_path, entities: 기존 값 유지
- 문서 메타데이터(doc_name, doc_title, doc_type, domain, source_org, authors, publish_date)와 extra_metadata(target, company, broker, ticker, analyst 등): 기존 값 유지
- 위에 없는 기존 키는 버리지 말고 extra_metadata["legacy"] 안에 넣는다

실행 순서:
1. --dry-run으로 전체 실행. 변환 성공/실패 수, table_data 검증 실패 수, extra_metadata["legacy"]로 들어간 키 목록을 보고하고 여기서 멈춘다.
2. (사용자 확인 후) 실제 실행.
3. 검증: source 525건 = target 525건, 문서 유형별·검수 상태별 개수가 source와 같은지, 무작위 10건의 dense 벡터가 source와 같은지 확인한다.

결과를 docs/migration/migrate_report.md에 저장한다.
```

---

## 프롬프트 6. 최종 확인

```
AGENTS.md를 먼저 읽고 따를 것.

목표: 통합 후 앱이 이전과 똑같이 동작하는지 확인한다.

1. docker compose로 qdrant, backend, frontend를 다시 띄운다 (QDRANT_COLLECTION=figindex_elements_v2).
2. GET /api/version, /api/elements?limit=100, /api/filter-options가 정상 응답하는지 확인한다.
3. 프론트엔드(http://localhost:3000)에서 "Qdrant 색인: 525건"이 보이는지, 오류 배너가 없는지 확인한다.
4. TABLE, CHART, DIAGRAM 각각 2건 이상, 총 10건을 골라:
   - 카드의 캡션·요약·태그가 보이는지
   - 원문 보기에서 올바른 page_number로 이동하는지
   - bbox 하이라이트(있다면)가 실제 요소 위치와 맞는지
   - TABLE은 표 데이터가 렌더링되는지
5. scripts/concurrency_check.py를 새 컬렉션 기준으로 실행해 40/40 200 OK인지 확인한다.
6. 문서 유형·출처 필터가 이전처럼 동작하는지 확인한다.
7. README.md의 실행 안내에서 바뀐 부분(QDRANT_COLLECTION, 스키마 위치)을 고친다.

결과를 docs/migration/verify_report.md에 저장하고, 문제가 없으면 refactor/schema-unify 브랜치의 PR 설명문 초안을 작성한다. PR 설명에는 바뀐 이름 표, 마이그레이션 결과 수치, 되돌리는 방법(QDRANT_COLLECTION을 figindex_elements로 바꾸면 이전 데이터로 복귀)을 넣는다.
```
