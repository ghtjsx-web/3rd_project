> 이 문서는 덧붙이지 말고 매번 전체를 다시 쓴다.

# FigIndex 프로젝트 종합 현황서 (AI 분석·인수인계용)

- **작성 시각**: 2026-11-13 16:45 (KST)
- **현재 브랜치**: `refactor/schema-unify` (기준 커밋: `1a90908`)
- **저장소 루트**: `c:\workAi\workProject\3차플젝`
- **검사기 상태**: `check_state.py --full` PASS=11 (전 항목 통과, 0 FAIL)

---

## 0. 한눈에 보기 (10줄 이내)

1. **지금 단계**: v2 컬렉션 이전(465건) 및 데이터 분석 완료, **프롬프트 4a(백엔드·프론트엔드 v2 전환) 진입 직전**입니다.
2. **서비스가 보는 컬렉션**: 백엔드와 프론트엔드는 **여전히 옛 컬렉션 `figindex_elements`(525건)**를 바라보고 있습니다.
3. **새 컬렉션 상태**: `figindex_elements_v2`는 **465건(문서 113개)**으로 생성되어 읽기 전용으로 대기 중입니다.
4. **바로 다음 작업**: **4a 단계** — 백엔드/프론트의 컬렉션 대상을 `figindex_elements_v2`로 전환하고, `caption`/`table_data` 필드 치환 및 `TableData.unit_for()` 기반 단위 표시를 구현합니다.
5. **그 다음 작업**: **4b 단계** — 파이프라인을 새 스키마로 전환하고 `schemas_legacy.py`와 루트 `app/`을 완전히 정리합니다.
6. **합병 목표**: 화요일(11/17) `main` 브랜치 병합을 목표로 리팩토링 안정화를 진행합니다.
7. **절대 하면 안 되는 것 (Warning)**:
   - `python figindex/pipeline/run_index.py` 실행 금지 (4b 전까지 옛 형식으로 쓰기 때문)
   - Qdrant 컬렉션(`figindex_elements`, `figindex_elements_v2`) 임의 쓰기·수정·삭제 금지
   - `schemas.py`, `AGENTS.md`, `docs/glossary.md` 무단 수정 및 기준선 임의 저장(`--save-baseline`) 금지

---

## 1. 프로젝트 개요·실행 환경

- **프로젝트 목적**: PDF 문서(증권 리포트, 공공 보고서, 학술 논문, IR 자료)에서 표(`TABLE`), 차트(`CHART`), 다이어그램(`DIAGRAM`)만 정밀 추출·구조화하여 **"여러 증권사 리포트의 동일 지표·기간을 모아 한눈에 비교·검수하는 지식 도서관"** 구축.
- **기술 스택**:
  - **Frontend**: Next.js 14 (`react-pdf`, Tailwind CSS, TypeScript, 포트 `3000`)
  - **Backend**: FastAPI (`uvicorn`, Python 3.10+, 포트 `8000`)
  - **Vector DB**: Qdrant (`dense` 1536차원 Cosine + `sparse` BM25, 포트 `6333`/`6334`)
  - **Pipeline**: PyMuPDF(`fitz`), `kiwipiepy`, `doclayout-yolo`, Gemini Multimodal API, OpenAI Embeddings (`text-embedding-3-small`)
- **실행 환경 (`figindex/docker-compose.yml`)**:
  - `figindex-qdrant`, `figindex-backend`, `figindex-frontend` 3개 서비스가 로컬 Docker에서 정상 가동 중 (`QDRANT_MODE=server`).
  - `pipeline` 서비스는 `profiles: ["index"]`로 분리되어 독립 컨테이너 실행 지원 (`docker compose run --rm pipeline ...`).
  - 로컬 프로덕션 검증용 `figindex/docker-compose.prod.yml` 별도 구비.

---

## 2. 기준 파일과 규칙

프로젝트의 모든 코드와 에이전트는 아래 6개 단일 기준(Single Source of Truth)을 따르며, 임의 정의는 엄격히 금지됩니다.

