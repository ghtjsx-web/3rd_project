# FigIndex 프로젝트 현재 진행 상태 요약 (AI 분석·인수인계용)

> 작성 시각: 2026-11-13  
> 기준 커밋: `2864055` (`데이터셋정리 및 규칙설정`) · 현재 브랜치: `refactor/schema-unify`  
> 저장소 루트: `c:\workAi\workProject\3차플젝`

이 문서는 다른 AI에 업로드하여 **현재 구현 상태, 구조적 이원화 지점, 남은 작업**을 빠르게 파악하고 다음 단계 설계를 논의할 수 있도록 정리한 현황서입니다.

---

## 1. 프로젝트 개요 및 실행 환경

- **목적**: PDF 문서(증권 리포트, 공공 보고서, 학술 논문, IR 자료)에서 표(`TABLE`), 차트(`CHART`), 다이어그램(`DIAGRAM`)만 추출·구조화하여 검색·비교·검수하는 지식 도서관 시스템
- **기술 스택**:
  - **Frontend**: Next.js 14 (`react-pdf`, Tailwind CSS, 포트 `3000`)
  - **Backend**: FastAPI (`uvicorn`, 포트 `8000`)
  - **Vector DB**: Qdrant (`figindex_elements` 컬렉션, `dense` 1536차원 Cosine + `sparse` BM25, 포트 `6333`/`6334`)
  - **Pipeline**: PyMuPDF(`fitz`), `kiwipiepy`, `doclayout-yolo`, Gemini Multimodal API, OpenAI Embeddings (`text-embedding-3-small`)
- **현재 로컬 Docker 실행 상태 (`figindex/docker-compose.yml`)**:
  - `figindex-qdrant`, `figindex-backend`, `figindex-frontend` 3개 서비스가 정상 가동 중 (`QDRANT_MODE=server`)
  - `pipeline` 서비스는 `profiles: ["index"]`로 분리되어 필요 시 `docker compose run --rm pipeline ...`로 실행
  - 로컬 프로덕션 검증용 `figindex/docker-compose.prod.yml` 별도 구성 완료
  - Onpod 배포용 기본값(`frontend/Dockerfile`의 `NEXT_PUBLIC_API_URL=https://figindex-api.onpod.ai`, `backend/Dockerfile`의 `QDRANT_MODE=local`)은 유지됨

---

## 2. 가장 중요한 구조적 특징 (AI 분석 시 필독)

기준 스키마의 위치가 **`figindex/shared/schemas.py`로 단일화**되었으며, 525건 실서비스 호환을 위해 구 모델은 `figindex/shared/schemas_legacy.py`로 분리 관리되고 있습니다.

### A. 현재 동작 중인 서비스와 스키마 구성 (`figindex/shared/`)
- **표준 스키마 (SSOT)**: `figindex/shared/schemas.py`
  - `Element`, `ElementSearchPayload`, `TableData`, `ConfidenceSignals`, `Document`, `Batch`, `ReviewLog` 등 11개 표준 모델 및 `CONFIDENCE_THRESHOLD`, `SIGNAL_WEIGHTS` 등 상수/Enum 정의 완료.
- **임시 호환 스키마**: `figindex/shared/schemas_legacy.py`
  - `VisualElementSchema`, `TableStructure` (프롬프트 4의 코드 필드 치환 완료 전까지 백엔드·파이프라인이 임시 참조).
- **루트 `app/schemas.py`**:
  - `figindex/shared/schemas.py`로 이전 안내하며 `ImportError` 발생 처리 (루트 `app/`은 차후 archive 예정).

### B. 최신 코딩 규칙·표준 스키마 축 (`AGENTS.md`, `figindex/shared/schemas.py`, `docs/glossary.md`)
- **규칙 준수**: 모든 새 코드 및 리팩토링은 `figindex/shared/schemas.py`에 정의된 필드와 모델만 사용 (`AGENTS.md`, `docs/glossary.md` 참조).
- **주요 필드/규격 차이 (프롬프트 4 & 5 마이그레이션 대상)**:
  - `VisualElementSchema` → `Element` / `ElementSearchPayload`
  - `title_or_caption` → 문서 `doc_title`, 요소 `caption`
  - `structured_data` → `table_data` (`TableData`)
  - `bbox` → `[x0, y0, x1, y1]` (0~1 정규화, 좌상단 원점), 좌표 변환은 `figindex/shared/coords.py` 사용 규칙(프롬프트 3 작성 대상)

