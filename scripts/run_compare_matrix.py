"""
FigIndex 종목 그룹별 지표 도표 비교 매트릭스 점검 스크립트

10개 종목 그룹 x 3개 지표(TARGET_PRICE, ANNUAL_ESTIMATE, QUARTERLY_RESULT)를 점검하여
문서별 matched / not_found 결과를 콘솔 표로 출력하고 data/compare_matrix.json에 저장합니다.
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
    from compare.metrics import MetricType
    from compare.service import compare_company_metric, load_compare_pairs
except ImportError:
    from figindex.compare.metrics import MetricType
    from figindex.compare.service import compare_company_metric, load_compare_pairs


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

    print(f"\n[1/2] 총 {len(pairs)}개 종목 그룹 비교 수행 중...")

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
            matrix_results.append(group_metric_record)

            for d in comp_res.get("documents", []):
                total_checks += 1
                is_matched = d.get("matched", False)
                status_str = "MATCHED" if is_matched else "not_found"
                if is_matched:
                    total_matched += 1
                else:
                    total_not_found += 1

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

        if g_idx < len(pairs):
            print("-" * 105)

    print("=" * 105)
    print(f"\n[2/2] 점검 결과 요약:")
    print(f"  - 총 종목 그룹: {len(pairs)}개 (문서 {len(pairs) * 3}건)")
    print(f"  - 총 점검 건수: {total_checks}건 (10개 그룹 x 3개 지표 x 3개 문서)")
    print(f"  - 매칭 성공 (MATCHED): {total_matched}건 ({total_matched / total_checks * 100:.1f}%)")
    print(f"  - 미매칭 (not_found): {total_not_found}건 ({total_not_found / total_checks * 100:.1f}%)")

    # JSON 저장
    output_path = REPO_ROOT / "data" / "compare_matrix.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(matrix_results, f, ensure_ascii=False, indent=2)

    print(f"\n✔ data/compare_matrix.json 저장 완료 ({output_path.resolve()})\n")


if __name__ == "__main__":
    main()