1. **`figindex/shared/schemas.py`**: 프로젝트의 유일한 표준 스키마 기준 (`Element`, `ElementSearchPayload`, `TableData`, `ConfidenceSignals`, `Document`, `Batch`, `ReviewLog` 등 11개 표준 모델 및 Enum).
2. **`figindex/shared/coords.py`**: 바운딩 박스 정규화 `[x0, y0, x1, y1]`(좌상단 원점, 0~1) 및 좌표 변환(pt/px, IoU, 패딩)의 유일한 계산 기준.
3. **`docs/glossary.md`**: 표 셀 수치 규칙(7절), 좌표계(8절), 단위 규칙 4원칙(9절), 확신도 가중치(10절), 평가 지표(12절)의 정의 기준.
4. **`AGENTS.md`**: 쓰지 않는 이름 표(2절), schemas.py 필드명 준수, 수정 금지 파일 등 AI 에이전트의 절대 행동 규칙.
5. **`figindex/pipeline/pdf_text.py`**: 증권 리포트 글자 드로잉 순서 꼬임을 해결하기 위해 PDF 텍스트 레이어를 2차원 좌표 순서로 정렬하여 읽는 단일 추출 함수 기준.
6. **`scripts/check_state.py`**: 코드베이스 전체의 금지 이름, 수정 금지 파일 변경, AST 컴파일, 단위 테스트, BBox 유효성을 검증하는 정합성 검사기 기준.

---

## 3. 데이터 현황

| 컬렉션 / 자원 | 건수 | 상태 | 비고 |
| :--- | :---: | :---: | :--- |
| **`figindex_elements` (옛 컬렉션)** | **525건** | 읽기 전용 (보존) | **현재 백엔드/프론트엔드가 조회 중인 실서비스 데이터** (스냅샷 백업 완료) |
| **`figindex_elements_v2` (새 컬렉션)** | **465건** | 읽기 전용 (대기) | **새 스키마 적용 완료** (문서 113개, 승인 386건, 검수 대기 79건, 중복 60건 제외) |
| **크롭 이미지 (`figindex/data/crops/`)** | 578개 | 정상 보존 | 서빙 경로 `/static/crops/{filename}` 지원 |
| **원본 PDF (`figindex/data/pdfs/`)** | 118건 | 정상 보존 | 색인 완료 113건 + 미색인 5건 (원문 404 누락 0건) |
| **엔티티 사전 (`figindex/data/entity_dictionary.csv`)** | 1건+헤더 | 기본 탑재 | SK하이닉스 및 주요 기업 티커 매핑 지원 |

> [!IMPORTANT]
> **핵심 인지 사항**: v2 컬렉션(465건)은 완벽히 생성 및 검증되었으나, **서비스 코드가 아직 전환되지 않아 백엔드/프론트는 여전히 옛 컬렉션(525건)을 보고 있습니다.** 4a 단계에서 이를 v2로 안전하게 스왑합니다.

- **마이그레이션 기록 위치 (`figindex/data/migration/`)**:
  - `doc_id_map.json`: 고유 문서 113개에 대한 `doc_name` ➔ `doc_id` 단일 발급 맵
  - `execute_v2_20261113-0351.md`: v2 컬렉션 실제 이전 실행 결과 및 검증 리포트
  - `dropped_elements_20261113-0350.csv`: 중복 제외된 60건의 메타데이터 보존 파일
  - `doc_name_audit_*.md`: 파일명 이중 색인 조사 리포트
- **데이터 분석 기록 위치 (`figindex/data/analysis/`)**:
  - `comparability_20261113-1633.md`: 교차 증권사 비교 가능성 정량 분석 리포트
  - `targets.csv`: 종목별 리포트/증권사/테이블 집계 (47개 종목)
  - `row_labels.csv`: 표 행 라벨 빈도 및 원문 변형 예시 (1,271개 라벨)
  - `period_labels.csv`: 기간 표기 패턴 유형 및 정규화 제안 (689개 표기)

---

## 4. 완료된 작업 (시간순 압축)

