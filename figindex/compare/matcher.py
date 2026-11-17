"""
FigIndex 도표 비교 매칭 및 행 라벨 정렬 엔진
"""
import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from shared.schemas import ElementType, TableData
except ImportError:
    from figindex.shared.schemas import ElementType, TableData

from .metrics import (
    MetricType,
    METRIC_KEYWORDS,
    EXCLUDE_KEYWORDS,
    FINANCIAL_INDICATORS,
    TARGET_PRICE_REQUIRED_LABELS,
    TARGET_PRICE_DISQUALIFY_CAPTION,
    TARGET_PRICE_PRIORITY_KEYWORDS,
)


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


ESTIMATE_YEAR_PATTERN = re.compile(r"(?:20\d{2}|\d{2})\s*[EFef]")
QUARTER_LABEL_PATTERN = re.compile(
    r"(?:[1-4]Q\s*\d{2}|\d{2}\s*[1-4]Q|[1-4]Q(?:\s*\(?[PEFpef]\)?)?|[1-4]분기)",
    re.IGNORECASE,
)


def clean_text(s: Any) -> str:
    """공백을 제거하고 소문자로 변환합니다."""
    if s is None:
        return ""
    return re.sub(r"\s+", "", str(s)).lower()


def has_estimate_year(table_data: Any) -> bool:
    """테이블의 컬럼 헤더나 셀 내용에 추정 연도(예: 2026E, 27F)가 포함되어 있는지 검사합니다."""
    if not table_data:
        return False
    cols = []
    rows = []
    if isinstance(table_data, dict):
        cols = table_data.get("columns") or []
        rows = table_data.get("rows") or []
    elif hasattr(table_data, "columns"):
        cols = getattr(table_data, "columns", []) or []
        rows = getattr(table_data, "rows", []) or []

    text_parts = [str(c) for c in cols]
    for r in rows:
        if isinstance(r, dict):
            for k, v in r.items():
                text_parts.append(str(k))
                text_parts.append(str(v))
    combined = " ".join(text_parts)
    return bool(ESTIMATE_YEAR_PATTERN.search(combined))


def count_quarter_labels(table_data: Any) -> int:
    """테이블의 컬럼 헤더 등에서 서로 다른 분기 표기(예: 3Q26, 3Q26P 등)의 개수를 셉니다."""
    if not table_data:
        return 0
    cols = []
    if isinstance(table_data, dict):
        cols = table_data.get("columns") or []
    elif hasattr(table_data, "columns"):
        cols = getattr(table_data, "columns", []) or []

    quarters = set()
    for c in cols:
        found = QUARTER_LABEL_PATTERN.findall(str(c))
        for f in found:
            clean_f = re.sub(r"\s+", "", f).upper()
            quarters.add(clean_f)
    return len(quarters)


def has_target_price_required_labels(table_data: Any) -> bool:
    """
    표의 행 또는 열 라벨에 {목표주가, 적정주가, 적정가치, 적용, Target} 중 하나가 있는지 검증합니다.
    """
    if not table_data:
        return False
    cols = []
    rows = []
    if isinstance(table_data, dict):
        cols = table_data.get("columns") or []
        rows = table_data.get("rows") or []
    elif hasattr(table_data, "columns"):
        cols = getattr(table_data, "columns", []) or []
        rows = getattr(table_data, "rows", []) or []

    # 1. 열 라벨(columns) 검사
    for c in cols:
        clean_c = clean_text(c)
        if any(clean_text(req) in clean_c for req in TARGET_PRICE_REQUIRED_LABELS):
            return True

    # 2. 행 라벨(rows) 검사
    for r in rows:
        if isinstance(r, dict) and r:
            first_val = clean_text(list(r.values())[0])
            if any(clean_text(req) in first_val for req in TARGET_PRICE_REQUIRED_LABELS):
                return True
            for k in r.keys():
                clean_k = clean_text(k)
                if any(clean_text(req) in clean_k for req in TARGET_PRICE_REQUIRED_LABELS):
                    return True

    return False


