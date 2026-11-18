"""
FigIndex 종목 그룹별 지표 도표 비교 매트릭스 점검 스크립트

10개 종목 그룹 x 3개 지표(TARGET_PRICE, ANNUAL_ESTIMATE, QUARTERLY_RESULT)를 점검하여
문서별 matched / not_found 결과를 콘솔 표로 출력하고, not_found 건의 원인(CAP_LIMIT,
KEYWORD_MISS, ABSENT)을 분류하여 compare_matrix.json에 저장합니다.
"""
import json
import os
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List

# 루트 및 figindex 디렉토리 경로 추가
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "figindex"))

try:
    from shared.schemas import ElementType
except ImportError:
    from figindex.shared.schemas import ElementType

try:
    from compare.metrics import MetricType
    from compare.service import (
        compare_company_metric,
        load_compare_pairs,
        fetch_elements_for_documents,
    )
except ImportError:
    from figindex.compare.metrics import MetricType
    from figindex.compare.service import (
        compare_company_metric,
        load_compare_pairs,
        fetch_elements_for_documents,
    )


# 지표별 관련 단어 사전 (KEYWORD_MISS 판정용)
METRIC_RELATED_WORDS: Dict[MetricType, List[str]] = {
    MetricType.TARGET_PRICE: [
        "목표", "주가", "적정", "산출", "산정", "valuation", "밸류에이션"
    ],
    MetricType.ANNUAL_ESTIMATE: [
        "추정", "실적", "전망", "수익", "earnings", "forecast", "연간"
    ],
    MetricType.QUARTERLY_RESULT: [
        "분기", "실적", "3q", "4q", "review", "잠정", "2q", "1q"
    ],
}


def get_display_width(text: str) -> int:
    """한글/전각 문자를 고려한 터미널 출력 폭 계산"""
    width = 0
    for ch in str(text):
        eaw = unicodedata.east_asian_width(ch)
        if eaw in ("W", "F"):
            width += 2
        else:
            width += 1
    return width


def pad_right(text: str, target_width: int) -> str:
    """출력 폭에 맞게 공백을 채웁니다."""
    cur_width = get_display_width(text)
    if cur_width >= target_width:
        return text
    return text + " " * (target_width - cur_width)


def truncate_text(text: str, max_width: int) -> str:
    """출력 폭에 맞게 자르고 말줄임표(..)를 붙입니다."""
    if get_display_width(text) <= max_width:
        return text
    res = ""
    for ch in text:
        if get_display_width(res + ch) > max_width - 2:
            return res + ".."
        res += ch
    return res + ".."