1. **새 파일명 파서 및 다중 문서 유형 지원 (`6711e0d`)**: RPT/PUB/PAP/IR 4대 문서 유형 분류 및 파일명 해석 CLI 지원.
2. **메타데이터 일반화 ("증권사/기업명" ➔ "출처/대상") (`23f8118`)**: `source_org` 및 `extra_metadata.target` 도입 및 프론트 라벨 동적 변경.
3. **로컬 Docker 핫 리로드 환경 정리 (`23f8118`)**: Next.js 및 FastAPI 실시간 reload 구성.
4. **Qdrant 동시성 충돌 해결 및 단일화 (`23f8118`, `2864055`)**: 단일 QdrantClient 인스턴스화 및 동시 40건 API 검증 통과.
5. **DocLayout-YOLO 시험 스크립트 작성 (`3e89a0b`)**: `yolo_trial.py`로 탐지 성능 비교 시험 완료.
6. **스키마 통합 1단계 현황 조사 및 authors 필드 추가 (`fc9becc`)**: 525건 BBox 전수 검사 및 `inventory.md` 작성.
7. **schemas.py 미등재 필드 조사 및 백엔드 즉시 호환 조치 (`2864055`)**: DTO에 표준 필드(`caption`, `table_data` 등) 최우선 수용.
8. **기준 스키마 이전 및 schemas_legacy 분리 (`f5f10c1`)**: `figindex/shared/schemas.py`를 유일한 SSOT로 단일화, 옛 모델은 `schemas_legacy`로 임시 격리.
9. **공통 좌표 모듈 구현 (`d14f974`, `7b0a01b`)**: `figindex/shared/coords.py` 구현 및 단위 테스트 23건 통과.
10. **상태 검사기 check_state.py 및 기준선 체계 구축 (`1be8140`, `89a3e22`)**: A그룹/B그룹 11개 검사기 및 기준선 관리 체계 도입.
11. **doc_name 조사 및 이중 색인 원인 규명 (`688f06f`)**: 옛 이름 29개 이중 색인 및 60건 중복 요소 식별 완료.
12. **v2 컬렉션 마이그레이션 스크립트 구현 (`29c723a`, `7a12e16`)**: `migrate_to_v2.py` 작성 및 dry-run 검증 (465건 이전, 60건 제외).
13. **v2 컬렉션 실제 이전 실행 완료 (`40221f8`, `67ffa9d`)**: `figindex_elements_v2` 생성, 벡터·페이로드 검증 100% 통과 (465건, 113개 문서).
14. **TableData에 행별·열별 단위 필드 및 unit_for() 추가 (`ad9c59f`, `51a39e0`)**: `unit_by_row`, `unit_by_column` 추가 및 검증 로직 구현.
15. **PDF 좌표 순서 정렬 텍스트 추출 함수 구현 (`ed7e285`, `56fd587`)**: `pdf_text.py` 구축으로 드로잉 순서 꼬임(68.6% ➔ 686% .) 해결.
16. **상태 검사기 A1 수정 금지 파일 감시 보강 (`4957d35`, `56fd587`)**: `--allow-protected` 도입 및 경로 정규화 결함 수정.
17. **상태 검사기 A2·A7 보완 (`dd10aef`, `53f35e4`)**: A2 상위 파일별 개수 표기, A7 문법 검사 범위 복원, 일회성 도구 제외.
18. **검사기 기준선 갱신 (`1a90908`)**: 일회성 도구 정리 후 엄격 금지 이름 기준선을 114건으로 갱신.
19. **v2 데이터 비교 가능성 정량 분석 (`analyze_comparability.py`)**: 롯데쇼핑 등 2개 증권사 교차 테이블에서 동일 지표/기간 비교 가능성 실증 완료.

---

## 5. 검사기 현재 기준선

- **총 엄격 금지 이름**: **114건** (`scripts/check_baseline.json` 기준)
  - **4a 대상 (백엔드 1 + 프론트엔드 4 = 70건)**:
    - `figindex/backend/app/main.py`: 19건 (`VisualElementSchema`: 12, `title_or_caption`: 3, `structured_data`: 3, `TableStructure`: 1)
    - `figindex/frontend/app/components/ReviewTab.tsx`: 18건 (`title_or_caption`: 11, `structured_data`: 5, `TableStructure`: 2)
    - `figindex/frontend/app/components/ComparisonModal.tsx`: 14건 (`title_or_caption`: 9, `structured_data`: 3, `TableStructure`: 2)
    - `figindex/frontend/app/elements/[id]/page.tsx`: 13건 (`structured_data`: 8, `title_or_caption`: 3, `TableStructure`: 2)
    - `figindex/frontend/app/page.tsx`: 6건 (`title_or_caption`: 3, `TableStructure`: 2, `structured_data`: 1)
  - **4b 대상 (파이프라인 5개 파일 = 44건)**:
    - `figindex/pipeline/extractor.py`: 20건 (`structured_data`: 8, `title_or_caption`: 5, `VisualElementSchema`: 5, `TableStructure`: 2)
    - `figindex/pipeline/evaluator.py`: 11건 (`structured_data`: 8, `TableStructure`: 3)
    - `figindex/pipeline/orchestrator.py`: 7건 (`VisualElementSchema`: 5, `title_or_caption`: 2)
    - `figindex/pipeline/run_index.py`: 4건 (`structured_data`: 2, `title_or_caption`: 2)
    - `figindex/pipeline/test_metadata_generalization.py`: 2건 (`structured_data`: 1, `title_or_caption`: 1)