---

## 3. 최근까지 완료된 주요 작업

1. **다중 문서 유형 및 파일명 파서 지원 (`figindex/pipeline/orchestrator.py`, `run_index.py`)**
   - 파일명 형식 A(`{코드}_{날짜}_{대상}_{출처}.pdf`), B(`{한글종류}_{날짜}_{주제}_{출처}.pdf`), C(`{한글종류}{YYYYMMDD}{제목}_{출처}.pdf`) 해석 지원
   - 문서 유형: `REPORT`, `PUBLIC_REPORT`, `PAPER`, `IR`
   - 증권사 별칭 정규화(`BROKER_ALIASES`) 및 `--types`, `--limit`, `--max-pages`, `--max-elements`, `--dry-run` CLI 옵션 추가
   - 단위 테스트 17건 통과 (`figindex/pipeline/test_metadata_generalization.py`)

2. **메타데이터 일반화 ("증권사/기업명" → "출처/대상")**
   - `source_org`(출처) + `extra_metadata["target"]`(대상) 공통 구조 적용 (`REPORT`일 때만 하위 호환용 `company`, `broker`, `ticker`, `analyst` 유지)
   - 프론트엔드 `docTypeLabels.ts`로 선택한 `doc_type`에 따라 드롭다운 라벨 동적 변경 (`증권사/기업명`, `발행기관/주제`, `학회·기관/논문 제목`, `기업/보고서명`)
   - 기존 Qdrant 데이터 보정 스크립트 `scripts/migrate_source_target.py` 작성

3. **로컬 Docker 핫 리로드 및 환경변수 정리 (`figindex/docker-compose.yml`)**
   - 프론트엔드 `npm run dev` + `NODE_ENV=development` + `NEXT_PUBLIC_API_URL=http://localhost:8000` + 폴링(`WATCHPACK_POLLING`, `CHOKIDAR_USEPOLLING`) 적용, 익명 `.next` 볼륨 제거
   - 백엔드 `uvicorn --reload --reload-dir /app/app --reload-dir /app/shared` + `WATCHFILES_FORCE_POLLING=true` 적용
   - `GET /api/version` 추가 및 개발 모드 하단 API/버전 상태 표시

4. **Qdrant 잠금 충돌 해결, 전역 예외 JSON화, 서버 모드 전환**
   - `figindex/backend/app/main.py`: `QdrantClient` 프로세스당 단일 인스턴스화, `lifespan` 종료 시에만 `close()`, 로컬 모드 전용 `threading.RLock` 보호(`qdrant_call_guard`), CORS 헤더 포함 `@app.exception_handler(Exception)` 500 JSON 반환
   - `figindex/pipeline/orchestrator.py`: 프로세스당 단일 `QdrantClient` 재사용, `atexit` 정리, `QDRANT_MODE=local` 실행 시 백엔드와 동시 실행 경고 로그 출력
   - `figindex/frontend/app/page.tsx`: API 실패 시 `"Failed to fetch"` 대신 에러 JSON(`type`, `error`, `path`) 또는 `"백엔드에 연결할 수 없음 (주소: ...)"` 표시
   - `scripts/local_to_server.py`: `/data/qdrant_local` → `http://qdrant:6333` 안전 이전 스크립트 (`--force` 없을 시 기존 데이터 보호)
   - `scripts/concurrency_check.py`: `/api/elements?limit=100` + `/api/filter-options` 동시 20쌍(40건) 요청 검증 통과 (로컬 모드 40/40 `200 OK`, 서버 모드 40/40 `200 OK`)

5. **DocLayout-YOLO 시험 스크립트 (`figindex/pipeline/yolo_trial.py`)**
   - `juliozhao/DocLayout-YOLO-DocStructBench` 모델로 탐지 결과 시각화 및 기존 `PDFCropper`와 비교하는 시험 스크립트 작성 완료 (본 파이프라인 `cropper.py`에는 아직 미통합)

