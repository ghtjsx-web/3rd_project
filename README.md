# FigIndex (금융·산업 리포트 도표·차트 자동 분류·색인 시스템)

> **프로젝트 상태**: v0.4 MVP 개발 환경 구축 완료  
> **기획·설계 명세서**: [`docs/FigIndex_통합_기획_설계서.md`](docs/FigIndex_통합_기획_설계서.md)  
> **Docker 세부 가이드**: [`figindex/README.md`](figindex/README.md)

---

## 1. 프로젝트 개요

**FigIndex**는 증권사 리서치 및 산업 분석 PDF에서 본문 줄글은 배제하고, 핵심 **'표(`TABLE`), 차트(`CHART`), 밸류체인 다이어그램(`DIAGRAM`)'**만 AI 비전으로 정밀 크롭·구조화하여 직관적으로 비교·검색하는 시각 자료 전용 지식 도서관입니다.

- **토큰 80% 이상 절감**: 문서 전체 입력 대신 도표/차트 BBox 영역만 정밀 크롭 전달
- **표 수치 JSON 구조화**: 복잡한 재무제표 및 실적 전망치를 정형 JSON(`columns`, `rows`, `unit`, `period_labels`)으로 복원
- **다중 신호 가중합 확신도(Confidence)**: 5개 신호 가중합으로 0.80 기준 자동 승인(`APPROVED`) vs 검수 대기(`PENDING_REVIEW`) 라우팅
- **하이브리드 검색**: `text-embedding-3-small` (1536차원) Dense + Kiwi 형태소 한국어 BM25 + Qdrant Payload 필터 결합
- **원문 페이지 즉시 점프**: 검색된 카드에서 클릭 한 번으로 원본 PDF 해당 페이지 Split View로 이동

---

## 2. 🚀 빠른 시작: Docker 한 줄로 실행하기

팀원 누구나 Windows / macOS / Linux 환경에서 Docker Desktop만 켜져 있다면 명령어 한 줄로 프론트엔드, 백엔드, 벡터 DB를 즉시 실행할 수 있습니다.

### Step 1. 저장소 클론 및 이동
```bash
git clone https://github.com/ghtjsx-web/3rd_project.git
cd 3rd_project/figindex
```

### Step 2. 환경변수 파일 복사 및 키 입력
```bash
# Mac / Linux / Git Bash
cp .env.example .env

# Windows PowerShell
copy .env.example .env
```
> `.env` 파일을 열고 발급받은 API 키(`GEMINI_API_KEY`, `OPENAI_API_KEY`)를 입력합니다.

### Step 3. ⭐️ Docker 한 줄 실행 (Frontend + Backend + Qdrant)
```bash
docker compose up -d --build
```
> ※ `pipeline` 컨테이너는 필요 시에만 구동되도록 분리(`profiles: ["index"]`)되어 있어, 평소에는 리소스를 차지하지 않고 웹 서비스 3개만 가볍게 실행됩니다.

---

## 3. 서비스 접속 및 확인

컨테이너가 실행된 후 웹 브라우저에서 아래 주소로 접속합니다:

| 서비스 | 접속 URL | 설명 |
| :--- | :--- | :--- |
| **Frontend Web** | [http://localhost:3000](http://localhost:3000) | Next.js 도표 갤러리 및 검색 대시보드 |
| **Backend API Docs** | [http://localhost:8000/docs](http://localhost:8000/docs) | FastAPI Swagger 대화형 API 문서 |
| **Backend Health** | [http://localhost:8000/health](http://localhost:8000/health) | 백엔드 및 Qdrant 연동 헬스체크 (`qdrant_connected: true`) |
| **Qdrant Dashboard** | [http://localhost:6333/dashboard](http://localhost:6333/dashboard) | Qdrant 벡터 데이터베이스 웹 콘솔 |

---

## 4. Qdrant 컬렉션 초기화 및 색인 실행

### 4.1 컬렉션 초기화 (최초 1회 필수)
Qdrant 벡터 DB에 Dense(1536차원) + Sparse(BM25) 및 6개 Payload 인덱스를 생성합니다:
```bash
docker compose run --rm pipeline python init_collection.py
```
> 성공 시 `[Success] FigIndex collection 'figindex_elements' and payload indices are ready!` 메시지가 출력됩니다.

### 4.2 색인 파이프라인 실행 (테스트 러너)
테스트용 PDF를 `figindex/data/pdfs/`에 넣은 뒤 색인을 실행합니다:
```bash
docker compose run --rm pipeline python run_index.py
```

### 4.3 서비스 종료
```bash
docker compose down
```

---

## 5. 프로젝트 디렉터리 구조

```text
3rd_project/
├── figindex/                       # 🐳 Docker 기반 통합 개발 환경
│   ├── docker-compose.yml          # Qdrant, Backend, Frontend, Pipeline 서비스 정의
│   ├── .env.example                # 환경변수 템플릿 (Gemini/OpenAI 키 등)
│   ├── .gitignore                  # figindex 하위 제외 규칙
│   ├── README.md                   # Docker 상세 인프라 가이드
│   ├── shared/                     # 백엔드 & 파이프라인 공통 모듈
│   │   └── schemas.py              # VisualElementSchema (Pydantic v2 데이터 모델)
│   ├── backend/                    # FastAPI 기반 초경량 REST API 서버 (포트 8000)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app/main.py
│   ├── pipeline/                   # PDF 파싱, YOLO 크롭, AI 구조화 배치 파이프라인
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── init_collection.py
│   │   └── run_index.py
│   ├── frontend/                   # Next.js 14 + Tailwind CSS 웹 대시보드 (포트 3000)
│   └── data/                       # 로컬 데이터 볼륨 (Git 제외, .gitkeep만 추적)
│       ├── pdfs/                   # 원본 PDF 파일
│       ├── crops/                  # 추출된 도표/차트 PNG 이미지
│       ├── qdrant/                 # Qdrant 영구 스토리지 볼륨
│       └── model_cache/            # DocLayout-YOLO 등 모델 가중치 캐시
├── app/                            # (참고용) 로컬 파이썬 모듈
├── docs/                           # 📄 기획 및 아키텍처 문서
│   └── FigIndex_통합_기획_설계서.md  # v0.4 통합 마스터 기획·설계서
├── scripts/                        # 유틸리티 스크립트
├── .env.example                    # 루트 공통 환경변수 템플릿
├── .gitignore                      # Git 보안 제외 설정
└── requirements.txt
```

---

## 6. 🔒 Git 보안 및 협업 규칙

1. **비밀 키 및 대용량 파일 보호**:
   - `.env`, `.env.*` 파일은 민감한 API Key 유출 방지를 위해 **Git 커밋이 원천 차단**되어 있습니다.
   - `node_modules/`, `.venv/`, `.next/`, `qdrant/`, `qdrant_storage/`, 다운로드된 PDF 및 캐시 파일은 `.gitignore`에 등록되어 GitHub에 올라가지 않습니다.
2. **단일 진실 공급원 (Single Source of Truth)**:
   - 모든 도표/차트 데이터 스키마는 **`figindex/shared/schemas.py`**를 기준으로 합니다.
   - 스키마 변경 시에는 팀 회의 및 PR 리뷰를 거쳐 반영합니다.
3. **데이터 볼륨 공유**:
   - 무거운 색인 데이터는 팀 클라우드 드라이브를 통해 공유하며, 각 팀원은 `figindex/data/`에 압축 해제 후 바로 사용할 수 있습니다.