- **일반 금지 이름**: 43건
- **단위 테스트**: 파이프라인 58건 + 상태 검사기 11건 = 총 69건 100% 통과

---

## 6. 다음 단계 (로드맵)

### 4a 단계: 백엔드·프론트엔드 v2 전환 (예정)
- 서비스 대상 컬렉션을 `figindex_elements_v2`로 전환 (`check_config.json`, `docker-compose.yml`, 백엔드 설정).
- 백엔드/프론트엔드 코드의 엄격 금지 이름 70건 전면 제거 (`title_or_caption` ➔ `caption`, `structured_data` ➔ `table_data`, `VisualElementSchema` ➔ `ElementSearchPayload`).
- 프론트엔드 표 상세 및 모달에 `TableData.unit_for()` 연동 및 행별·열별 단위 표시 구현.

### 4b 단계: 파이프라인 새 스키마 전환 및 레거시 정리 (예정)
- 파이프라인 5개 파일의 엄격 금지 이름 44건 치환 (`extractor.py`, `evaluator.py`, `orchestrator.py`, `run_index.py`).
- 임시 호환 파일 `figindex/shared/schemas_legacy.py` 및 루트 `app/` 디렉터리 완전 제거.
- `from shared.schemas import ...`로 파이프라인 전면 통일.

### 브랜치 병합 (화요일 11/17)
- `refactor/schema-unify` 브랜치 회귀 검증 완료 후 `main` 브랜치 병합.

### 3주차 과제
1. **DocLayout-YOLO 파이프라인 정식 통합**: `yolo_trial.py` 결과를 본 크로퍼(`cropper.py`)에 이식.
2. **확신도 5개 신호 정규화**: `text_match` 계산 시 `pdf_text.py` 기반 좌표 정렬 텍스트 적용.
3. **ReviewLog 누적 저장**: 검수 이력 불변 테이블/컬렉션 연동.
4. **지표·기간 정규화 사전 엔진**: 분석 리포트에서 제안된 지표 18개군 및 기간 정규화 규칙을 검색·비교 엔진에 적용.

---

## 7. 알려진 문제·주의점

1. **파이프라인 실행 금지**: 4b 단계가 완료되기 전까지 `python figindex/pipeline/run_index.py`를 실행해서는 안 됩니다. 현재 파이프라인은 옛 스키마 형식으로 데이터를 생성하므로 새 v2 컬렉션을 오염시킬 위험이 있습니다.
2. **DocLayout-YOLO 라이선스 (AGPL-3.0)**: DocLayout-YOLO 모델은 AGPL-3.0 라이선스이므로, 향후 상용화 또는 외부 SaaS 배포 시 파이프라인 컨테이너를 별도 네트워크 서비스로 격리하거나 대안 모델(Apache 2.0 등)을 검토해야 합니다.
3. **실데이터 쓰기 잠금**: 현재 Qdrant의 `figindex_elements`(525건)와 `figindex_elements_v2`(465건)는 읽기 전용 상태를 유지해야 하며, 임의 쓰기는 금지됩니다.

---

## 8. 저장소 파일 맵