6. **스키마 통합 1단계 조사 완료 (`docs/migration/inventory.md`) 및 표준 문서 보완**
   - `refactor/schema-unify` 브랜치 생성 및 Qdrant `figindex_elements` 전체 스냅샷 백업 완료 (`figindex/data/backup/figindex_elements-1851693946944154-2026-11-12-08-04-40-1.snapshot`, `1,319,749,632 bytes` / 약 `1.23 GiB`, `.gitignore`로 제외됨)
   - `bbox` 10건 시각화(`figindex/data/backup/bbox_check/`) + 525건 전수 검사 완료: 전체가 `[ymin, xmin, ymax, xmax]`, `0~1` 정규화(좌상단 원점), **패딩 포함** 규격으로 일관되며 위반 건 `0건`
   - `figindex/` 및 `scripts/` 옛 이름 사용처·루트 `app/` 폴백 import·Qdrant 525건 실제 payload 키 통계 정리 완료
   - `app/schemas.py` 및 `docs/glossary.md` 최신 보완 반영:
     - `ElementSearchPayload`에 `authors: List[str]` 추가 (기존 525건의 `authors`를 `extra_metadata["legacy"]`로 밀어 넣지 않고 직접 보존 가능)
     - `docs/glossary.md`에 `doc_id` 발급 및 문서 메타데이터 추출은 `orchestrator`, `Element` 생성은 `extractor`로 역할 분담 명시

7. **필수 코드 및 Qdrant 페이로드 대상 schemas.py 미등재 필드 전수 조사 및 호환성 조치 (2026-11-13)**
   - `app/schemas.py`(11개 모델, 58개 표준 필드) 기준으로 백엔드, 파이프라인, 프론트엔드, Qdrant 페이로드 전수 조사 완료.
   - **즉시 호환 조치 (`figindex/backend/app/main.py`)**:
     - `ReviewActionRequest`: `review_action`, `caption`, `table_data`를 schemas.py 표준 필드로 최우선 수용하고, 기존 프론트엔드 호환용 `action`, `title_or_caption`, `structured_data` 폴백 허용.
     - `GET /api/elements`: 쿼리 파라미터 `review_status`를 표준으로 추가하고 기존 `status` 폴백 지원.
   - **DB 마이그레이션 대상 분리**:
     - Qdrant 컬렉션 실데이터(525건) 및 프론트엔드가 참조하는 `title_or_caption`(`caption`), `structured_data`(`table_data`), `bbox` `[ymin, xmin, ymax, xmax]`(`[x0, y0, x1, y1]`)는 코드만 임의 수정 시 서비스 장애가 발생하므로, `antigravity_스키마통합_프롬프트.md`의 프롬프트 4(코드 치환) 및 프롬프트 5(컬렉션 v2 이전) 단계에서 일괄 전환하기로 확정.
   - **엔티티 무관 내부 필드 구분**:
     - `AdminVerifyRequest.password`(인증 DTO), `cropper.py`의 `crop_info` 임시 반환 키, `orchestrator.py`의 `target/broker/ticker` 등은 `extra_metadata` 내부 저장 및 내부 파이프라인 변수로 정상 분류.

8. **기준 스키마 위치 이전 및 레거시 분리 완료 (프롬프트 2, 2026-11-13)**
   - `app/schemas.py`의 최신 표준 스키마를 `figindex/shared/schemas.py`로 덮어써 Single Source of Truth(SSOT) 단일화 완료.
   - 기존 실서비스 호환을 위해 `VisualElementSchema`, `TableStructure`는 `figindex/shared/schemas_legacy.py`로 임시 분리.
   - `figindex/backend/app/main.py`, `pipeline/extractor.py`, `orchestrator.py`, `evaluator.py`의 import를 `shared.schemas` 및 `shared.schemas_legacy`로 정리하고 `app.schemas` 폴백 import 전면 제거.
   - 루트 `app/schemas.py`는 이동 안내 `ImportError` 파일로 변경.
   - `AGENTS.md`, `docs/glossary.md`, `PROJECT_RULES.md`의 스키마 및 좌표 모듈 참조 경로를 `figindex/shared/`로 갱신 완료 (`app.schemas` 잔존 0건).

