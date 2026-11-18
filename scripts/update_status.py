#!/usr/bin/env python3
"""
FigIndex 현황서 자동 갱신 스크립트 (scripts/update_status.py)

PROJECT_STATUS_FOR_AI.md의 <!-- AUTO:START --> ~ <!-- AUTO:END --> 구간을
실제 시스템 환경에서 직접 조회한 최신 프로젝트 메트릭으로 자동 덮어씁니다.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Windows 콘솔 인코딩 대응
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
STATUS_FILE = REPO_ROOT / "PROJECT_STATUS_FOR_AI.md"

try:
    from shared.schemas import ReviewStatus
except ImportError:
    try:
        from figindex.shared.schemas import ReviewStatus
    except ImportError:
        sys.path.insert(0, str(REPO_ROOT))
        sys.path.insert(0, str(REPO_ROOT / "figindex"))
        from shared.schemas import ReviewStatus


def get_current_timestamp() -> str:
    """현재 시각 문자열을 반환합니다 (KST)."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S KST")


def get_git_info() -> Dict[str, Any]:
    """Git 저장소 메타데이터를 조회합니다."""
    ts = get_current_timestamp()
    res = {
        "branch": "알 수 없음",
        "commit": "알 수 없음",
        "uncommitted_count": 0,
        "timestamp": ts,
    }
    try:
        # 1. 브랜치명
        p = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        res["branch"] = p.stdout.strip()

        # 2. 최신 커밋 해시 및 메시지
        p2 = subprocess.run(
            ["git", "log", "-1", "--format=%h - %s"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        res["commit"] = p2.stdout.strip()

        # 3. 커밋 안 된 변경 파일 수
        p3 = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        lines = [line for line in p3.stdout.splitlines() if line.strip()]
        res["uncommitted_count"] = len(lines)
    except Exception as e:
        print(f"[Warn] Git 정보 조회 실패: {e}")
    return res


def get_qdrant_info(
    url: str = "http://localhost:6333",
    collection_name: str = "figindex_elements_v2",
) -> Tuple[Dict[str, Any], Set[str]]:
    """Qdrant 컬렉션 상태(포인트 수, 고유 문서 수, 승인/검수대기 수) 및 인덱싱된 문서 목록을 조회합니다."""
    ts = get_current_timestamp()
    info = {
        "points_count": "조회 실패",
        "doc_count": "조회 실패",
        "approved_count": "조회 실패",
        "pending_count": "조회 실패",
        "rejected_count": "조회 실패",
        "timestamp": ts,
        "success": False,
    }
    doc_names: Set[str] = set()

    try:
        # 1. 포인트 카운트
        count_url = f"{url}/collections/{collection_name}/points/count"
        req = urllib.request.Request(
            count_url,
            data=json.dumps({"exact": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            info["points_count"] = data.get("result", {}).get("count", 0)

        # 2. Scroll 순회로 고유 문서 수 및 승인 상태 집계
        scroll_url = f"{url}/collections/{collection_name}/points/scroll"
        offset = None
        approved = 0
        pending = 0
        rejected = 0

        while True:
            body: Dict[str, Any] = {
                "limit": 100,
                "with_payload": ["doc_name", "review_status"],
            }
            if offset:
                body["offset"] = offset

            req_scroll = urllib.request.Request(
                scroll_url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req_scroll, timeout=10.0) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                result_data = res_json.get("result", {})

            pts = result_data.get("points", [])
            if not pts:
                break

            for p in pts:
                pl = p.get("payload") or {}
                dname = pl.get("doc_name")
                if dname:
                    doc_names.add(dname)
                st = pl.get("review_status")
                if st == ReviewStatus.APPROVED.value or st == ReviewStatus.APPROVED:
                    approved += 1
                elif st == ReviewStatus.REJECTED.value or st == ReviewStatus.REJECTED:
                    rejected += 1  # 반려는 검수대기와 따로 센다
                else:
                    pending += 1

            offset = result_data.get("next_page_offset")
            if not offset:
                break

        info["doc_count"] = len(doc_names)
        info["approved_count"] = approved
        info["pending_count"] = pending
        info["rejected_count"] = rejected
        info["success"] = True
    except Exception as e:
        print(f"[Warn] Qdrant 정보 조회 실패: {e}")

    return info, doc_names


def get_pdf_info(indexed_docs: Set[str], qdrant_success: bool) -> Dict[str, Any]:
    """PDF 저장소 파일 수 및 미색인 PDF 목록을 조회합니다."""
    ts = get_current_timestamp()
    candidates = [
        REPO_ROOT / "figindex" / "data" / "pdfs",
        REPO_ROOT / "data" / "pdfs",
    ]
    pdf_dir = None
    for c in candidates:
        if c.exists() and c.is_dir():
            pdf_dir = c
            break

    if not pdf_dir:
        return {
            "total_pdfs": 0,
            "unindexed_pdfs": [],
            "timestamp": ts,
        }

    all_pdfs = sorted([f.name for f in pdf_dir.glob("*.pdf") if not f.name.startswith(".")])
    if not qdrant_success:
        unindexed = ["Qdrant 연결 실패로 미색인 목록 확인 불가"]
    else:
        unindexed = [p for p in all_pdfs if p not in indexed_docs]

    return {
        "total_pdfs": len(all_pdfs),
        "unindexed_pdfs": unindexed,
        "timestamp": ts,
    }


def get_compare_pairs_info() -> Dict[str, Any]:
    """compare_pairs.json 정보를 조회합니다."""
    ts = get_current_timestamp()
    candidates = [
        REPO_ROOT / "data" / "compare_pairs.json",
        REPO_ROOT / "figindex" / "data" / "compare_pairs.json",
    ]
    path = None
    for c in candidates:
        if c.exists():
            path = c
            break

    if not path:
        return {"group_count": 0, "timestamp": ts}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {"group_count": len(data), "timestamp": ts}
    except Exception as e:
        print(f"[Warn] compare_pairs.json 로드 실패: {e}")
        return {"group_count": 0, "timestamp": ts}


def get_compare_matrix_info() -> Dict[str, Any]:
    """compare_matrix.json 정보를 조회하여 지표별 MATCHED 수와 not_found 원인별 수를 집계합니다."""
    ts = get_current_timestamp()
    candidates = [
        REPO_ROOT / "data" / "compare_matrix.json",
        REPO_ROOT / "figindex" / "data" / "compare_matrix.json",
    ]
    path = None
    for c in candidates:
        if c.exists():
            path = c
            break

    res: Dict[str, Any] = {
        "matched_by_metric": {},
        "not_found_by_reason": {},
        "total_checks": 0,
        "total_matched": 0,
        "total_not_found": 0,
        "timestamp": ts,
    }
    if not path:
        return res

    try:
        with open(path, "r", encoding="utf-8") as f:
            matrix = json.load(f)

        for g in matrix:
            m = g.get("metric", "UNKNOWN")
            res["matched_by_metric"].setdefault(m, 0)
            for d in g.get("documents", []):
                res["total_checks"] += 1
                if d.get("matched"):
                    res["matched_by_metric"][m] += 1
                    res["total_matched"] += 1
                else:
                    reason = d.get("reason") or "UNKNOWN"
                    res["not_found_by_reason"][reason] = (
                        res["not_found_by_reason"].get(reason, 0) + 1
                    )
                    res["total_not_found"] += 1
    except Exception as e:
        print(f"[Warn] compare_matrix.json 로드 실패: {e}")

    return res


def get_check_state_summary() -> Dict[str, Any]:
    """check_state.py --quick 실행 요약 및 WARN/SKIP 항목을 파싱합니다."""
    ts = get_current_timestamp()
    res = {
        "summary_line": "조회 실패",
        "warn_items": [],
        "skip_items": [],
        "fail_items": [],
        "timestamp": ts,
    }
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "check_state.py"),
        "--quick",
        "--allow-protected",
        "scripts/check_state.py",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = proc.stdout

        # 요약 라인 파싱: "검사 요약: PASS=6  WARN=1  CHANGED=0  FAIL=0  SKIP=1"
        sum_match = re.search(r"검사 요약:\s*(PASS=\d+.*)", output)
        if sum_match:
            res["summary_line"] = sum_match.group(1).strip()

        # 각 검사 항목 라인 파싱
        for line in output.splitlines():
            line_str = line.strip()
            if line_str.startswith("[WARN]"):
                item_name = line_str[6:].split(":", 1)[0].strip()
                res["warn_items"].append(item_name)
            elif line_str.startswith("[SKIP]"):
                item_name = line_str[6:].split(":", 1)[0].strip()
                res["skip_items"].append(item_name)
            elif line_str.startswith("[FAIL]"):
                item_name = line_str[6:].split(":", 1)[0].strip()
                res["fail_items"].append(item_name)
    except Exception as e:
        print(f"[Warn] check_state.py 실행 실패: {e}")

    return res


def generate_auto_markdown() -> str:
    """모든 시스템 항목을 조회하여 AUTO 구간에 삽입할 마크다운 문자열을 생성합니다."""
    git_info = get_git_info()
    qdrant_info, indexed_docs = get_qdrant_info()
    pdf_info = get_pdf_info(indexed_docs, qdrant_info["success"])
    pairs_info = get_compare_pairs_info()
    matrix_info = get_compare_matrix_info()
    check_info = get_check_state_summary()

    # 미색인 목록 표시 포맷 (최대 5개 표시)
    unindexed = pdf_info["unindexed_pdfs"]
    if not unindexed:
        unindexed_str = "없음 (모든 PDF 색인 완료)"
    elif len(unindexed) <= 5:
        unindexed_str = f"{len(unindexed)}건: " + ", ".join(unindexed)
    else:
        unindexed_str = (
            f"{len(unindexed)}건: "
            + ", ".join(unindexed[:5])
            + f" 외 {len(unindexed) - 5}건"
        )

    # 지표별 MATCHED 포맷
    matched_m = matrix_info["matched_by_metric"]
    m_parts = [f"{k}: {v}건" for k, v in matched_m.items()]
    matched_str = (
        f"총 {matrix_info['total_matched']}건 (" + ", ".join(m_parts) + ")"
        if m_parts
        else "0건"
    )

    # not_found 원인별 포맷
    reasons = matrix_info["not_found_by_reason"]
    r_parts = [f"{k}: {v}건" for k, v in sorted(reasons.items())]
    reasons_str = (
        f"총 {matrix_info['total_not_found']}건 (" + ", ".join(r_parts) + ")"
        if r_parts
        else "0건"
    )

    # check_state 항목 포맷
    warn_str = ", ".join(check_info["warn_items"]) if check_info["warn_items"] else "없음"
    skip_str = ", ".join(check_info["skip_items"]) if check_info["skip_items"] else "없음"
    fail_str = ", ".join(check_info["fail_items"]) if check_info["fail_items"] else "없음"

    lines = [
        "<!-- AUTO:START -->",
        f"| 항목 | 측정값 | 측정 시각 |",
        f"| :--- | :--- | :--- |",
        f"| **Git 브랜치** | `{git_info['branch']}` | {git_info['timestamp']} |",
        f"| **Git 최신 커밋** | `{git_info['commit']}` | {git_info['timestamp']} |",
        f"| **Git 미커밋 변경 파일** | `{git_info['uncommitted_count']}개 파일` | {git_info['timestamp']} |",
        f"| **Qdrant 컬렉션 (`v2`) 포인트** | `{qdrant_info['points_count']}` (승인: `{qdrant_info['approved_count']}`, 검수대기: `{qdrant_info['pending_count']}`, 반려: `{qdrant_info['rejected_count']}`) | {qdrant_info['timestamp']} |",
        f"| **Qdrant 색인 고유 문서** | `{qdrant_info['doc_count']}개 문서` | {qdrant_info['timestamp']} |",
        f"| **원문 PDF 총계** | `{pdf_info['total_pdfs']}개 PDF` | {pdf_info['timestamp']} |",
        f"| **미색인 원문 PDF 목록** | {unindexed_str} | {pdf_info['timestamp']} |",
        f"| **동일 종목 비교 그룹** | `{pairs_info['group_count']}개 그룹` (`compare_pairs.json`) | {pairs_info['timestamp']} |",
        f"| **도표 비교 매칭 성공** | {matched_str} | {matrix_info['timestamp']} |",
        f"| **도표 비교 미매칭 원인** | {reasons_str} | {matrix_info['timestamp']} |",
        f"| **상태 검사기 (`check_state`)** | `{check_info['summary_line']}` | {check_info['timestamp']} |",
        f"| └ **검사 경고(WARN) 항목** | {warn_str} | {check_info['timestamp']} |",
        f"| └ **검사 생략(SKIP) 항목** | {skip_str} | {check_info['timestamp']} |",
        f"| └ **검사 실패(FAIL) 항목** | {fail_str} | {check_info['timestamp']} |",
        "<!-- AUTO:END -->",
    ]
    return "\n".join(lines)


def update_status_file() -> bool:
    """PROJECT_STATUS_FOR_AI.md 파일을 읽어 AUTO 구간을 갱신합니다."""
    if not STATUS_FILE.exists():
        print(f"[Error] 현황서 파일이 존재하지 않습니다: {STATUS_FILE}")
        return False

    with open(STATUS_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    auto_block = generate_auto_markdown()
    pattern = re.compile(r"<!-- AUTO:START -->.*?<!-- AUTO:END -->", re.DOTALL)

    if pattern.search(content):
        new_content = pattern.sub(auto_block, content)
    else:
        # 기존에 태그가 없는 경우 1절 뒤에 삽입하거나 적절히 대체
        print("[Info] <!-- AUTO:START --> 태그가 없어 현황서 상단에 추가합니다.")
        new_content = auto_block + "\n\n" + content

    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"✔ 현황서 자동 갱신 완료: {STATUS_FILE}")
    return True


if __name__ == "__main__":
    success = update_status_file()
    sys.exit(0 if success else 1)
