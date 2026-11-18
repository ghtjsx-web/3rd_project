"""
FigIndex 도표 비교 서비스 (Qdrant 연동 및 종목 그룹 비교)
"""
import json
import os
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from shared.schemas import ElementType, TableData
except ImportError:
    from figindex.shared.schemas import ElementType, TableData

from .metrics import MetricType
from .matcher import find_best_table_for_doc, align_matched_tables


def get_compare_pairs_path() -> Path:
    """compare_pairs.json 경로를 탐색합니다."""
    candidates = [
        Path("data/compare_pairs.json"),
        Path("/data/compare_pairs.json"),
        Path(__file__).resolve().parent.parent.parent / "data" / "compare_pairs.json",
        Path(__file__).resolve().parent.parent / "data" / "compare_pairs.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def load_compare_pairs() -> List[Dict[str, Any]]:
    """compare_pairs.json 파일을 로드합니다."""
    path = get_compare_pairs_path()
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Warn] compare_pairs.json 로드 실패 ({path}): {e}")
        return []


def fetch_elements_for_documents(
    doc_names: List[str],
    qdrant_url: Optional[str] = None,
    collection_name: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    지정된 doc_name 목록에 속하는 모든 도표 요소를 Qdrant에서 조회합니다.
    """
    import urllib.request

    url = qdrant_url or os.getenv("QDRANT_URL", "http://localhost:6333")
    coll = collection_name or os.getenv("QDRANT_COLLECTION", "figindex_elements_v2")

    doc_set = set(doc_names)
    results_by_doc: Dict[str, List[Dict[str, Any]]] = {d: [] for d in doc_names}

    scroll_url = f"{url.rstrip('/')}/collections/{coll}/points/scroll"
    offset = None

    while True:
        body: Dict[str, Any] = {
            "limit": 500,
            "with_payload": True,
            "with_vector": False,
        }
        if offset is not None:
            body["offset"] = offset

        req = urllib.request.Request(
            scroll_url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                res = data.get("result", {})
                points = res.get("points", [])
                offset = res.get("next_page_offset")

                for pt in points:
                    pl = pt.get("payload", {})
                    d_name = pl.get("doc_name")
                    if d_name in doc_set:
                        results_by_doc[d_name].append(pl)

                if not offset or not points:
                    break
        except Exception as e:
            print(f"[Error] Qdrant 도표 조회 실패: {e}")
            break

    return results_by_doc


def compare_company_metric(
    company: str,
    metric: MetricType,
    qdrant_url: Optional[str] = None,
    collection_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    특정 기업과 지표에 대해 그룹 내 문서들의 도표를 비교하고 정렬된 행을 반환합니다.
    """
    pairs = load_compare_pairs()
    matched_group = None
    for g in pairs:
        grp_target = g.get("target") or g.get("company")
        if grp_target == company:
            matched_group = g
            break

    if not matched_group:
        # compare_pairs에 없는 경우 Qdrant에서 검색된 문서들로 임시 구성
        # (호환성을 위해)
        docs_info = []
    else:
        docs_info = matched_group.get("documents", [])

    doc_names = [d["doc_name"] for d in docs_info if "doc_name" in d]

    elements_by_doc = fetch_elements_for_documents(
        doc_names=doc_names,
        qdrant_url=qdrant_url,
        collection_name=collection_name,
    )

    doc_results: List[Dict[str, Any]] = []

    for d_info in docs_info:
        d_name = d_info["doc_name"]
        elems = elements_by_doc.get(d_name, [])
        match_res = find_best_table_for_doc(elems, metric)

        doc_results.append({
            "doc_name": d_name,
            "source_org": d_info.get("source_org"),
            "publish_date": d_info.get("publish_date"),
            "matched": match_res["matched"],
            "element_id": match_res["element_id"],
            "page_number": match_res["page_number"],
            "caption": match_res["caption"],
            "match_score": match_res["match_score"],
            "second_candidate_element_id": match_res["second_candidate_element_id"],
            "table_data": match_res["table_data"],
            "match_status": match_res["match_status"],
            "match_rule": match_res.get("match_rule"),
        })

    aligned_rows = align_matched_tables(doc_results, metric=metric)

    return {
        "company": company,
        "metric": metric.value if isinstance(metric, MetricType) else str(metric),
        "documents": doc_results,
        "aligned_rows": aligned_rows,
    }