9. **환경변수 경로 유연화 및 파이프라인 Docker 빌드 보완 (2026-11-13)**
   - `figindex/shared/schemas.py`: `ENTITY_DICTIONARY_PATH = os.getenv("ENTITY_DICTIONARY_PATH", "data/entity_dictionary.csv")`로 변경하여 호스트 환경과 컨테이너 환경(`/data/entity_dictionary.csv`) 모두 지원.
   - `figindex/pipeline/Dockerfile`: `COPY shared/ /app/shared/` 복사 구문 추가 및 `figindex/docker-compose.yml`의 파이프라인 빌드 컨텍스트를 `.`로 일원화하여 독립 빌드 시 스키마 누락 방지.
   - `docker-compose.yml`, `docker-compose.prod.yml`, `backend/Dockerfile`, `pipeline/Dockerfile`에 `ENTITY_DICTIONARY_PATH=/data/entity_dictionary.csv` 환경변수 반영.

10. **공통 좌표 변환 모듈 및 단위 테스트 작성 완료 (프롬프트 3, 2026-11-13)**
    - `figindex/shared/coords.py` 생성: 표준 라이브러리만을 사용하여 `validate_bbox`, `clip_bbox`, `pt_to_norm`, `norm_to_pt`, `px_to_norm`, `norm_to_px`, `pt_to_px_scale`, `from_legacy_yxyx`, `union_bbox`, `pad_bbox_pt`, `bbox_area`, `iou` 등 12개 좌표 변환·검증 함수 구현.
    - `fitz`, `numpy`, `ultralytics` 등 외부 의존성을 배제하여 백엔드/파이프라인 양쪽에서 경량 import 보장.
    - 단위 테스트 `figindex/pipeline/test_coords.py` 9개 케이스 작성 및 100% 통과 (기존 테스트 17건 포함 총 26건 통과).

11. **상태 검사기 및 회귀 방지 기준선 체계 구축 (`scripts/check_state.py`, 2026-11-13)**
    - 읽기 전용 검사기 `scripts/check_state.py` 및 설정 `scripts/check_config.json` 작성 완료.
    - **A그룹 빠른 검사 (8종)**: A1(Git 변경 범위 및 protected_files 검사), A2(AGENTS.md 금지 이름 실시간 추출 및 엄격/일반 카운트), A3(직접 쓴 상태 문자열), A4(0.8 임계값 리터럴), A5(app.schemas 금지 및 schemas_legacy 참조 감시), A6(Pydantic 모델 중복 정의), A7(Python 문법 컴파일), A8(단위 테스트 결과 파싱).
    - **B그룹 전체 검사 (3종, --full)**: B1(API/Qdrant 개수 일치 및 샘플 조회), B2(Qdrant 525건 스키마 분포 및 BBox 유효성), B3(프론트 TypeScript 타입 검사).
    - `ALLOWED_REQUEST_PATTERNS` 화이트리스트를 통한 안전한 읽기 전용 HTTP 요청 강제.
    - `AGENTS.md` 7절(수정 금지 파일에 check_config, check_baseline 추가 및 save-baseline AI 실행 금지 명시) 및 8절(작업 보고에 check_state 요약 의무화) 반영 완료.

12. **상태 검사기 B1 이미지 응답 처리·A8 pytest 안내·A7 경로 매칭 보완 (2026-11-13)**
    - **B1 샘플 이미지 오류 해결**: `safe_http_request()`가 PNG 바이너리 응답(`/static/crops/*.png`)을 utf-8로 디코드하려다 `UnicodeDecodeError`가 발생하던 검사기 자체 결함을 수정 (`Content-Type: image/` 또는 decode 실패 시 raw bytes 반환). 백엔드와 프론트엔드는 정상(HTTP 200) 확인.
    - **B1 실패 리포트 고도화**: 실패 시 URL과 HTTP 상태 코드를 세부 리포트에 명시하고, 기준선이 없을 때는 "0 ➔ 3 증가" 대신 "실패 N건"으로 표시.
    - **A8 pytest 의존성 및 안내 메시지 추가**: `figindex/pipeline/requirements.txt`에 `pytest>=8.0.0` 추가 완료 및 Docker 실행 시 `No module named pytest` 발생 시 `docker compose build pipeline` 실행 안내 메시지 출력.
    - **A7 검사 파일 수 정상화**: `check_config.json`의 `"app"` 제외 규칙이 `figindex/backend/app`까지 오인 제외하던 문제를 `is_path_excluded`로 수정하여 `main.py` 복원 (대상 Python 파일 18개 ➔ 19개).
    - **기준선 저장 안전조건 강화**: `--save-baseline`은 `--full` 모드에서만 실행 가능하며, FAIL뿐 아니라 SKIP 항목이 하나라도 있을 때도 저장을 거부하도록 수정.

