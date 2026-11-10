
# FigIndex (금융·산업 리포트 도표·차트 자동 분류·색인 시스템)

> **상태**: v0.3 MVP  
> **기획·설계 명세서**: [`docs/FigIndex_통합_기획_설계서.md`](docs/FigIndex_통합_기획_설계서.md)

---

## 1. 프로젝트 개요

**FigIndex**는 한경 컨센서스 등 증권사 리서치 PDF에서 본문 줄글은 배제하고, 핵심 **'표(`TABLE`), 차트(`CHART`), 밸류체인 다이어그램(`DIAGRAM`)'**만 AI 비전으로 정밀 추출·구조화하여 직관적으로 비교·검색하는 시각 자료 전용 지식 도서관입니다.

- **토큰 80% 이상 절감**: 문서 전체 입력 대신 도표/차트 BBox 영역만 정밀 크롭 전달
- **표 수치 JSON 구조화**: 복잡한 재무제표 및 실적 전망치를 정형 JSON(`columns`, `rows`, `unit`, `period_labels`)으로 복원
- **다중 신호 가중합 확신도(Confidence)**: 5개 검증 신호(YOLO 탐지, 스키마, 수치 정합성, Self-consistency, 텍스트 일치율)의 가중합으로 0.80 기준 자동 승인(`APPROVED`) vs 관리자 검수(`PENDING_REVIEW`) 라우팅
- **하이브리드 검색**: `text-embedding-3-small` (1536차원) Dense + Kiwi 형태소 한국어 BM25 + Qdrant Payload 필터 결합
- **원문 페이지 즉시 점프**: 검색된 카드에서 클릭 한 번으로 원본 PDF 해당 페이지 Split View로 이동

---

## 2. 프로젝트 디렉터리 구조

```text
3차플젝/
├── app/
│   ├── api/                # API 엔드포인트 라우터
│   ├── core/
│   │   └── config.py       # Pydantic Settings, 환경변수 및 경로 설정
│   ├── pipeline/
│   │   ├── cropper.py      # PyMuPDF 렌더링, 캡션 병합 및 포인트/비율 패딩 크롭
│   │   ├── evaluator.py    # 5개 신호 가중합 확신도 산출 및 HITL 라우팅
│   │   ├── extractor.py    # Gemini 3.8 Flash 멀티모달 분석 및 JSON 구조화
│   │   └── orchestrator.py # PDF 일괄 파싱 및 엔드투엔드 색인 오케스트레이터
│   ├── services/
│   │   └── search.py       # Kiwi 형태소 BM25 + Qdrant 하이브리드 검색 엔진
│   ├── main.py             # FastAPI 메인 애플리케이션 엔트리포인트
│   └── schemas.py          # VisualElementSchema, TableStructure 데이터 모델
├── data/
│   ├── sample_pdfs/        # 테스트용 증권사 리서치 PDF 저장 디렉터리
│   └── crops/              # 크롭된 도표/차트 PNG 이미지 저장 디렉터리
├── docs/
│   └── FigIndex_통합_기획_설계서.md  # v0.3 통합 마스터 기획·설계서 (단일 진실 공급원)
├── requirements.txt        # 파이썬 의존성 패키지 목록
└── .env                    # API 키 및 환경변수 설정 파일
```

---

## 3. 설치 및 실행 가이드

### 3.1 가상환경 구성 및 패키지 설치

```bash
# 가상환경 생성 및 활성화
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1

# 의존성 패키지 설치
pip install -r requirements.txt
```

### 3.2 환경변수 설정 (`.env`)

```ini
GEMINI_API_KEY="your-gemini-api-key"
VISION_MODEL="gemini-3.8-flash"

OPENAI_API_KEY="your-openai-api-key"
EMBEDDING_MODEL="text-embedding-3-small"
EMBEDDING_DIM=1536

QDRANT_HOST="localhost"
QDRANT_PORT=6333
```

### 3.3 백엔드 서버 실행

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- **Swagger API 대화형 문서**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **헬스 체크**: [http://localhost:8000/health](http://localhost:8000/health)

=======
# 3rd_project
>>>>>>> ea17ef7f063a2e6a297f02e861213be38c84e4c4