def get_target_price_priority(clean_cap: str) -> int:
    """
    TARGET_PRICE 표의 우선순위를 결정합니다.
    3: 캡션에 {산출, 산정, 적정주가} 포함 (1순위)
    2: 일반 목표주가/Valuation 표 (2순위)
    1: '요약' 박스형 표 (산출표가 없을 때만 고름)
    """
    if any(clean_text(kw) in clean_cap for kw in TARGET_PRICE_PRIORITY_KEYWORDS):
        return 3
    if "요약" in clean_cap:
        return 1
    return 2


def count_row_overlaps(table_data: Any) -> int:
    """행 라벨 중 주요 재무지표 항목과 겹치는 개수를 셉니다."""
    row_overlap_count = 0
    if not table_data:
        return 0
    rows = (
        table_data.get("rows")
        if isinstance(table_data, dict)
        else getattr(table_data, "rows", None)
    ) or []
    for r in rows:
        if isinstance(r, dict) and r:
            first_val = str(list(r.values())[0]).lower()
            if any(ind.lower() in first_val for ind in FINANCIAL_INDICATORS):
                row_overlap_count += 1
    return row_overlap_count


def score_element_for_metric(
    element: Dict[str, Any],
    metric: MetricType,
) -> Tuple[float, int, List[str]]:
    """
    단일 도표 요소에 대해 지표 캡션 키워드 점수 및 행 라벨 재무항목 겹침 수를 계산합니다.
    규칙:
    - 캡션과 키워드 모두 공백 제거 후 비교
    - TARGET_PRICE:
      * 캡션에 Forecast 또는 earning이 있으면 탈락
      * 표의 행 또는 열 라벨에 {목표주가, 적정주가, 적정가치, 적용, Target} 중 하나가 없으면 탈락
    - ANNUAL_ESTIMATE & QUARTERLY_RESULT:
      * 캡션에 '가정'이 들어간 표는 탈락
    - ANNUAL_ESTIMATE: '실적' + {추정, 전망, 추이, 예상} 또는 관련 키워드가 있고, 기간 라벨에 추정 연도가 있어야 유효 (없으면 탈락)
    - QUARTERLY_RESULT: {분기, 1Q, 2Q, 3Q, 4Q, Review, 잠정} 중 하나가 있으면 유효
    - 제외 키워드(변동내역, 투자등급, 투자의견비율, 괴리율 등) 포함 시 탈락
    """
    # TABLE 유형이 아니면 매칭 대상 제외
    element_type = element.get("element_type")
    if element_type != ElementType.TABLE.value and element_type != ElementType.TABLE:
        return 0.0, 0, []

    caption = element.get("caption") or ""
    clean_cap = clean_text(caption)
    if not clean_cap:
        return 0.0, 0, []

    # 매칭 제외 키워드 검사 (공백 제거 후 비교)
    for ex in EXCLUDE_KEYWORDS:
        if clean_text(ex) in clean_cap:
            return 0.0, 0, []

    # ANNUAL_ESTIMATE 및 QUARTERLY_RESULT: 캡션에 '가정'이 들어간 표 탈락
    if metric in (MetricType.ANNUAL_ESTIMATE, MetricType.QUARTERLY_RESULT):
        if "가정" in clean_cap:
            return 0.0, 0, []

    matched_keywords: List[str] = []
    table_data = element.get("table_data")

    if metric == MetricType.TARGET_PRICE:
        # 캡션에 Forecast 또는 earning이 들어간 표 탈락
        if any(dis in clean_cap for dis in TARGET_PRICE_DISQUALIFY_CAPTION):
            return 0.0, 0, []

        keywords = METRIC_KEYWORDS.get(MetricType.TARGET_PRICE, [])
        for kw in keywords:
            if clean_text(kw) in clean_cap:
                matched_keywords.append(kw)
        if not matched_keywords:
            return 0.0, 0, []

    elif metric == MetricType.ANNUAL_ESTIMATE:
        # 캡션에 '실적'과 {추정, 전망, 추이, 예상} 중 하나가 함께 있거나 기존 키워드 매칭
        has_rel_word = any(w in clean_cap for w in ["추정", "전망", "추이", "예상"])
        has_combo = ("실적" in clean_cap and has_rel_word)
        existing_kws = METRIC_KEYWORDS.get(MetricType.ANNUAL_ESTIMATE, [])
        for kw in existing_kws:
            if clean_text(kw) in clean_cap:
                matched_keywords.append(kw)

        if has_combo:
            if "실적" not in matched_keywords:
                matched_keywords.append("실적")

        if not matched_keywords and not has_combo:
            return 0.0, 0, []

        # 기간 라벨에 추정 연도(예: 2026E, 27F)가 하나도 없으면 탈락
        if not has_estimate_year(table_data):
            return 0.0, 0, []

    elif metric == MetricType.QUARTERLY_RESULT:
        # {분기, 1Q, 2Q, 3Q, 4Q, Review, 잠정} 중 하나
        q_kws = ["분기", "1Q", "2Q", "3Q", "4Q", "Review", "잠정"]
        for kw in q_kws:
            if clean_text(kw) in clean_cap:
                matched_keywords.append(kw)
        if not matched_keywords:
            return 0.0, 0, []

    keyword_score = float(len(matched_keywords))
    row_overlap_count = count_row_overlaps(table_data)

    return keyword_score, row_overlap_count, matched_keywords