13. **v2 컬렉션 이전 스크립트 및 10종 단위 테스트 작성 (프롬프트 5a-1, 2026-11-13)**
    - **순수 변환 함수 `transform_payload` 구현 (`figindex/pipeline/migrate_to_v2.py`)**:
      - `title_or_caption` ➔ `caption`, `structured_data` ➔ `table_data`(`TableData` 검증), `bbox` `[ymin, xmin, ymax, xmax]` ➔ `coords.from_legacy_yxyx`를 통한 `[x0, y0, x1, y1]` 변환 및 `coords.validate_bbox` 유효성 검사.
      - `authors`는 상위 필드로 직접 보존, TABLE이 아닌 요소의 옛 표 데이터 및 비표준 키는 `extra_metadata["legacy"]`로 안전 격리.
      - 동일 `doc_name`에 대해 단일 `doc_id`(UUIDv4) 매핑 보장.
      - `ElementSearchPayload`를 통한 최종 스키마 검증.
    - **단위 테스트 10종 구현 및 통과 (`figindex/pipeline/test_migrate_to_v2.py`)**:
      - 정상 TABLE, 정상 CHART, 옛 표 없는 TABLE, TableData 검증 실패(키 불일치), target 없는 요소, authors 보존, 레거시 키 격리, bbox 정상 변환, 뒤집힌 bbox 제외, 동일 doc_name doc_id 일치 등 10개 케이스 작성 및 100% 통과 (파이프라인 전체 단위 테스트 36건으로 증가).
    - **Dry-Run 실행 완료 (`figindex/data/migration/dry_run_20261113-1048.md`)**:
      - 원본 525건 중 **525건 전원 변환 성공** (제외: 0건), 고유 문서 142개 식별.
      - `doc_type` 및 `review_status` 분포 100% 일치.
      - `TableData` 검증 실패 13건(키 불일치 등)은 안전하게 `table_data=None` 처리 및 요소 보존.
      - Qdrant 실데이터 쓰기/수정 0건 (읽기 전용 보장, `check_state.py --full` B2 통과로 불변 입증).

14. **문서 이름(doc_name) 142개 vs 118건 정합성 조사 완료 (2026-11-13)**
    - **원인 규명**: Qdrant 142개 중 113개는 루트 파일명과 일치하며, **29개는 `rename_reports.py` 실행 전 과거 이름**(`rename_plan.csv` 기록)으로 현재 새 이름(`RPT_...`)과 함께 **Qdrant에 이중 색인**되어 있음 (113 + 29 = 142개). 루트 PDF 118건 중 5건은 미색인 파일 (113 + 5 = 118).
    - **영향 및 중복도 분석**:
      - 29개 과거 이름 문서는 백엔드 원문 PDF 조회 시 파일이 없어 **404 Not Found (원문 보기 실패)** 발생.
      - 동일 SHA-256 해시 묶음 29개 내에서 동일 페이지 및 IoU ≥ 0.9인 **중복 도표 요소가 60건** 존재.
      - 중복을 제거한 **순수 실제 요소 수는 465건** (525건 - 60건).
      - 디스크 어디에도 파일이 없는 고아 문서는 0건(142건 전체가 실제 PDF와 1:1 대응 확인).
    - **결과물 및 검증**:
      - 조사 리포트(`figindex/data/migration/doc_name_audit_20261113-1111.md`) 및 정리안 CSV(`.csv`) 생성 완료.
      - `audit_doc_names.py` 및 단위 테스트 3종(`test_audit_doc_names.py`) 작성 완료 (파이프라인 단위 테스트 총 39건 100% 통과).
      - `check_state.py --full` 검사 11개 전 항목 통과 (기존 데이터 B2 불변 입증).

