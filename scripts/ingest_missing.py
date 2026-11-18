#!/usr/bin/env python3
"""
ingest_missing.py: data/ 아래 PDF 중 Qdrant에 doc_name이 아직 없는 파일만 골라
기존 orchestrator 파이프라인으로 순서대로 색인하는 스크립트.

개선 사항:
1. Gemini API 호출 단위 공용 rate limiter(분당 최대 14회, 최소 간격 약 4.29초) 적용
2. 문서 하나의 모든 도표 처리가 정상 완료된 후에만 Qdrant에 일괄 upsert (중간 실패 시 미저장 및 실패 목록 기록)
3. parse_rpt_filename에서 증권사 자리가 '미확인'이면 source_org를 파일명에서 가져오지 않고 LLM/표지 추출값 사용
4. --only 옵션으로 파일명 패턴(예: RPT_, 논문 등) 필터링 지원
5. --dry-run 예상 시간을 '도표 수 × 호출 수'(분당 14회 기준)로 정확히 재계산

사용법:
    # 1. 대상 목록 및 예상 시간 확인 (--dry-run)
    python scripts/ingest_missing.py --dry-run
    python scripts/ingest_missing.py --dry-run --only RPT_

    # 2. 실제 색인 실행 (Docker 파이프라인 컨테이너 권장)
    #   docker compose -f figindex/docker-compose.yml run --rm pipeline python /scripts/ingest_missing.py --only RPT_
"""

import argparse
import json
import logging
import os
import random
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# sys.path 설정 (호스트 및 Docker 환경 공통)
_CURRENT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _CURRENT_DIR.parent
_FIGINDEX_DIR = _REPO_ROOT / "figindex"
_PIPELINE_DIR = _FIGINDEX_DIR / "pipeline"

for p in (_FIGINDEX_DIR, _PIPELINE_DIR, Path("/app"), Path("/app/shared")):
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

logger = logging.getLogger(__name__)


def get_default_qdrant_url() -> str:
    """실행 환경(Docker 내부 vs 로컬 호스트)에 맞춰 기본 Qdrant URL을 반환합니다."""
    env_url = os.getenv("QDRANT_URL")
    if env_url:
        return env_url
    if Path("/data/pdfs").exists() or Path("/app/orchestrator.py").exists():
        return "http://qdrant:6333"
    return "http://localhost:6333"


def get_default_data_dir() -> Path:
    """PDF 파일들이 존재하는 기본 데이터 디렉토리를 탐색합니다."""
    candidates = [
        Path(os.getenv("PDFS_DIR", "")),
        Path("/data/pdfs"),
        Path("data/pdfs"),
        Path("figindex/data/pdfs"),
        Path("data"),
        Path("figindex/data"),
    ]
    for cand in candidates:
        if str(cand) and cand.is_dir():
            matched = list(cand.glob("*.pdf"))
            if matched:
                return cand
    return Path("figindex/data/pdfs")


