"""
업로드 작업자 (설계서 '업로드→파이프라인 연결 설계', 0.1.3).

업로드 DB(/data/metadata.sqlite3)에서 UPLOADED 문서를 한 건씩 가져와 index_document로 처리하고
COMPLETED / FAILED를 기록한다. 백엔드는 등록만 하고, 처리는 이 작업자만 한다.

- 한 번에 한 건 (Gemini 분당 14회 한도를 작업자 하나가 씀)
- 켜질 때 남아 있는 PROCESSING을 UPLOADED로 되돌림 (처리 도중 재시작 대비, 작업자는 하나뿐)
- 실패는 자동 재시도하지 않음 (화면의 [다시 시도]로만 UPLOADED로)
- DB 함수는 shared/upload_db.py (팀원1 담당)의 것만 쓴다

실행 (figindex 폴더):
    docker compose --profile worker up -d worker
    docker compose logs -f worker
일괄 스크립트(run_index.py, 재추출 등)를 돌리는 동안에는 멈춘다: docker compose stop worker
"""
import os
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from shared.schemas import DocStatus, Document

DB_PATH = os.getenv("UPLOAD_DB_PATH", "/data/metadata.sqlite3")
PDFS_DIR = Path(os.getenv("PDFS_DIR", "/data/pdfs"))
POLL_SECONDS = float(os.getenv("WORKER_POLL_SECONDS", "5"))
MAX_ERROR_CHARS = 300


def run_once(
    claim: Callable[[], Optional[Document]],
    index: Callable[[Path, str], Document],
    complete: Callable[[Document], None],
    fail: Callable[[str, str], None],
    pdfs_dir: Path = PDFS_DIR,
) -> Optional[str]:
    """문서 한 건을 처리한다. 처리할 문서가 없으면 None, 있으면 그 문서의 결과 상태 값을 돌려준다."""
    document = claim()
    if document is None:
        return None
    pdf_path = pdfs_dir / document.doc_name
    started = time.monotonic()
    print(f"[worker] 처리 시작 {document.doc_name} (doc_id={document.doc_id})", flush=True)
    try:
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF 파일 없음: {pdf_path.name}")
        result = index(pdf_path, document.doc_id)
        if result.doc_id != document.doc_id:
            raise RuntimeError(f"doc_id가 바뀜 ({document.doc_id} → {result.doc_id})")
        # 업로드 때 정한 값은 유지하고, 처리에서 알아낸 메타데이터만 얹는다
        merged = document.model_copy(update={
            "doc_title": result.doc_title,
            "doc_type": result.doc_type,
            "domain": result.domain,
            "source_org": result.source_org,
            "authors": result.authors,
            "publish_date": result.publish_date,
            "page_count": result.page_count,
            "doc_status": result.doc_status,
            "doc_error": None,
            "extra_metadata": {**document.extra_metadata, **result.extra_metadata},
        })
        complete(merged)
        count = merged.extra_metadata.get("element_count")
        print(f"[worker] 완료 {document.doc_name}: 도표 {count}개, {time.monotonic() - started:.1f}초", flush=True)
        return merged.doc_status.value
    except Exception as e:  # 어떤 실패든 그 문서만 FAILED로 두고 다음 문서로 넘어간다
        reason = f"{type(e).__name__}: {e}"[:MAX_ERROR_CHARS]
        fail(document.doc_id, reason)
        print(f"[worker] 실패 {document.doc_name}: {reason}", flush=True)
        return DocStatus.FAILED.value


def ensure_collection(client, name: str, template: str = "figindex_elements_v2") -> None:
    """저장할 컬렉션이 없으면 v2와 같은 벡터 설정으로 만든다.

    init_collection.py는 새로 만들 때 /data/crops를 비우므로 여기서는 쓰지 않는다.
    """
    existing = {c.name for c in client.get_collections().collections}
    if name in existing:
        return
    params = client.get_collection(template).config.params
    client.create_collection(collection_name=name, vectors_config=params.vectors,
                             sparse_vectors_config=params.sparse_vectors)
    print(f"[worker] 컬렉션 {name} 새로 만듦 ({template}와 같은 설정)", flush=True)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    from shared import upload_db  # 팀원1: claim_next_document 등 4개 함수
    from orchestrator import ExtractionPipelineOrchestrator

    orchestrator = ExtractionPipelineOrchestrator()
    ensure_collection(orchestrator.qdrant_client, orchestrator.collection_name)
    reset = upload_db.reset_processing_documents(DB_PATH)
    print(f"[worker] 시작: 컬렉션 {orchestrator.collection_name}, 되돌린 PROCESSING {reset}건, "
          f"{POLL_SECONDS:.0f}초마다 확인", flush=True)

    while True:
        outcome = run_once(
            claim=lambda: upload_db.claim_next_document(DB_PATH),
            index=orchestrator.index_document,
            complete=lambda d: upload_db.mark_document_completed(DB_PATH, d),
            fail=lambda doc_id, reason: upload_db.mark_document_failed(DB_PATH, doc_id, reason),
        )
        if outcome is None:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