15. **v2 마이그레이션 스크립트에 doc_name 정리안 반영 및 최종 dry-run 완료 (프롬프트 5a-2, 2026-11-13)**
    - **팀장 결정 사항 100% 구현 (`figindex/pipeline/migrate_to_v2.py`)**:
      - **doc_name 정리**: `doc_name_audit_20261113-1111.csv` 맵을 적용하여 과거 이름 29개를 실제 PDF 파일명(`canonical_doc_name`)으로 치환. `doc_id`는 대표 이름 기준으로 발급하여 고유 문서 113개로 단일화.
      - **중복 요소 제거 (`filter_duplicate_elements`)**: 동일 PDF·동일 페이지·IoU ≥ 0.9인 옛 이름 쪽 중복 요소 60건을 정밀 필터링하여 제외 (최종 이전 465건 달성). 옛 이름에만 있고 중복이 아닌 요소는 새 이름으로 갱신하여 안전하게 보존.
      - **`pipeline_version` 고정**: 이전되는 모든 레거시 데이터의 버전을 `"0.0.0"`으로 설정.
      - **`table_data` 검증 실패 처리**: `table_data = None`으로 초기화하고, 기존 `APPROVED` 요소 10건을 `PENDING_REVIEW`로 자동 전환하며 `extra_metadata["legacy"]["migration_note"]`에 사유 상세 기록.
      - **예상값 검증 안전장치**: 대상 525건, 제외 60건, 최종 465건, 고유 문서 113개, 원문 누락 0개가 아닐 시 즉시 중단(Abort)하는 방어 로직 내장.
      - **제외 요소 기록**: `--execute` 시 제외된 60건의 메타데이터를 `figindex/data/migration/dropped_elements_YYYYMMDD-HHMM.csv`에 자동 영구 보존.
    - **단위 테스트 5종 추가 구현 및 100% 통과 (`figindex/pipeline/test_migrate_to_v2.py`)**:
      - 옛 이름 ➔ 새 대표 이름 및 doc_id 매핑 일치, 중복 쌍 새 이름 요소만 유지 및 옛 이름 요소 제외, 비중복 옛 요소 보존, TableData 실패 시 APPROVED ➔ PENDING_REVIEW 및 메모 기록, pipeline_version=="0.0.0" 검증 등 총 15개 테스트 작성 완료 (파이프라인 전체 단위 테스트 44건 100% 통과).
    - **최종 dry-run 검증 완료 (`figindex/data/migration/dry_run_v2_final_20261113-1121.md`)**:
      - **대상 525건 ➔ 제외 60건 ➔ 최종 이전 465건, 고유 문서 113개, 원문 누락 0개** 예상 기준치와 100% 일치 확인.
      - 이전 후 검수 상태: `APPROVED` 386건 (83.0%), `PENDING_REVIEW` 79건 (17.0%, TableData 검증 실패 10건 포함).
      - Qdrant 실데이터 쓰기/수정 0건 유지 (읽기 전용 보장, `check_state.py --full` 11개 전 항목 PASS 확인).

---

## 3.5 확인된 문제점 및 기술적 판단 (프롬프트 4~6 진행 전 점검 결과)

1. **`inventory.md`와 최신 `app/schemas.py` 간 `authors` 차이**
   - `inventory.md` 작성 직후 `ElementSearchPayload`에 `authors`가 추가되었으므로, 5단계(`migrate_to_v2.py`)에서는 `authors`를 `extra_metadata["legacy"]`가 아닌 `ElementSearchPayload.authors`로 직접 이관해야 합니다.