```text
3차플젝/
├── AGENTS.md                                # AI 코딩 규칙 (필드명, 쓰지 않는 이름, 금지 파일 정의)
├── PROJECT_RULES.md                         # 프로젝트 작업 기본 수칙
├── PROJECT_STATUS_FOR_AI.md                 # 본 현황서 (매번 전체 재작성)
├── README.md                                # 프로젝트 개요
├── docs/
│   ├── glossary.md                          # 용어집 (단위 규칙 4원칙, 표 수치, 좌표계 등)
│   └── FigIndex_통합_기획_설계서.md
├── scripts/
│   ├── check_state.py                       # 형상·스키마·단위테스트 상태 검사기
│   ├── check_config.json                    # 검사기 설정 (스캔 디렉터리, 제외 목록, 보호 파일)
│   ├── check_baseline.json                  # 검사기 기준선 (A2 엄격 114건 기준)
│   ├── test_check_state_a1.py               # A1 수정 금지 감시 단위 테스트 (7건)
│   ├── test_check_state_a2.py               # A2/A7 파일별 카운트/문법 검사 단위 테스트 (4건)
│   ├── concurrency_check.py                 # 백엔드 API 동시성 검증 도구
│   ├── local_to_server.py                   # Qdrant 로컬 -> 서버 이전 도구
│   └── migrate_source_target.py             # 메타데이터 마이그레이션 도구
└── figindex/
    ├── docker-compose.yml                   # 로컬 개발용 Docker Compose (server 모드)
    ├── docker-compose.prod.yml              # 로컬 프로덕션 검증용
    ├── shared/                              # [표준 기준 모듈]
    │   ├── schemas.py                       # 단일 표준 스키마 (SSOT, 11개 모델)
    │   ├── schemas_legacy.py                # 임시 호환 모델 (VisualElementSchema 등, 4b에서 삭제 예정)
    │   └── coords.py                        # 바운딩 박스 정규화 [x0, y0, x1, y1] 및 좌표 변환 모듈
    ├── backend/
    │   └── app/main.py                      # FastAPI 백엔드 (현재 525건 조회 중, 4a 전환 대상)
    ├── frontend/
    │   └── app/                             # Next.js 14 프론트엔드 (4a 전환 대상)
    │       ├── page.tsx                     # 메인 검색·필터 페이지
    │       ├── elements/[id]/page.tsx       # 요소 상세 페이지
    │       └── components/                  # ReviewTab, ComparisonModal 등
    ├── pipeline/                            # [색인 파이프라인 - 4b 전환 대상]
    │   ├── pdf_text.py                      # PDF 좌표 순서 정렬 텍스트 추출 모듈 (신규)
    │   ├── test_pdf_text.py                 # pdf_text 단위 테스트 (4건)
    │   ├── test_schemas_table_units.py      # TableData 단위 필드 단위 테스트 (6건)
    │   ├── analyze_comparability.py         # 비교 가능성 데이터 분석 스크립트 (신규)
    │   ├── migrate_to_v2.py                 # v2 컬렉션 이전 실행 도구
    │   ├── audit_doc_names.py               # 파일명 감사 도구
    │   ├── extractor.py, orchestrator.py, evaluator.py, cropper.py, run_index.py
    │   └── test_coords.py, test_migrate_to_v2.py, test_metadata_generalization.py
    └── data/
        ├── pdfs/                            # 원본 PDF 118건
        ├── crops/                           # 크롭 이미지 578건
        ├── entity_dictionary.csv            # 엔티티 사전
        ├── migration/                       # v2 이전 기록 (doc_id_map.json, execute_v2_*.md 등)
        └── analysis/                        # 비교 가능성 분석 결과 (comparability_*.md, CSV 3종)
```

---

## 9. 다른 AI에게 질문할 때 예시

- **4a 백엔드·프론트엔드 v2 전환 설계 시**:
  > "첨부한 `PROJECT_STATUS_FOR_AI.md`와 `figindex/shared/schemas.py`를 참조하여, 현재 백엔드(`backend/app/main.py`)와 프론트엔드(`frontend/app/`)가 `figindex_elements_v2` 컬렉션을 조회하도록 변경하고, `title_or_caption` ➔ `caption`, `structured_data` ➔ `table_data`로 치환하며, `TableData.unit_for()`를 활용해 단위가 섞인 표에서 셀별 단위를 올바르게 표시하는 4a 단계 수정 계획을 작성해줘."

- **4b 파이프라인 새 스키마 전환 설계 시**:
  > "`PROJECT_STATUS_FOR_AI.md`를 바탕으로, 파이프라인(`extractor.py`, `evaluator.py`, `orchestrator.py`, `run_index.py`) 내 레거시 모델(`VisualElementSchema`, `TableStructure`)과 옛 필드명을 새 스키마(`Element`, `caption`, `table_data`)로 전면 교체하고, `schemas_legacy.py`와 루트 `app/`을 안전하게 제거하는 4b 단계 상세 변경 가이드를 제안해줘."
