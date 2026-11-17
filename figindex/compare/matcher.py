"""
FigIndex 도표 비교 매칭 및 행 라벨 정렬 엔진
"""
import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from shared.schemas import ElementType, TableData
except ImportError:
    from figindex.shared.schemas import ElementType, TableData

from .metrics import MetricType, METRIC_KEYWORDS, EXCLUDE_KEYWORDS, FINANCIAL_INDICATORS


def normalize_row_label(label: Any) -> str:
    """
    행 라벨을 정규화합니다:
    1. 앞뒤 공백 및 내부 공백 제거
    2. (P)/(E)/(F) 표기 통일 ([E], E -> (E) 등)
    """
    if label is None:
        return ""
    s = str(label).strip()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"\[([PEFpef])\]", lambda m: f"({m.group(1).upper()})", s)
    s = re.sub(r"(?<=[0-9A-Za-z가-힣])([PEFpef])(?=$|[^0-9A-Za-z가-힣])", lambda m: f"({m.group(1).upper()})", s)
    return s


def get_canonical_row_key(norm_label: str) -> str:
    """
    서로 다른 표에서 같은 의미의 행 라벨을 매핑하기 위한 정규화 키를 반환합니다.
    (예: '영업이익률(%)' -> '영업이익률')
    """
    return re.sub(r"\(%\)|\[%\]", "", norm_label)


def score_element_for_metric(
    element: Dict[str, Any],
    metric: MetricType,
) -> Tuple[float, int, List[str]]:
    """
    단일 도표 요소에 대해 지표 캡션 키워드 점수 및 행 라벨 재무항목 겹침 수를 계산합니다.
    반환: (keyword_score, row_overlap_count, matched_keywords)
    """
    # TABLE 유형이 아니면 매칭 대상 제외
    element_type = element.get("element_type")
    if element_type != ElementType.TABLE.value and element_type != ElementType.TABLE:
        return 0.0, 0, []

    caption = element.get("caption") or ""
    caption_lower = caption.lower()

    # 매칭 제외 키워드 검사
    for ex in EXCLUDE_KEYWORDS:
        if ex.lower() in caption_lower:
            return 0.0, 0, []

    keywords = METRIC_KEYWORDS.get(metric, [])
    matched_keywords: List[str] = []
    for kw in keywords:
        if kw.lower() in caption_lower:
            matched_keywords.append(kw)

    keyword_score = float(len(matched_keywords))
    if keyword_score == 0.0:
        return 0.0, 0, []

    # 동점 시 행 라벨 겹침 수 계산
    table_data = element.get("table_data")
    row_overlap_count = 0
    if table_data and isinstance(table_data, dict):
        rows = table_data.get("rows") or []
        for r in rows:
            if isinstance(r, dict) and r:
                first_val = str(list(r.values())[0]).lower()
                if any(ind.lower() in first_val for ind in FINANCIAL_INDICATORS):
                    row_overlap_count += 1
    elif hasattr(table_data, "rows") and table_data.rows:
        for r in table_data.rows:
            if isinstance(r, dict) and r:
                first_val = str(list(r.values())[0]).lower()
                if any(ind.lower() in first_val for ind in FINANCIAL_INDICATORS):
                    row_overlap_count += 1

    return keyword_score, row_overlap_count, matched_keywords


def find_best_table_for_doc(
    elements: List[Dict[str, Any]],
    metric: MetricType,
) -> Dict[str, Any]:
    """
    문서의 요소 목록에서 지정된 지표에 가장 적합한 TABLE을 찾습니다.
    규칙:
    1. 캡션 키워드 점수가 가장 높은 표 1개 선택
    2. 동점이면 행 라벨 겹침 수가 많은 표 선택
    3. 키워드가 하나도 맞지 않으면 not_found 반환
    4. 후보가 여러 개면 2순위 후보 id도 함께 반환
    """
    scored_candidates = []
    for el in elements:
        k_score, r_overlap, m_kws = score_element_for_metric(el, metric)
        if k_score > 0.0:
            scored_candidates.append({
                "keyword_score": k_score,
                "row_overlap": r_overlap,
                "element": el,
                "matched_keywords": m_kws,
                "page_number": el.get("page_number", 999),
            })

    if not scored_candidates:
        return {
            "matched": False,
            "element_id": None,
            "page_number": None,
            "caption": None,
            "match_score": 0.0,
            "second_candidate_element_id": None,
            "table_data": None,
            "match_status": "not_found",
        }

    # 점수 높은 순 -> 행 겹침 많은 순 -> 페이지 앞선 순 정렬
    scored_candidates.sort(
        key=lambda x: (-x["keyword_score"], -x["row_overlap"], x["page_number"])
    )

    best = scored_candidates[0]
    best_el = best["element"]
    second_id = (
        scored_candidates[1]["element"].get("element_id")
        if len(scored_candidates) > 1
        else None
    )

    return {
        "matched": True,
        "element_id": best_el.get("element_id"),
        "page_number": best_el.get("page_number"),
        "caption": best_el.get("caption"),
        "match_score": best["keyword_score"],
        "second_candidate_element_id": second_id,
        "table_data": best_el.get("table_data"),
        "match_status": "matched",
    }


def align_matched_tables(
    matched_doc_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    매칭된 표들의 행 라벨을 정규화하여 같은 행끼리 나란히 맞춥니다.
    단위는 변환하지 않고 유지합니다.
    """
    canonical_order: List[str] = []
    canonical_to_norm: Dict[str, str] = {}
    canonical_to_rows: Dict[str, Dict[str, Dict[str, Any]]] = {}
    canonical_to_raw_labels: Dict[str, Dict[str, str]] = {}

    for doc_res in matched_doc_results:
        if not doc_res.get("matched"):
            continue

        doc_name = doc_res.get("doc_name") or "unknown_doc"
        tdata = doc_res.get("table_data")
        if not tdata:
            continue

        rows = (
            tdata.get("rows")
            if isinstance(tdata, dict)
            else getattr(tdata, "rows", None)
        ) or []
        columns = (
            tdata.get("columns")
            if isinstance(tdata, dict)
            else getattr(tdata, "columns", None)
        ) or []

        label_col = columns[0] if columns else None

        for row in rows:
            if not isinstance(row, dict) or not row:
                continue

            # 첫 번째 열을 행 라벨로 취급
            first_key = label_col if (label_col and label_col in row) else list(row.keys())[0]
            raw_label = str(row.get(first_key, "")).strip()
            norm_lbl = normalize_row_label(raw_label)
            canon_key = get_canonical_row_key(norm_lbl)

            if not canon_key:
                continue

            if canon_key not in canonical_to_norm:
                canonical_order.append(canon_key)
                canonical_to_norm[canon_key] = norm_lbl
                canonical_to_rows[canon_key] = {}
                canonical_to_raw_labels[canon_key] = {}

            # 해당 문서에서의 원본 라벨 및 수치 열들 저장
            canonical_to_raw_labels[canon_key][doc_name] = raw_label
            val_cols = {k: v for k, v in row.items() if k != first_key}
            canonical_to_rows[canon_key][doc_name] = val_cols

    aligned_result: List[Dict[str, Any]] = []
    for c_key in canonical_order:
        aligned_result.append({
            "row_label": canonical_to_norm[c_key],
            "raw_labels": canonical_to_raw_labels.get(c_key, {}),
            "values": canonical_to_rows.get(c_key, {}),
        })

    return aligned_result