2. **`bbox` 형식은 일관되나 기존 크롭/분류 품질 오탐 사례 존재**
   - `bbox` 좌표 규격 자체는 525건 전체가 100% 일관되어 스키마 통합에는 문제가 없습니다 (`[bbox[1], bbox[0], bbox[3], bbox[2]]`로 즉시 변환 가능).
   - 다만 `bbox_check/` 시각화에서 문서 목차가 `TABLE`로(`01_TABLE_fig-b5f2_p6.png`), 회화 사진이 `CHART`로(`05_CHART_fig-e24f_p2.png`) 오분류된 사례가 확인되었습니다. 이는 스키마 통합 이후 DocLayout-YOLO 통합 단계에서 개선해야 할 과제입니다.
3. **`ENTITY_DICTIONARY_PATH` 경로 유연화 (해결 완료)**
   - `os.getenv` 및 컨테이너 환경변수(`ENTITY_DICTIONARY_PATH=/data/entity_dictionary.csv`) 설정으로 호스트·컨테이너 양방향 호환 완료.
4. **`pipeline/Dockerfile`의 `shared/` 복사 누락 (해결 완료)**
   - `pipeline/Dockerfile`에 `COPY shared/ /app/shared/` 추가 및 compose build context `.` 정렬 완료.
5. **기존 525건 마이그레이션 시 불완전 레코드 주의**
   - `structured_data` 누락 1건(`524/525`), `extra_metadata.target` 누락 118건(`407/525`)이 확인되었습니다. `migrate_to_v2.py` 실행 시 `--dry-run`으로 `TableData` 검증 실패 건수를 먼저 확인해야 합니다.
6. **루트 `app/` 폴백 import 잔존 해결 완료**
   - `figindex/pipeline/`의 `evaluator.py`, `extractor.py`, `orchestrator.py`에 남아 있던 `from app.schemas import ...` 폴백이 모두 제거되어 `shared`로 단일화 완료되었습니다.
7. **백엔드 DTO는 표준 수용 완료, Qdrant 및 UI 계층은 마이그레이션 대기 중**
   - `backend/app/main.py`는 `review_action`, `caption`, `table_data`, `review_status`를 수용하도록 업데이트되었으나, 실제 Qdrant 저장 페이로드 및 프론트엔드 연동은 여전히 `title_or_caption`, `structured_data` 기반으로 동작 중입니다. 프롬프트 4 & 5 실행 전까지는 양방향 호환을 유지해야 합니다.
- **종합 판단**: 기준 스키마 위치 이전(프롬프트 2) 및 공통 좌표 모듈 구현(프롬프트 3)이 완료되었으므로, 다음 단계인 **프롬프트 4(코드 레벨 필드명 치환: `title_or_caption` → `caption`, `structured_data` → `table_data`, `bbox` 규격 전환)**로 안전하게 진행 가능합니다.

---

## 4. 현재 데이터 및 검증 현황

- **원본 PDF (`figindex/data/pdfs/`)**: 118건
- **크롭 이미지 (`figindex/data/crops/`)**: 578개 파일
- **Qdrant 서버 (`http://qdrant:6333`, `figindex_elements`)**: **525 points**
  - 문서 유형별: `REPORT` 303, `PAPER` 145, `PUBLIC_REPORT` 76, `IR` 1
  - 검수 상태별: `APPROVED` 455, `PENDING_REVIEW` 70
  - 출처(`source_org`) 64종(`REPORT` 14, `PUBLIC_REPORT` 9, `PAPER` 40, `IR` 1), 대상(`target`) 113종(`REPORT` 47, `PUBLIC_REPORT` 22, `PAPER` 43, `IR` 1)
- **Qdrant 로컬 (`figindex/data/qdrant_local`)**: 118 points (위 525건에 모두 포함됨)
- **엔티티 사전 (`figindex/data/entity_dictionary.csv`)**: 현재 헤더 + `SK하이닉스` 1행만 등록됨
- **프론트엔드(`http://localhost:3000`)**: 헤드리스 Chrome 확인 기준 `Qdrant 색인: 525건`, `100개 표시 중`, `DEV MODE`, 오류 배너 없음 확인

---

## 5. 주요 디렉터리 및 파일 맵