def query_all_indexed_doc_names(qdrant_url: str, collection: str) -> Set[str]:
    """Qdrant REST API scroll을 끝까지 페이징하여 색인된 모든 doc_name을 수집합니다."""
    scroll_url = f"{qdrant_url.rstrip('/')}/collections/{collection}/points/scroll"
    indexed_names: Set[str] = set()
    next_offset: Optional[Any] = None

    while True:
        payload: Dict[str, Any] = {
            "limit": 100,
            "with_payload": True,
            "with_vector": False,
        }
        if next_offset is not None:
            payload["offset"] = next_offset

        req = urllib.request.Request(
            scroll_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            print(f"[Error] Qdrant scroll 요청 실패 ({scroll_url}): {e}")
            sys.exit(1)

        result = data.get("result", {})
        points = result.get("points", [])
        for pt in points:
            raw_name = pt.get("payload", {}).get("doc_name")
            if raw_name:
                norm_name = unicodedata.normalize("NFC", raw_name).strip()
                indexed_names.add(norm_name)

        next_offset = result.get("next_page_offset")
        if not next_offset:
            break

    return indexed_names


def find_missing_pdfs(
    data_dir: Path,
    indexed_doc_names: Set[str],
    only_pattern: Optional[str] = None,
) -> Tuple[List[Path], int]:
    """데이터 폴더의 PDF 중 Qdrant에 아직 없는 파일 목록과 전체 PDF 수를 반환합니다."""
    all_pdfs = sorted(list(data_dir.glob("*.pdf")))
    # 샘플 파일 제외
    valid_pdfs = [
        p for p in all_pdfs
        if not unicodedata.normalize("NFC", p.name).startswith("sample_")
    ]

    missing_files: List[Path] = []
    for pdf_p in valid_pdfs:
        norm_name = unicodedata.normalize("NFC", pdf_p.name).strip()
        if norm_name in indexed_doc_names:
            continue

        # --only 패턴 필터링 적용
        if only_pattern:
            norm_pat = unicodedata.normalize("NFC", only_pattern).strip().lower()
            if norm_pat not in norm_name.lower():
                continue

        missing_files.append(pdf_p)

    return missing_files, len(valid_pdfs)


def find_reindex_pdfs(
    matrix_path: Path,
    reason: Optional[str],
    data_dir: Path,
    only_pattern: Optional[str] = None,
) -> Tuple[List[Path], Dict[str, Dict[str, Any]]]:
    """
    compare_matrix.json에서 특정 reason(예: CAP_LIMIT)인 RPT 문서를 추출하여 PDF 경로 목록을 반환합니다.
    """
    if not matrix_path.exists():
        print(f"[Error] 재색인 대상 매트릭스 파일을 찾을 수 없습니다: {matrix_path}")
        return [], {}

    with open(matrix_path, "r", encoding="utf-8") as f:
        matrix = json.load(f)

    target_docs: Dict[str, Dict[str, Any]] = {}
    for item in matrix:
        company = item.get("company", "")
        metric = item.get("metric", "")
        for d in item.get("documents", []):
            if reason and d.get("reason") != reason:
                continue
            dname = d.get("doc_name", "")
            if not dname.startswith("RPT_"):
                continue

            if only_pattern:
                norm_pat = unicodedata.normalize("NFC", only_pattern).strip().lower()
                if norm_pat not in dname.lower():
                    continue

            if dname not in target_docs:
                target_docs[dname] = {
                    "doc_name": dname,
                    "company": company,
                    "source_org": d.get("source_org"),
                    "metrics_missed": [],
                }
            if metric not in target_docs[dname]["metrics_missed"]:
                target_docs[dname]["metrics_missed"].append(metric)

    pdf_files: List[Path] = []
    for dname in sorted(target_docs.keys()):
        candidates = [
            data_dir / dname,
            data_dir / "pdfs" / dname,
        ]
        found_path = None
        for c in candidates:
            if c.exists():
                found_path = c
                break
        if not found_path:
            norm_target = unicodedata.normalize("NFC", dname).strip().lower()
            for p in data_dir.glob("*.pdf"):
                if unicodedata.normalize("NFC", p.name).strip().lower() == norm_target:
                    found_path = p
                    break
        if found_path:
            pdf_files.append(found_path)
        else:
            print(f"  [Warn] PDF 파일을 로컬에서 찾을 수 없습니다: {dname}")

    return pdf_files, target_docs


def get_document_point_ids(
    qdrant_url: str,
    collection_name: str,
    doc_name: str,
) -> List[Any]:
    """Qdrant에서 특정 doc_name을 가진 기존 포인트 ID 목록을 페이징 순회하여 조회합니다."""
    scroll_url = f"{qdrant_url.rstrip('/')}/collections/{collection_name}/points/scroll"
    point_ids: List[Any] = []
    next_offset: Optional[Any] = None

    while True:
        body: Dict[str, Any] = {
            "limit": 100,
            "filter": {
                "must": [
                    {"key": "doc_name", "match": {"value": doc_name}}
                ]
            },
            "with_payload": False,
            "with_vector": False,
        }
        if next_offset is not None:
            body["offset"] = next_offset

        req = urllib.request.Request(
            scroll_url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"  [Warn] 기존 포인트 ID 조회 실패 ({doc_name}): {e}")
            break

        result = data.get("result", {})
        pts = result.get("points", [])
        for pt in pts:
            if "id" in pt:
                point_ids.append(pt["id"])

        next_offset = result.get("next_page_offset")
        if not next_offset:
            break

    return point_ids


def delete_points_from_qdrant(
    qdrant_url: str,
    collection_name: str,
    point_ids: List[Any],
) -> bool:
    """Qdrant 컬렉션에서 지정된 포인트 ID들을 일괄 삭제합니다."""
    if not point_ids:
        return True
    del_url = f"{qdrant_url.rstrip('/')}/collections/{collection_name}/points/delete"
    body = {"points": point_ids}
    req = urllib.request.Request(
        del_url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            return res.get("status") == "ok"
    except Exception as e:
        print(f"  [Error] 기존 포인트 삭제 실패: {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Qdrant에 없는 미색인 PDF만 골라 orchestrator 파이프라인으로 순서대로 색인합니다."
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=None,
        help="PDF 파일이 있는 디렉토리 (기본값: 자동 감지)",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=os.getenv("QDRANT_COLLECTION", "figindex_elements_v2"),
        help="Qdrant 컬렉션 이름 (기본값: figindex_elements_v2)",
    )
    parser.add_argument(
        "--qdrant-url",
        type=str,
        default=get_default_qdrant_url(),
        help="Qdrant 서버 URL (기본값: 환경에 맞춰 자동 감지)",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="파일명 패턴 필터링 (예: RPT_, 논문, IR 등 특정 접두어나 문자열을 포함하는 파일만 처리)",
    )
    parser.add_argument(
        "--reindex-from",
        type=str,
        default=None,
        help="재색인 대상 매트릭스 JSON 경로 (예: data/compare_matrix.json)",
    )
    parser.add_argument(
        "--reason",
        type=str,
        default="CAP_LIMIT",
        help="재색인 대상 선별 사유 (기본값: CAP_LIMIT)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 색인을 수행하지 않고 대상 파일 목록 및 예상 호출 소요시간만 출력하고 종료합니다.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="최대 색인할 문서 수 (0은 전체 처리)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=5,
        help="429 에러 발생 시 최대 재시도 횟수 (기본값: 5)",
    )
    parser.add_argument(
        "--base-backoff",
        type=float,
        default=5.0,
        help="429 백오프 시작 대기 시간 (초, 기본값: 5.0)",
    )
    parser.add_argument(
        "--max-delay",
        type=float,
        default=60.0,
        help="429 백오프 최대 대기 시간 (초, 기본값: 60.0)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=12,
        help="문서당 최대 검사 페이지 수 (기본값: 12)",
    )
    parser.add_argument(
        "--max-elements",
        type=int,
        default=4,
        help="문서당 최대 추출 도표 수 (기본값: 4, 재색인 모드 시 8)",
    )
    args = parser.parse_args()

    target_data_dir = Path(args.data_dir) if args.data_dir else get_default_data_dir()
    if not target_data_dir.exists():
        print(f"[Error] 데이터 디렉토리를 찾을 수 없습니다: {target_data_dir}")
        sys.exit(1)

    is_reindex_mode = bool(args.reindex_from)
    reindex_meta: Dict[str, Dict[str, Any]] = {}

    # 재색인 모드 시 max_elements가 기본값 4이면 8로 자동 상향
    if is_reindex_mode and args.max_elements == 4:
        args.max_elements = 8

    print("=" * 80)
    print(" FigIndex PDF 문서 자동 색인 파이프라인 (ingest_missing)")
    print(f" - 실행 모드: {'재색인 모드 (--reindex-from, 사유: ' + args.reason + ')' if is_reindex_mode else '미색인 신규 색인 모드'}")
    print(f" - 대상 디렉토리: {target_data_dir.resolve()}")
    print(f" - Qdrant 컬렉션: {args.collection} ({args.qdrant_url})")
    print(f" - 문서당 도표 상한: 최대 {args.max_elements}개 (검사 페이지: {args.max_pages}p)")
    print(f" - 파일명 필터(--only): {args.only if args.only else '전체 (ALL)'}")
    print(f" - 속도 제한: Gemini API 호출 단위 공용 Rate Limiter 적용 (분당 최대 14회, 최소 ~4.29s)")
    print("=" * 80)

    if is_reindex_mode:
        # [재색인 모드] compare_matrix.json에서 reason(예: CAP_LIMIT)인 RPT 파일 선별
        reindex_json_path = Path(args.reindex_from)
        if not reindex_json_path.exists():
            print(f"[Error] 재색인 대상 JSON 파일이 없습니다: {reindex_json_path}")
            sys.exit(1)

        print(f"[1/3] 재색인 대상 파일 탐색 중 (사유: {args.reason})...")
        target_pdfs, reindex_meta = find_reindex_pdfs(
            matrix_path=reindex_json_path,
            reason=args.reason,
            data_dir=target_data_dir,
            only_pattern=args.only,
        )
        target_files = target_pdfs if args.limit <= 0 else target_pdfs[:args.limit]
        print(f"  -> 조건 부합 대상 RPT 문서: 총 {len(target_files)}건 선별 완료")

        if not target_files:
            print("\n[안내] 재색인 대상 파일이 없습니다.")
            return

        print("\n" + "-" * 80)
        print(f"          [재색인 대상 RPT 문서 목록 (사유: {args.reason}, 총 {len(target_files)}건)]")
        print("-" * 80)
        for idx, pdf_p in enumerate(target_files, 1):
            meta = reindex_meta.get(pdf_p.name, {})
            comp = meta.get("company", "-")
            sorg = meta.get("source_org", "-")
            missed = ", ".join(meta.get("metrics_missed", []))
            print(f" {idx:2d}. {pdf_p.name} [{comp}/{sorg}] (미매칭 지표: {missed})")
        print("-" * 80)

    else:
        # [신규 미색인 모드]
        print("[1/3] Qdrant 컬렉션의 색인된 문서 목록 조회 중...")
        indexed_doc_names = query_all_indexed_doc_names(args.qdrant_url, args.collection)
        print(f"  -> Qdrant 기색인 고유 문서: {len(indexed_doc_names)}건")

        print("[2/3] 데이터 폴더의 미색인 PDF 파일 탐색 중...")
        missing_files, total_pdfs = find_missing_pdfs(
            data_dir=target_data_dir,
            indexed_doc_names=indexed_doc_names,
            only_pattern=args.only,
        )
        filter_label = f" (필터: '{args.only}')" if args.only else ""
        print(f"  -> 폴더 내 유효 PDF: {total_pdfs}건 중 미색인 대상{filter_label}: {len(missing_files)}건")

        if not missing_files:
            print("\n[안내] 처리할 미색인 PDF 파일이 없습니다.")
            return

        target_files = missing_files if args.limit <= 0 else missing_files[:args.limit]

        print("\n" + "-" * 80)
        print(f"                     [미색인 대상 PDF 목록 (총 {len(target_files)}건)]")
        print("-" * 80)
        for idx, pdf_p in enumerate(target_files, 1):
            print(f" {idx:2d}. {pdf_p.name}")
        print("-" * 80)

    # dry-run 모드인 경우
    if args.dry_run:
        est_elements_per_doc = 7.0 if is_reindex_mode else 3.0
        total_est_api_calls = int(len(target_files) * est_elements_per_doc)
        seconds_per_call = 60.0 / 14.0
        total_est_seconds = total_est_api_calls * seconds_per_call
        total_est_minutes = total_est_seconds / 60.0

        mode_label = f"재색인 모드 (사유: {args.reason})" if is_reindex_mode else "신규 미색인 모드"
        print(f"\n[사전 진단 보고서 (--dry-run)]")
        print(f"  * 실행 모드: {mode_label}")
        print(f"  * 색인 대상 문서: {len(target_files)}건 (RPT 한정)")
        print(f"  * 문서당 도표 상한: 최대 {args.max_elements}개 (기존 4개 ➔ {args.max_elements}개 확대)")
        print(f"  * 예상 도표 수: 약 {total_est_api_calls}개 (문서당 평균 {est_elements_per_doc:.1f}개 기준)")
        print(f"  * 예상 Gemini API 호출 수: 약 {total_est_api_calls}회 (캐시 미적중 시)")
        print(f"  * 속도 제한 기준: 분당 최대 14회 (호출 간 최소 {seconds_per_call:.2f}초 강제 대기)")
        print(f"  * 총 예상 소요 시간: 약 {total_est_minutes:.1f}분 ({total_est_seconds:.0f}초)")
        print(f"\n[실제 색인 실행 안내]")
        reindex_opt = f" --reindex-from {args.reindex_from} --reason {args.reason} --max-elements {args.max_elements}" if is_reindex_mode else ""
        only_arg = f" --only {args.only}" if args.only else ""
        print(f"  Docker 파이프라인 컨테이너에서 아래 명령어로 실행하세요:")
        print(f"    docker compose -f figindex/docker-compose.yml run --rm pipeline python /scripts/ingest_missing.py{reindex_opt}{only_arg}\n")
        return

    # 5. 실제 색인 파이프라인 초기화 (lazy import)
    try:
        from orchestrator import ExtractionPipelineOrchestrator
    except ImportError:
        try:
            from pipeline.orchestrator import ExtractionPipelineOrchestrator
        except ImportError as e:
            print("\n[Error] 파이프라인 의존성(PyMuPDF, Kiwi 등)을 로드할 수 없습니다.")
            print(f"  원인: {e}")
            print("\n[권장 실행 방법] 실제 색인은 Docker 파이프라인 컨테이너에서 실행하세요:")
            only_arg = f" --only {args.only}" if args.only else ""
            print(f"  docker compose -f figindex/docker-compose.yml run --rm pipeline python /scripts/ingest_missing.py{only_arg}\n")
            sys.exit(1)

    print("\n[3/3] 파이프라인 초기화 및 순차 색인 시작...")
    # ExtractionPipelineOrchestrator는 환경변수(QDRANT_COLLECTION, QDRANT_URL)에서 설정을 읽음
    if args.collection:
        os.environ["QDRANT_COLLECTION"] = args.collection
    if args.qdrant_url:
        os.environ["QDRANT_URL"] = args.qdrant_url

    orchestrator = ExtractionPipelineOrchestrator()

    success_cnt = 0
    fail_cnt = 0
    total_elements_indexed = 0
    failed_file_logs: List[Tuple[str, str, float]] = []
    pipeline_start_time = time.time()

    print("\n" + "=" * 80)
    print(f"                순차 색인 진행 로그 (총 {len(target_files)}건)")
    print("=" * 80)

    for idx, pdf_p in enumerate(target_files, 1):
        file_start = time.time()
        print(f"\n[{idx}/{len(target_files)}] 시작: {pdf_p.name}")

        # 재색인 모드: 기존 Qdrant 포인트 ID 조회 (성공 시에만 삭제하기 위해 보관)
        old_point_ids: List[Any] = []
        if is_reindex_mode:
            old_point_ids = get_document_point_ids(args.qdrant_url, args.collection, pdf_p.name)
            print(f"  -> 기존 Qdrant 포인트: {len(old_point_ids)}건 확인 (신규 색인 성공 시 원자적 교체 예정)")

        # 429 지수 백오프 재시도 루프
        attempt = 1
        current_delay = args.base_backoff
        file_success = False
        elements_count = 0
        last_error = ""

        while attempt <= args.max_retries:
            try:
                # orchestrator.process_pdf는 문서 내 모든 도표 처리가 끝난 뒤에만 일괄 Qdrant upsert 수행
                indexed_elements = orchestrator.process_pdf(
                    pdf_path=pdf_p,
                    max_pages=args.max_pages,
                    max_elements_per_pdf=args.max_elements,
                )
                elements_count = len(indexed_elements)
                file_success = True
                break

            except Exception as e:
                err_str = str(e)
                last_error = err_str
                is_rate_limit = (
                    "429" in err_str
                    or "RESOURCE_EXHAUSTED" in err_str
                    or "quota" in err_str.lower()
                    or "rate" in err_str.lower()
                )

                if is_rate_limit and attempt < args.max_retries:
                    jitter = random.uniform(0.5, 2.0)
                    wait_sec = min(args.max_delay, current_delay + jitter)
                    print(f"  ⚠ [429 RateLimit] Gemini 한도 초과 감지. {wait_sec:.1f}초 대기 후 재시도 (시도 {attempt}/{args.max_retries})...")
                    time.sleep(wait_sec)
                    current_delay = min(args.max_delay, current_delay * 2.0)
                    attempt += 1
                else:
                    print(f"  ✖ [에러 발생] {err_str[:120]}")
                    break

        file_elapsed = time.time() - file_start
        if file_success:
            # [원자적 교체] 새 포인트 upsert 완료 후 기존 구 포인트 삭제
            if is_reindex_mode and old_point_ids:
                # 새 포인트 ID와 겹치는 경우 삭제 대상에서 제외 (동일 ID 덮어쓰기 보존)
                new_point_ids: Set[Any] = set()
                for elem in indexed_elements:
                    eid = getattr(elem, "element_id", None)
                    if isinstance(elem, dict):
                        eid = elem.get("element_id")
                    if eid:
                        pt_id = abs(hash(eid)) % (2**63 - 1)
                        new_point_ids.add(pt_id)
                        new_point_ids.add(str(pt_id))
                        new_point_ids.add(eid)

                ids_to_delete = [
                    pid for pid in old_point_ids
                    if pid not in new_point_ids and str(pid) not in new_point_ids
                ]

                if ids_to_delete:
                    del_ok = delete_points_from_qdrant(args.qdrant_url, args.collection, ids_to_delete)
                    if del_ok:
                        overlap_cnt = len(old_point_ids) - len(ids_to_delete)
                        overlap_msg = f" (새 ID와 겹침 제외: {overlap_cnt}건)" if overlap_cnt > 0 else ""
                        print(f"  ✔ [원자적 교체 완료] 구 포인트 {len(ids_to_delete)}건 삭제{overlap_msg} ➔ 신규 포인트 {elements_count}개 유지")
                    else:
                        print(f"  ⚠ [경고] 구 포인트 {len(ids_to_delete)}건 삭제 요청 실패")
                else:
                    print(f"  ✔ [원자적 교체 완료] 기존 구 포인트 {len(old_point_ids)}건이 모두 새 포인트로 덮어쓰기되어 추가 삭제 생략")

            success_cnt += 1
            total_elements_indexed += elements_count
            print(f"  ✔ [성공] '{pdf_p.name}' | 소요시간: {file_elapsed:.1f}초 | 도표 수: {elements_count}개 (Qdrant 일괄 저장 완료)")
        else:
            fail_cnt += 1
            failed_file_logs.append((pdf_p.name, last_error[:100], file_elapsed))
            print(f"  ✖ [실패] '{pdf_p.name}' | 소요시간: {file_elapsed:.1f}초 | Qdrant 기존 포인트 안전 보존 (에러: {last_error[:100]})")

    total_elapsed = time.time() - pipeline_start_time
    print("\n" + "=" * 80)
    print("                        색인 완료 요약 보고")
    print("=" * 80)
    print(f"  - 처리 대상 문서: {len(target_files)}건")
    print(f"  - 성공: {success_cnt}건 | 실패: {fail_cnt}건")
    print(f"  - 총 색인된 도표 수: {total_elements_indexed}개")
    print(f"  - 총 소요 시간: {total_elapsed / 60.0:.1f}분 ({total_elapsed:.1f}초)")

    if failed_file_logs:
        print("\n" + "-" * 80)
        print(f"                     [실패 문서 목록 (총 {len(failed_file_logs)}건)]")
        print("-" * 80)
        for f_idx, (f_name, f_err, f_time) in enumerate(failed_file_logs, 1):
            print(f" {f_idx:2d}. {f_name} ({f_time:.1f}초) -> {f_err}")
        print("-" * 80)

    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