def main():
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    collection_name = os.getenv("QDRANT_COLLECTION", "figindex_elements_v2")

    print("=" * 105)
    print(" FigIndex 종목 그룹별 지표 도표 비교 매트릭스 일괄 점검")
    print(f" - Qdrant: {qdrant_url} (컬렉션: {collection_name})")
    print(" - 대상 지표: TARGET_PRICE, ANNUAL_ESTIMATE, QUARTERLY_RESULT")
    print("=" * 105)

    pairs = load_compare_pairs()
    if not pairs:
        print("[Error] data/compare_pairs.json 데이터를 찾을 수 없습니다.")
        sys.exit(1)

    # 전체 대상 문서 목록 수집 및 Qdrant 사전 조회
    all_doc_names: List[str] = []
    for g in pairs:
        for d in g.get("documents", []):
            if "doc_name" in d:
                all_doc_names.append(d["doc_name"])

    print(f"\n[1/3] 대상 {len(pairs)}개 그룹 ({len(all_doc_names)}개 문서) 요소 조회 중...")
    all_elements_by_doc = fetch_elements_for_documents(
        doc_names=all_doc_names,
        qdrant_url=qdrant_url,
        collection_name=collection_name,
    )

    print(f"[2/3] 매칭 매트릭스 연산 수행 중...")

    metrics = [
        MetricType.TARGET_PRICE,
        MetricType.ANNUAL_ESTIMATE,
        MetricType.QUARTERLY_RESULT,
    ]

    matrix_results: List[Dict[str, Any]] = []

    # 콘솔 헤더 출력
    header = (
        f"{pad_right('종목명', 10)} | "
        f"{pad_right('지표 (Metric)', 18)} | "
        f"{pad_right('출처(증권사)', 12)} | "
        f"{pad_right('상태', 10)} | "
        f"{pad_right('도표ID', 16)} | "
        f"{pad_right('p', 4)} | "
        f"캡션 (Caption)"
    )
    print("\n" + "-" * 105)
    print(header)
    print("-" * 105)

    total_checks = 0
    total_matched = 0
    total_not_found = 0

    not_found_records: List[Dict[str, Any]] = []

    for g_idx, group in enumerate(pairs, 1):
        company = group["company"]

        for metric in metrics:
            comp_res = compare_company_metric(
                company=company,
                metric=metric,
                qdrant_url=qdrant_url,
                collection_name=collection_name,
            )

            group_metric_record = {
                "company": company,
                "metric": metric.value,
                "documents": comp_res.get("documents", []),
                "aligned_rows_count": len(comp_res.get("aligned_rows", [])),
                "aligned_rows": comp_res.get("aligned_rows", []),
            }

            for d in comp_res.get("documents", []):
                total_checks += 1
                is_matched = d.get("matched", False)
                status_str = "MATCHED" if is_matched else "not_found"
                dname = d.get("doc_name", "")

                doc_all_elements = all_elements_by_doc.get(dname, [])
                table_elements = [
                    e for e in doc_all_elements
                    if e.get("element_type") == ElementType.TABLE.value
                    or e.get("element_type") == ElementType.TABLE
                ]
                table_caps = [e.get("caption") or "" for e in table_elements]

                d["all_table_captions"] = table_caps
                d["total_elements_in_doc"] = len(doc_all_elements)

                if is_matched:
                    total_matched += 1
                    d["reason"] = None
                else:
                    total_not_found += 1
                    # not_found 원인 분류 규칙
                    # 1. 문서 도표 수가 정확히 4개면 CAP_LIMIT 의심
                    # 2. 캡션 중 지표 관련 단어가 있는데 매칭이 안 됐으면 KEYWORD_MISS
                    # 3. 그 외는 ABSENT
                    combined_caps = " ".join(table_caps).lower()
                    has_related_words = any(
                        w.lower() in combined_caps
                        for w in METRIC_RELATED_WORDS.get(metric, [])
                    )

                    if len(doc_all_elements) == 4:
                        reason = "CAP_LIMIT"
                    elif has_related_words:
                        reason = "KEYWORD_MISS"
                    else:
                        reason = "ABSENT"

                    d["reason"] = reason

                    matched_indicators = [
                        w for w in METRIC_RELATED_WORDS.get(metric, [])
                        if w.lower() in combined_caps
                    ]
                    not_found_records.append({
                        "company": company,
                        "metric": metric.value,
                        "source_org": d.get("source_org") or "기타",
                        "doc_name": dname,
                        "reason": reason,
                        "total_elements": len(doc_all_elements),
                        "table_count": len(table_elements),
                        "table_captions": table_caps,
                        "matched_indicators": matched_indicators,
                    })

                source_org = d.get("source_org") or "기타"
                eid = d.get("element_id") or "-"
                pnum = str(d.get("page_number") or "-")
                caption_text = d.get("caption") or "-"

                line = (
                    f"{pad_right(company, 10)} | "
                    f"{pad_right(metric.value, 18)} | "
                    f"{pad_right(source_org, 12)} | "
                    f"{pad_right(status_str, 10)} | "
                    f"{pad_right(eid, 16)} | "
                    f"{pad_right(pnum, 4)} | "
                    f"{truncate_text(caption_text, 36)}"
                )
                print(line)

            matrix_results.append(group_metric_record)

        if g_idx < len(pairs):
            print("-" * 105)

    print("=" * 105)
    print(f"\n[3/3] 점검 결과 요약:")
    print(f"  - 총 종목 그룹: {len(pairs)}개 (문서 {len(pairs) * 3}건)")
    print(f"  - 총 점검 건수: {total_checks}건 (10개 그룹 x 3개 지표 x 3개 문서)")
    print(f"  - 매칭 성공 (MATCHED): {total_matched}건 ({total_matched / total_checks * 100:.1f}%)")
    print(f"  - 미매칭 (not_found): {total_not_found}건 ({total_not_found / total_checks * 100:.1f}%)")

    # 규칙 변경 전 vs 후 지표별 매칭 수 비교
    # 1차 규칙: 19 / 24 / 13
    # 2차 규칙 (직전): 17 / 26 / 24
    prev_counts = {
        MetricType.TARGET_PRICE.value: 17,
        MetricType.ANNUAL_ESTIMATE.value: 26,
        MetricType.QUARTERLY_RESULT.value: 24,
    }
    after_counts = {
        m.value: 0 for m in metrics
    }
    matched_by_metric: Dict[str, List[Dict[str, Any]]] = {
        m.value: [] for m in metrics
    }

    for item in matrix_results:
        m_val = item["metric"]
        for d in item.get("documents", []):
            if d.get("matched"):
                after_counts[m_val] += 1
                matched_by_metric[m_val].append({
                    "company": item["company"],
                    "source_org": d.get("source_org") or "기타",
                    "caption": d.get("caption") or "(캡션 없음)",
                    "page_number": d.get("page_number"),
                    "element_id": d.get("element_id"),
                    "match_rule": d.get("match_rule") or "caption",
                    "match_score": d.get("match_score", 0),
                })

    print("\n" + "=" * 105)
    print("                [규칙 보완 전(67건 기준) / 후 지표별 매칭 수 비교]")
    print("=" * 105)
    cmp_header = f"{pad_right('지표 (Metric)', 22)} | {pad_right('직전(67건 기준)', 16)} | {pad_right('보완 후', 10)} | {pad_right('변동 (증감)', 12)}"
    print(cmp_header)
    print("-" * 105)
    total_prev = sum(prev_counts.values())
    total_after = sum(after_counts.values())
    for m in metrics:
        m_val = m.value
        p_cnt = prev_counts.get(m_val, 0)
        a_cnt = after_counts.get(m_val, 0)
        diff = a_cnt - p_cnt
        diff_str = f"+{diff}" if diff > 0 else f"{diff}"
        print(f"{pad_right(m_val, 22)} | {pad_right(str(p_cnt) + '건', 16)} | {pad_right(str(a_cnt) + '건', 10)} | {pad_right(diff_str, 12)}")
    print("-" * 105)
    tot_diff = total_after - total_prev
    tot_diff_str = f"+{tot_diff}" if tot_diff > 0 else f"{tot_diff}"
    print(f"{pad_right('총계 (Total)', 22)} | {pad_right(str(total_prev) + '건', 14)} | {pad_right(str(total_after) + '건', 10)} | {pad_right(tot_diff_str, 12)}")

    # TARGET_PRICE MATCHED 상세 목록 출력
    tp_val = MetricType.TARGET_PRICE.value
    tp_items = matched_by_metric.get(tp_val, [])
    print("\n" + "=" * 105)
    print(f"                [TARGET_PRICE MATCHED 목록 (총 {len(tp_items)}건)]")
    print("=" * 105)
    for idx, mi in enumerate(tp_items, 1):
        comp = mi["company"]
        s_org = mi["source_org"]
        cap = mi["caption"]
        m_rule = mi["match_rule"]
        p_num = mi["page_number"]
        eid = mi["element_id"]
        print(f" {idx:2d}. [{comp} · {s_org}] \"{cap}\" (p.{p_num}, ID: {eid})")

    # not_found 원인별 묶음 상세 출력
    print("\n" + "=" * 105)
    print(f"                [not_found 미매칭 원인별 상세 분류 (총 {len(not_found_records)}건)]")
    print("=" * 105)

    reasons_order = ["CAP_LIMIT", "KEYWORD_MISS", "ABSENT"]
    reason_titles = {
        "CAP_LIMIT": "1. CAP_LIMIT 의심 (문서 도표 수가 정확히 4개로 잘려 추가 도표 색인 누락 의심)",
        "KEYWORD_MISS": "2. KEYWORD_MISS (문서에 5개 이상 도표가 있고 캡션에 지표 관련어가 있으나 매칭 누락)",
        "ABSENT": "3. ABSENT (문서 내에 해당 지표 관련 도표가 전혀 존재하지 않음)",
    }

    for r_code in reasons_order:
        sub_items = [r for r in not_found_records if r["reason"] == r_code]
        print(f"\n▶ {reason_titles[r_code]} : 총 {len(sub_items)}건")
        print("-" * 105)

        for idx, item in enumerate(sub_items, 1):
            comp = item["company"]
            m_val = item["metric"]
            s_org = item["source_org"]
            d_name = item["doc_name"]
            tot_n = item["total_elements"]
            tbl_n = item["table_count"]
            caps = item["table_captions"]

            print(f" ({idx:2d}) [{comp}] {m_val} | {s_org} ({d_name})")
            print(f"      - 추출 도표 수: 전체 {tot_n}개 중 TABLE {tbl_n}개")
            if item.get("matched_indicators"):
                print(f"      - 캡션 내 지표 관련 단어: {item['matched_indicators']}")
            print(f"      - 전체 TABLE 캡션 목록 ({len(caps)}개):")
            if caps:
                for c_idx, cap in enumerate(caps, 1):
                    print(f"         {c_idx}. \"{cap}\"")
            else:
                print("         (추출된 TABLE 없음)")
            print()

    # JSON 저장 (reason 필드 포함)
    output_path = REPO_ROOT / "data" / "compare_matrix.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(matrix_results, f, ensure_ascii=False, indent=2)

    print("=" * 105)
    print(f"✔ data/compare_matrix.json에 reason 필드 반영 저장 완료 ({output_path.resolve()})\n")


if __name__ == "__main__":
    main()