def find_best_table_for_doc(
    elements: List[Dict[str, Any]],
    metric: MetricType,
) -> Dict[str, Any]:
    """
    문서의 요소 목록에서 지정된 지표에 가장 적합한 TABLE을 찾습니다.
    규칙:
    1. TARGET_PRICE:
       - 캡션에 {산출, 산정, 적정주가}가 있는 표를 1순위로
       - '요약' 박스형 표는 산출표가 없을 때만 고르게 함
    2. 캡션 키워드 점수가 가장 높은 표 선택 (match_rule = 'caption')
    3. QUARTERLY_RESULT의 경우 캡션 후보가 없으면, 기간 라벨에 분기 표기(예: 3Q26, 3Q26P)가 2개 이상인 TABLE을 대신 후보로 선택 (match_rule = 'period_label')
    4. 키워드가 하나도 맞지 않고 폴백도 없으면 not_found 반환
    5. 후보가 여러 개면 2순위 후보 id도 함께 반환
    """
    scored_candidates = []
    for el in elements:
        k_score, r_overlap, m_kws = score_element_for_metric(el, metric)
        if k_score > 0.0:
            caption = el.get("caption") or ""
            clean_cap = clean_text(caption)
            tp_priority = get_target_price_priority(clean_cap) if metric == MetricType.TARGET_PRICE else 0
            scored_candidates.append({
                "keyword_score": k_score,
                "row_overlap": r_overlap,
                "tp_priority": tp_priority,
                "element": el,
                "matched_keywords": m_kws,
                "page_number": el.get("page_number", 999),
                "match_rule": "caption",
            })

    # QUARTERLY_RESULT: 캡션 후보가 없으면 기간 라벨(period_label) 폴백
    if not scored_candidates and metric == MetricType.QUARTERLY_RESULT:
        period_candidates = []
        for el in elements:
            el_type = el.get("element_type")
            if el_type != ElementType.TABLE.value and el_type != ElementType.TABLE:
                continue

            caption = el.get("caption") or ""
            clean_cap = clean_text(caption)
            # 제외 키워드 체크 및 '가정' 제외
            if any(clean_text(ex) in clean_cap for ex in EXCLUDE_KEYWORDS):
                continue
            if "가정" in clean_cap:
                continue

            tdata = el.get("table_data")
            q_count = count_quarter_labels(tdata)
            if q_count >= 2:
                r_overlap = count_row_overlaps(tdata)
                period_candidates.append({
                    "keyword_score": float(q_count),
                    "row_overlap": r_overlap,
                    "tp_priority": 0,
                    "element": el,
                    "matched_keywords": [f"{q_count}개 분기 표기"],
                    "page_number": el.get("page_number", 999),
                    "match_rule": "period_label",
                })

        if period_candidates:
            scored_candidates = period_candidates

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
            "match_rule": None,
        }

    # 점수 높은 순 -> TARGET_PRICE 우선순위 -> 행 겹침 많은 순 -> 페이지 앞선 순 정렬
    scored_candidates.sort(
        key=lambda x: (
            -x.get("tp_priority", 0),
            -x["keyword_score"],
            -x["row_overlap"],
            x["page_number"],
        )
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
        "match_rule": best["match_rule"],
    }


