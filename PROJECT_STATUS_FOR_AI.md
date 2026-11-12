# FigIndex 프로젝트 현재 진행 상태 요약 (AI 분석·인수인계용)

> 작성 시각: 2026-11-12  
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

현재 저장소에는 **두 개의 코드/스키마 축**이 공존하고 있습니다.

### A. 실제 동작 중인 Docker 서비스 축 (`figindex/`)
- **실행 위치**: `figindex/backend/`, `figindex/pipeline/`, `figindex/frontend/`, `figindex/shared/`
- **사용 스키마**: `figindex/shared/schemas.py` (`VisualElementSchema`, `TableStructure`, `ElementType`, `ReviewStatus`)
- **주요 필드/규격**:
  - 제목: `title_or_caption`
  - 표 데이터: `structured_data` (`TableStructure`)
  - 좌표: `bbox` (문서상 `[ymin, xmin, ymax, xmax]`)

### B. 최신 코딩 규칙·표준 스키마 축 (`AGENTS.md`, `app/schemas.py`, `docs/glossary.md`)
- 커밋 `2864055`에서 프로젝트 표준 규칙으로 확정된 기준입니다.
- **사용 스키마**: `app/schemas.py`
  - 상수: `CONFIDENCE_THRESHOLD = 0.80`, `PIPELINE_VERSION = "0.1.0"`, `ENTITY_DICTIONARY_PATH = "data/entity_dictionary.csv"`, `SIGNAL_WEIGHTS`, `LAYOUT_TO_ELEMENT`, `MERGE_CLASSES`
  - Enum: `ElementType`, `DocStatus`, `ReviewStatus`, `ReviewAction`, `LayoutClass`, `EntityType`
  - 모델: `Batch`, `Collection`, `Document`, `Page`, `Detection`, `TableData`, `ConfidenceSignals`, `Element`, `ElementSearchPayload`, `ReviewLog`, `EntityEntry`
- **주요 필드/규격 차이**:
  - `VisualElementSchema` → `Element` / `ElementSearchPayload`
  - `title_or_caption` → 문서 `doc_title`, 요소 `caption`
  - `structured_data` → `table_data` (`TableData`)
  - `bbox` → `[x0, y0, x1, y1]` (0~1 정규화, 좌상단 원점), 좌표 변환은 `app/coords.py` 사용 규칙(현재 `app/coords.py` 파일은 아직 없음)
  - `AGENTS.md` 규칙상 향후 모든 코드 작성·수정은 `AGENTS.md`, `app/schemas.py`, `docs/glossary.md`를 따라야 하며, 세 파일은 사용자 명시 요청 없이 수정 금지
- 참고: 루트의 `app/` 폴더(`app/main.py` v0.3 등)는 초기 스켈레톤 상태이며, 현재 Docker에서 실제 실행되는 앱은 `figindex/`입니다.

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

---

## 3.5 확인된 문제점 및 기술적 판단 (프롬프트 2~6 진행 전 점검 결과)

1. **`inventory.md`와 최신 `app/schemas.py` 간 `authors` 차이**
   - `inventory.md` 작성 직후 `app/schemas.py`의 `ElementSearchPayload`에 `authors`가 추가되었으므로, 5단계(`migrate_to_v2.py`)에서는 `authors`를 `extra_metadata["legacy"]`가 아닌 `ElementSearchPayload.authors`로 직접 이관해야 합니다.
2. **`bbox` 형식은 일관되나 기존 크롭/분류 품질 오탐 사례 존재**
   - `bbox` 좌표 규격 자체는 525건 전체가 100% 일관되어 스키마 통합에는 문제가 없습니다 (`[bbox[1], bbox[0], bbox[3], bbox[2]]`로 즉시 변환 가능).
   - 다만 `bbox_check/` 시각화에서 문서 목차가 `TABLE`로(`01_TABLE_fig-b5f2_p6.png`), 회화 사진이 `CHART`로(`05_CHART_fig-e24f_p2.png`) 오분류된 사례가 확인되었습니다. 이는 스키마 통합 이후 DocLayout-YOLO 통합 단계에서 개선해야 할 과제입니다.
3. **`ENTITY_DICTIONARY_PATH`와 컨테이너 `/data/` 경로 불일치**
   - `app/schemas.py` 기본값은 `"data/entity_dictionary.csv"`이나 `backend`/`pipeline` 컨테이너의 `WORKDIR`은 `/app`이고 데이터는 `/data/entity_dictionary.csv`에 마운트됩니다. 환경변수 `ENTITY_DICTIONARY_PATH`로 덮어쓸 수 있게 처리해야 합니다.
4. **`pipeline/Dockerfile`의 `shared/` 복사 누락 (잠재 이슈)**
   - 로컬 `docker-compose.yml`은 `./shared:/app/shared` 볼륨 마운트로 정상 동작하지만, `figindex/pipeline/Dockerfile`에는 `COPY *.py ./`만 있어 Compose 없이 단독 이미지 빌드 시 `shared/`가 누락됩니다.
