# FigIndex: PDF 도표·차트 자동 분류 및 색인 시스템

PDF 문서(리포트, 논문, 보고서 등)에서 줄글은 건너뛰고, 핵심 **표(`TABLE`), 차트(`CHART`), 다이어그램(`DIAGRAM`)**만 AI 비전으로 정밀 추출·구조화하여 검색·비교하는 지식 도서관 시스템의 개발 인프라입니다.

5명의 팀원이 Windows / macOS(Intel & Apple Silicon) 환경에서 **`docker compose up` 한 번으로 완전히 동일한 개발 환경**을 구동할 수 있도록 구성되어 있습니다.

---

## 1. 사전 준비

- **Docker Desktop** 최신 버전 설치 및 실행
- **권장 메모리**: 8GB 이상
  - **Windows (WSL2)**: 사용자 홈 디렉터리(`C:\Users\<사용자명>\.wslconfig`) 파일 생성 또는 수정:
    ```ini
    [wsl2]
    memory=8GB
    processors=4
    ```
  - **macOS**: Docker Desktop > Settings > Resources > Memory를 8GB 이상으로 할당

---

## 2. 최초 세팅 및 실행

1. **저장소 클론 및 이동**:
   ```bash
   git clone <저장소-URL> figindex
   cd figindex
   ```

2. **환경변수 파일 생성**:
   ```bash
   cp .env.example .env
   ```
   `.env` 파일을 열고 발급받은 API 키(`GEMINI_API_KEY`, `OPENAI_API_KEY`)를 입력합니다.

3. **로컬 개발 실행 (Hot Reload 모드)**:
   ```bash
   docker compose up -d -V
   ```
   - 프론트엔드는 `npm run dev` + `WATCHPACK_POLLING=true`, 백엔드는 `uvicorn --reload --reload-dir /app/app --reload-dir /app/shared` + `WATCHFILES_FORCE_POLLING=true`로 실행되어 코드 수정 시 수 초 내 자동 반영됩니다.
   - 예전 빌드/익명 볼륨 캐시가 남아 있을 때 초기화 명령:
     ```bash
     docker compose build --no-cache frontend && docker compose up -d -V
     ```
   *(평소 실행 시: `pipeline` 컨테이너는 프로파일(`profiles: ["index"]`)로 분리되어 있으므로 `qdrant`, `backend`, `frontend` 3개 서비스만 자동으로 뜹니다.)*

4. **로컬 프로덕션 모드 확인 (`docker-compose.prod.yml`)**:
   소스 바인드 마운트 없이 이미지에 빌드된 결과만으로 프로덕션 환경을 검증합니다:
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   # 확인 종료 후
   docker compose -f docker-compose.prod.yml down
   ```

5. **Onpod 배포**:
   - `frontend/Dockerfile`의 `ARG NEXT_PUBLIC_API_URL="https://figindex-api.onpod.ai"` 기본값을 유지하므로 Onpod에서 기존 방식 그대로 빌드·배포하면 됩니다(또는 명시적으로 `--build-arg NEXT_PUBLIC_API_URL=https://figindex-api.onpod.ai` 전달).
   - `backend/Dockerfile`은 단독 이미지 배포 시 `QDRANT_MODE=local`과 `/data` 내장 데이터를 사용합니다.

---

## 3. 서비스 접속 확인

브라우저에서 아래 주소로 접속하여 각 서비스의 정상 구동을 확인합니다:

| 서비스 | 접속 URL | 설명 |
| :--- | :--- | :--- |
| **Frontend Web** | [http://localhost:3000](http://localhost:3000) | Next.js 대시보드 (백엔드 헬스체크 및 목업 도표 카드 2종 렌더링) |
| **Backend API Docs** | [http://localhost:8000/docs](http://localhost:8000/docs) | FastAPI Swagger 대화형 API 문서 |
| **Backend Health** | [http://localhost:8000/health](http://localhost:8000/health) | 백엔드 및 Qdrant 연결 상태 JSON 응답 |
| **Qdrant Dashboard** | [http://localhost:6333/dashboard](http://localhost:6333/dashboard) | Qdrant 벡터 데이터베이스 웹 관리 콘솔 |

---

## 4. Qdrant 컬렉션 초기화

Qdrant 벡터 DB에 Dense(1536차원) + Sparse(BM25) 및 Payload 인덱스를 생성합니다:

```bash
docker compose run --rm pipeline python init_collection.py
```
성공 시 `[Success] FigIndex collection 'figindex_elements' and payload indices are ready!` 메시지가 출력되며, [http://localhost:6333/dashboard](http://localhost:6333/dashboard)에서 컬렉션을 확인할 수 있습니다.

### 4.1 로컬 임베디드(`qdrant_local`) → Qdrant 서버 데이터 이전
로컬 파일 모드(`/data/qdrant_local`)에 저장된 기존 색인 데이터를 Docker Qdrant 서버(`http://qdrant:6333`)로 옮길 때 사용합니다(`docker-compose.yml`에서 `../scripts:/scripts`가 마운트되어 있으며 원본 폴더는 수정하지 않습니다):

```bash
docker compose stop backend
docker compose run --rm pipeline python /scripts/local_to_server.py
docker compose up -d backend
```
*(대상 서버에 이미 컬렉션이 있을 때 덮어쓰려면 `--force` 옵션을 함께 전달하세요.)*

---

## 5. 색인 파이프라인 실행 (Pipeline Runner)

테스트할 PDF 파일들을 `data/pdfs/` 폴더에 넣은 후 다음 명령어를 실행합니다:

```bash
docker compose run --rm pipeline python run_index.py
```
현재 스켈레톤 상태에서는 `data/pdfs/`에 있는 PDF 파일 목록과 페이지 수를 출력하고, 단계별 7단계 파이프라인 TODO 로드맵을 보여줍니다.

---

## 6. 데이터 공유 규칙 (중요)

- **Git 관리 제외**: PDF 원본 문서, 크롭된 이미지(`.png`), Qdrant 벡터 데이터(`.qdrant/`), 다운로드된 AI 모델 가중치(`.cache/`)는 용량 및 저작권 문제로 `.gitignore` 처리되어 **절대 Git에 올리지 않습니다.**
- **데이터 공유 방식**: 대용량 색인 작업은 **색인 담당자 1명이 대표로 실행**합니다.
- 색인이 완료된 후 생성된 `data/` 폴더 압축본(또는 Qdrant 스냅샷 파일)을 **팀 클라우드 드라이브**에 업로드하여 공유합니다.
- 다른 팀원은 공유받은 압축을 본인의 로컬 `figindex/data/`에 풀고 `docker compose up`만 실행하면 즉시 색인된 데이터로 프론트엔드 및 백엔드 개발이 가능합니다.

---

## 7. 팀 협업 규칙

1. **단일 진실 공급원 (Single Source of Truth)**:
   - 모든 도표 데이터 규격은 **`shared/schemas.py`**의 `VisualElementSchema`를 유일한 기준으로 합니다.
   - `backend`와 `pipeline` 모두 이 단일 스키마 파일만 참조합니다.
2. **스키마 변경 절차**:
   - `shared/schemas.py` 필드 추가/변경은 구두 협의로 진행하지 않고, **GitHub PR(Pull Request) 리뷰를 통해서만 머지**합니다.
3. **AI 코딩 도구 활용 시**:
   - Cursor, Claude Code, Antigravity 등의 AI 도구에 프롬프트를 작성할 때는 반드시 **`shared/schemas.py`**와 **`docker-compose.yml`**을 컨텍스트로 함께 전달하세요.

---

## 8. 프론트엔드 로컬 단독 개발 가이드 (선택 사항)

도커 대신 로컬 Node 환경에서 빠른 핫 리로딩(Hot Reload)으로 프론트엔드 UI를 작업하고 싶은 경우:

```bash
cd frontend
npm install
npm run dev
```
백엔드 컨테이너(`docker compose up backend qdrant`)만 띄워둔 상태에서 로컬 `http://localhost:3000`으로 쾌적하게 개발할 수 있습니다.

---

## 9. 자주 발생하는 문제 및 트러블슈팅

### Q1. 포트 충돌 오류 (Port 6333, 8000, 3000 already in use)
- **원인**: 로컬 PC에서 이미 다른 프로세스가 해당 포트를 사용 중임.
- **해결**:
  - Windows: `netstat -ano | findstr :8000` 후 `taskkill /PID <PID> /F`
  - macOS: `lsof -i :8000` 후 `kill -9 <PID>`
  - 또는 `docker-compose.yml`의 호스트 포트 바인딩(예: `"8001:8000"`)을 변경.

### Q2. 메모리 부족으로 pipeline 컨테이너 빌드/실행 실패 (OOMKilled)
- **원인**: PyTorch, OpenCV, DocLayout-YOLO 등 비전 패키지 빌드 시 4GB 미만 메모리 환경에서 충돌 발생.
- **해결**: 사전 준비 가이드에 따라 Docker Desktop의 할당 메모리를 **최소 8GB 이상**으로 증설하세요.

### Q3. Apple Silicon (M1/M2/M3) Mac 빌드 이슈
- **원인**: x86_64 전용 바이너리 의존성 차이.
- **해결**: `pipeline/Dockerfile`의 베이스 이미지는 멀티 아키텍처를 지원하므로 기본 동작하며, 필요 시 `docker-compose.yml`의 서비스에 `platform: linux/amd64`를 명시하세요.