```text
3차플젝/
├── AGENTS.md                           # AI 코딩 규칙 (app/schemas.py, glossary.md 준수 필수)
├── PROJECT_RULES.md                    # 프로젝트 작업 규칙
├── README.md                           # 전체 안내 및 실행 가이드
├── app/                                # [레거시 초기 코드 - archive 이전 예정]
│   ├── schemas.py                      # ImportError 안내 파일 (figindex/shared/schemas.py로 이동됨)
│   ├── main.py                         # v0.3 초기 API 스켈레톤
│   ├── core/, pipeline/, services/
├── docs/
│   ├── glossary.md                     # 용어집 (표 수치, 확신도, 좌표, 평가 지표 정의)
│   └── FigIndex_통합_기획_설계서.md
├── scripts/
│   ├── check_state.py                  # 형상·스키마·테스트 종합 상태 검사기
│   ├── check_config.json               # 상태 검사기 설정 파일
│   ├── local_to_server.py              # qdrant_local -> Qdrant 서버 이전
│   ├── concurrency_check.py            # 동시 40건 API 안정성 검증
│   ├── migrate_source_target.py        # 출처/대상 payload 마이그레이션
│   └── generate_sample_pdf.py
└── figindex/                           # [현재 Docker로 실제 구동 중인 앱]
    ├── docker-compose.yml              # 로컬 개발용 (QDRANT_MODE=server, Hot Reload)
    ├── docker-compose.prod.yml         # 로컬 프로덕션 검증용
    ├── shared/
    │   ├── schemas.py                  # 표준 Single Source of Truth (Element, TableData, ReviewLog 등)
    │   ├── schemas_legacy.py           # 임시 호환용 (VisualElementSchema, TableStructure)
    │   └── coords.py                   # 공통 좌표 변환 모듈 (정규화, pt/px 변환, IoU, 패딩)
    ├── backend/app/main.py             # FastAPI 서버 (포트 8000)
    ├── pipeline/                       # 색인 파이프라인 (run_index.py, orchestrator.py, test_coords.py 등)
    ├── frontend/app/                   # Next.js 14 UI (포트 3000)
    └── data/                           # pdfs(118), crops(578), qdrant(525), qdrant_local(118)
```

---

## 6. 다음 단계 / 검토가 필요한 과제

1. **코드 레벨 필드명 전면 치환 (프롬프트 4)**
   - `title_or_caption` → `caption`, `structured_data` → `table_data`, `VisualElementSchema` → `Element` / `ElementSearchPayload`로 코드베이스 일괄 교체.
   - `figindex/shared/coords.py` 함수들을 `cropper.py`, `extractor.py`에 연결.
2. **Qdrant v2 컬렉션 마이그레이션 (프롬프트 5)**
   - 기존 525건 데이터를 `figindex_elements_v2`로 변환 이전하고 스왑(`alias` 또는 설정 변경).
3. **탐지/추출 고도화 (DocLayout-YOLO & 엔티티 사전)**
   - `yolo_trial.py` 결과를 본 크로퍼(`cropper.py`)에 정식 통합.
   - `ConfidenceSignals` 5개 신호 및 `SIGNAL_WEIGHTS` 재정규화 로직 정렬.
   - `entity_dictionary.csv` 데이터 확충 및 고유명사 치환 적용.
4. **등록 작업·검수 이력·평가 고도화**
   - `Batch`, `Document`, `ReviewLog`(추가 전용 이력) 및 `docs/glossary.md` 12절 지표(`crop_recall`, `table_valid_rate`, `cell_accuracy`, `precision_at_5` 등) 기반 정량 평가 연결

---

## 7. 다른 AI에게 분석 요청할 때 참고 질문 예시

- "첨부한 `PROJECT_STATUS_FOR_AI.md`를 바탕으로, `app/schemas.py` + `AGENTS.md` 기준과 현재 실행 중인 `figindex/` 코드 간의 간극을 메우기 위한 단계별 마이그레이션 계획을 세워줘."
- "기존 Qdrant 데이터(525건)를 깨뜨리지 않으면서 `VisualElementSchema`에서 `ElementSearchPayload`로 안전하게 전환하는 전략을 제안해줘."
- "`yolo_trial.py` 결과를 본 파이프라인 `cropper.py`에 통합하고 `app/coords.py`를 설계하는 구조를 잡아줘."