5. **기존 525건 마이그레이션 시 불완전 레코드 주의**
   - `structured_data` 누락 1건(`524/525`), `extra_metadata.target` 누락 118건(`407/525`)이 확인되었습니다. `migrate_to_v2.py` 실행 시 `--dry-run`으로 `TableData` 검증 실패 건수를 먼저 확인해야 합니다.
6. **루트 `app/` 폴백 import 잔존**
   - `figindex/pipeline/`의 `evaluator.py`, `extractor.py`, `orchestrator.py`에 `except ImportError:` 폴백으로 `from app.schemas import ...`가 남아 있어, 루트 `app/`을 `archive/app_v0_3/`로 이동할 때 `from shared.schemas import ...`로 단일화해야 합니다.
- **종합 판단**: 위 6건 모두 원인과 대응 방법이 명확하므로, 현재 상태에서 스키마 통합 **프롬프트 2(기준 파일 위치 옮기기)**로 안전하게 진행 가능합니다.

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
├── app/                                # [신규 표준 스키마 및 초기 로컬 코드]
│   ├── schemas.py                      # 표준 Single Source of Truth (Element, TableData, ReviewLog 등)
│   ├── main.py                         # v0.3 초기 API 스켈레톤
│   ├── core/, pipeline/, services/
├── docs/
│   ├── glossary.md                     # 용어집 (표 수치, 확신도, 좌표, 평가 지표 정의)
│   └── FigIndex_통합_기획_설계서.md
├── scripts/
│   ├── local_to_server.py              # qdrant_local -> Qdrant 서버 이전
│   ├── concurrency_check.py            # 동시 40건 API 안정성 검증
│   ├── migrate_source_target.py        # 출처/대상 payload 마이그레이션
│   └── generate_sample_pdf.py
└── figindex/                           # [현재 Docker로 실제 구동 중인 앱]
    ├── docker-compose.yml              # 로컬 개발용 (QDRANT_MODE=server, Hot Reload)
    ├── docker-compose.prod.yml         # 로컬 프로덕션 검증용
    ├── shared/schemas.py               # 현재 figindex 앱이 참조하는 기존 스키마
    ├── backend/app/main.py             # FastAPI 서버 (포트 8000)
    ├── pipeline/                       # 색인 파이프라인 (run_index.py, orchestrator.py 등)
    ├── frontend/app/                   # Next.js 14 UI (포트 3000)
    └── data/                           # pdfs(118), crops(578), qdrant(525), qdrant_local(118)
```

---

## 6. 다음 단계 / 검토가 필요한 과제

1. **표준 스키마(`AGENTS.md` / `app/schemas.py`)와 실행 코드(`figindex/`) 통합 여부 결정**
   - 현재 동작 중인 `figindex/`는 `figindex/shared/schemas.py`(`VisualElementSchema`, `title_or_caption`, `structured_data`, `[ymin, xmin, ymax, xmax]`)를 사용 중이고, `AGENTS.md`는 `app/schemas.py`(`Element`, `caption`, `table_data`, `[x0, y0, x1, y1]`) 사용을 요구함
   - `figindex/`를 `app/schemas.py` 기준으로 마이그레이션할지, 혹은 브리지/어댑터를 둘지 결정 필요
2. **좌표 모듈(`app/coords.py`) 구현**
   - `AGENTS.md`와 `docs/glossary.md`에 명시된 PyMuPDF(`pt`)·YOLO(`px`)·화면(`px`) 간 `[x0, y0, x1, y1]` 변환 모듈 신규 작성 필요
3. **탐지/추출 고도화**
   - `yolo_trial.py`로 시험한 DocLayout-YOLO 탐지 로직을 본 크로퍼(`cropper.py`)에 통합할지 검토
   - `ConfidenceSignals` 5개 신호 및 `SIGNAL_WEIGHTS` 재정규화 로직 정렬
   - `entity_dictionary.csv` 데이터 확충 및 고유명사 치환 적용
4. **등록 작업·검수 이력·평가 고도화**
   - `Batch`, `Document`, `ReviewLog`(추가 전용 이력) 및 `docs/glossary.md` 12절 지표(`crop_recall`, `table_valid_rate`, `cell_accuracy`, `precision_at_5` 등) 기반 정량 평가 연결

---

## 7. 다른 AI에게 분석 요청할 때 참고 질문 예시

- "첨부한 `PROJECT_STATUS_FOR_AI.md`를 바탕으로, `app/schemas.py` + `AGENTS.md` 기준과 현재 실행 중인 `figindex/` 코드 간의 간극을 메우기 위한 단계별 마이그레이션 계획을 세워줘."
- "기존 Qdrant 데이터(525건)를 깨뜨리지 않으면서 `VisualElementSchema`에서 `ElementSearchPayload`로 안전하게 전환하는 전략을 제안해줘."
- "`yolo_trial.py` 결과를 본 파이프라인 `cropper.py`에 통합하고 `app/coords.py`를 설계하는 구조를 잡아줘."