def parse_quarter_key(col_name: Any) -> Optional[Tuple[int, int, str]]:
    """
    열 이름에서 연도와 분기를 파악하여 (연도, 분기, '3Q26') 형태의 튜플을 반환합니다.
    """
    s = clean_text(col_name)
    # 1) 3q26, 3q26p, 3q2026 등
    m1 = re.search(r"([1-4])q(?:20)?(\d{2})", s)
    if m1:
        q = int(m1.group(1))
        yy = int(m1.group(2))
        year = 2000 + yy if yy < 100 else yy
        return year, q, f"{q}Q{yy:02d}"

    # 2) 26년 3q, 26.3q 등
    m2 = re.search(r"(?:20)?(\d{2})[^1-4q]*([1-4])q", s)
    if m2:
        yy = int(m2.group(1))
        q = int(m2.group(2))
        year = 2000 + yy if yy < 100 else yy
        return year, q, f"{q}Q{yy:02d}"

    # 3) 26년 3분기 등
    m3 = re.search(r"(?:20)?(\d{2})[^1-4]*([1-4])분기", s)
    if m3:
        yy = int(m3.group(1))
        q = int(m3.group(2))
        year = 2000 + yy if yy < 100 else yy
        return year, q, f"{q}Q{yy:02d}"

    return None


def align_matched_tables(
    matched_doc_results: List[Dict[str, Any]],
    metric: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """
    매칭된 표들의 행 라벨을 정규화하여 같은 행끼리 나란히 맞춥니다.
    QUARTERLY_RESULT인 경우, 그룹 문서들에 공통으로 있는 가장 최근 실적 분기 열만 골라 나란히 보여줍니다.
    단위는 변환하지 않고 유지합니다.
    """
    canonical_order: List[str] = []
    canonical_to_norm: Dict[str, str] = {}
    canonical_to_rows: Dict[str, Dict[str, Dict[str, Any]]] = {}
    canonical_to_raw_labels: Dict[str, Dict[str, str]] = {}

    target_common_quarter: Optional[str] = None
    metric_str = metric.value if hasattr(metric, "value") else str(metric or "")
    if metric_str == MetricType.QUARTERLY_RESULT.value:
        doc_quarters: Dict[str, Dict[str, str]] = {}
        for doc_res in matched_doc_results:
            if not doc_res.get("matched"):
                continue
            doc_name = doc_res.get("doc_name") or "unknown_doc"
            tdata = doc_res.get("table_data")
            cols = (
                tdata.get("columns")
                if isinstance(tdata, dict)
                else getattr(tdata, "columns", None)
            ) or []
            qmap: Dict[str, str] = {}
            for c in cols:
                parsed = parse_quarter_key(c)
                if parsed:
                    _, _, q_code = parsed
                    if q_code not in qmap:
                        qmap[q_code] = c
            if qmap:
                doc_quarters[doc_name] = qmap

        if doc_quarters:
            # 모든 매칭 문서에 공통으로 존재하는 분기 탐색
            common_set = set.intersection(*(set(qm.keys()) for qm in doc_quarters.values()))
            if not common_set:
                freq: Dict[str, int] = {}
                for qm in doc_quarters.values():
                    for qk in qm.keys():
                        freq[qk] = freq.get(qk, 0) + 1
                max_f = max(freq.values())
                common_set = {k for k, v in freq.items() if v == max_f}

            def q_sort_key(code: str) -> Tuple[int, int]:
                try:
                    q = int(code[0])
                    yy = int(code[2:])
                    return (yy, q)
                except Exception:
                    return (0, 0)

            if common_set:
                target_common_quarter = max(common_set, key=q_sort_key)

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

            # 해당 문서에서의 원본 라벨 및 수치 열 저장
            canonical_to_raw_labels[canon_key][doc_name] = raw_label

            if target_common_quarter:
                orig_col = None
                for c in columns:
                    parsed = parse_quarter_key(c)
                    if parsed and parsed[2] == target_common_quarter:
                        orig_col = c
                        break
                if orig_col and orig_col in row:
                    val_cols = {target_common_quarter: row[orig_col]}
                else:
                    val_cols = {target_common_quarter: None}
            else:
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
