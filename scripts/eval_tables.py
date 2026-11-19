"""표 평가: table_valid_rate, cell_accuracy를 잰다 (docs/glossary.md 12절). 읽기 전용.

table_valid_rate = TABLE 요소 중 table_data가 TableData 검증을 통과하고 행이 1개 이상인 수 ÷ TABLE 요소 수
                   (반려된 요소는 빼고 센다). 숫자를 '1,234'처럼 문자열로 저장한 표도 검증은 통과하므로,
                   그 규모는 pipeline_version별 '저장 규칙 위반'으로 따로 보고한다.
cell_accuracy    = 수치 정답셋의 숫자 셀 중 값이 같은 셀 수 ÷ 숫자 셀 수
                   셀은 (첫 열 행 라벨, 열 이름)으로 맞추고, 못 찾은 셀은 틀린 것으로 센다.
                   카드가 없는 표('요소 없음')의 셀도 모두 틀린 것으로 들어간다.
아래 두 값은 위 값을 원인별로 나눠 보기 위한 보조 지표다 (11-19 팀장 결정, glossary 12절 추가 대기).
gt_table_coverage       = 정답 표 중 카드가 있고 연결된 표 수 ÷ 정답 표 수 (표를 빠짐없이 뽑았는지)
cell_accuracy_extracted = 카드가 있는 표의 숫자 셀만 채점한 cell_accuracy (뽑은 표의 숫자를 맞게 읽었는지)

정답셋 (정답셋 작업 시트에서 옮긴 것, 원문 기준)
    figindex/data/gt/table/cells.csv   표의 셀 1칸 = 1줄 ('수치표' 탭)
    figindex/data/gt/table/links.csv   표 ID ↔ element_id ('수치표_연결' 탭)

채점 방법
- 정답 값이 숫자가 아닌 셀(NA, 텍스트)은 숫자 셀이 아니므로 빼고 센다.
- AI 값은 pipeline/table_parse.py의 parse_cell_value로 정리한 뒤 비교한다 ('1,202.2' → 1202.2, '6.0%' → 6.0).
  읽은 숫자가 맞는지를 재는 지표라서다. 정리 없이는 숫자가 아니었던 칸 수는 rule_violation_cells로 따로 보고한다.
- 행 라벨·열 이름은 공백을 모두 빼고 비교한다. 같은 행 라벨이 여러 번 나오면 나온 순서대로 짝짓는다.
- 행과 열이 바뀌어 저장된 표는 (열 이름, 행 라벨)로 한 번 더 찾고, transposed_cells로 따로 센다.
- links.csv에 아직 없는 표는 채점하지 않고 '미연결'로 보고한다.
- 연결 판정이 '다른 표가 잡힘'·'요소 없음'이거나 요소가 컬렉션에 없거나 반려됐으면 그 표의 셀은 모두 틀린 것으로 센다.
- 연결된 요소의 문서·페이지가 정답과 다르면 '연결 오류'로 보고하고 그 표의 셀은 모두 틀린 것으로 센다.

사용법 (Qdrant 실행 중, 저장소 루트에서):
    python scripts/eval_tables.py
    python scripts/eval_tables.py --out table_eval.json --detail table_eval_cells.csv

정답셋은 채점 전용이다. 이 점수를 보고 정답셋을 고치지 않는다.
"""
import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "figindex"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

try:
    from shared.schemas import ElementType, ReviewStatus, TableData
    from pipeline.table_parse import parse_cell_value
except ImportError as e:
    sys.exit(f"figindex 모듈을 불러오지 못했습니다: {e}\n'pip install pydantic' 후 다시 실행해 주세요.")

from diagnose_empty_tables import scroll_all

GT_DIR = REPO_ROOT / "figindex/data/gt/table"
# links.csv의 link_status 값 (시트 '수치표_연결' 탭 드롭다운과 같아야 한다)
LINK_SAME = "같은 표"
LINK_PARTIAL = "표 일부만 잡힘"
SCORABLE_LINKS = {LINK_SAME, LINK_PARTIAL}

DETAIL_COLUMNS = ["table_id", "element_id", "row_label", "column", "expected", "actual", "result"]


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def norm_label(text: Any) -> str:
    """행 라벨·열 이름 비교용: 공백을 모두 빼고 소문자로."""
    return "".join(str(text).split()).lower() if text is not None else ""


def same_number(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# table_valid_rate
# ---------------------------------------------------------------------------

def table_is_valid(table_data: Any) -> Tuple[bool, str]:
    if not isinstance(table_data, dict):
        return False, "table_data 없음"
    try:
        table = TableData(**table_data)
    except Exception as e:
        return False, f"검증 실패: {str(e).splitlines()[0][:80]}"
    if not table.rows:
        return False, "행 없음"
    return True, ""


def count_rule_violations(table_data: Any) -> int:
    """숫자로 읽히는데 문자열로 저장된 칸 수 (첫 열 행 라벨은 뺌). 예: '1,202.2', '6.0%'"""
    if not isinstance(table_data, dict):
        return 0
    columns = [str(c) for c in (table_data.get("columns") or [])]
    count = 0
    for row in table_data.get("rows") or []:
        if not isinstance(row, dict):
            continue
        for col in columns[1:]:
            raw = row.get(col)
            if isinstance(raw, str) and is_number(parse_cell_value(raw)[0]):
                count += 1
    return count


def eval_table_valid_rate(payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
    tables = [
        p for p in payloads
        if p.get("element_type") == ElementType.TABLE.value
        and p.get("review_status") != ReviewStatus.REJECTED.value
    ]
    reasons: Dict[str, int] = defaultdict(int)
    invalid_ids: List[str] = []
    valid = 0
    # 저장 규칙(glossary 9절) 위반 규모: pipeline_version별로 센다
    by_version: Dict[str, Dict[str, int]] = defaultdict(lambda: {"tables": 0, "violating_tables": 0, "violating_cells": 0})
    for p in tables:
        ok, reason = table_is_valid(p.get("table_data"))
        if ok:
            valid += 1
        else:
            reasons[reason.split(":")[0]] += 1
            invalid_ids.append(p.get("element_id") or "")
        stats = by_version[str(p.get("pipeline_version") or "없음")]
        stats["tables"] += 1
        violations = count_rule_violations(p.get("table_data"))
        if violations:
            stats["violating_tables"] += 1
            stats["violating_cells"] += violations
    return {
        "table_valid_rate": valid / len(tables) if tables else 0.0,
        "table_count": len(tables),
        "valid_count": valid,
        "invalid_reasons": dict(reasons),
        "invalid_element_ids": invalid_ids,
        "rule_violation_tables": sum(v["violating_tables"] for v in by_version.values()),
        "rule_violation_by_version": dict(sorted(by_version.items())),
    }


# ---------------------------------------------------------------------------
# cell_accuracy
# ---------------------------------------------------------------------------

def load_gt_tables(path: Path) -> Dict[str, Dict[str, Any]]:
    """표 ID → {doc_name, page_number} (연결 검증용)."""
    tables: Dict[str, Dict[str, Any]] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tables.setdefault(row["table_id"], {"doc_name": row["doc_name"], "page_number": int(row["page_number"])})
    return tables


def load_gt_cells(path: Path) -> Dict[str, List[Dict[str, Any]]]:
    """표 ID → 숫자 셀 목록. 숫자가 아닌 정답 셀은 뺀다."""
    by_table: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            value, _ = parse_cell_value(row["value"])
            if not is_number(value):
                continue
            by_table[row["table_id"]].append(
                {"row_label": row["row_label"], "column": row["column"], "expected": value}
            )
    return by_table


def load_links(path: Path) -> Dict[str, Dict[str, str]]:
    links: Dict[str, Dict[str, str]] = {}
    if not path.exists():
        return links
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("table_id") and (row.get("element_id") or row.get("link_status")):
                links[row["table_id"]] = row
    return links


def index_ai_table(table_data: Dict[str, Any]) -> Dict[Tuple[str, str], List[Any]]:
    """(행 라벨, 열 이름) → 값 목록 (같은 라벨이 여러 번이면 나온 순서대로)."""
    index: Dict[Tuple[str, str], List[Any]] = defaultdict(list)
    columns = [str(c) for c in (table_data.get("columns") or [])]
    if not columns:
        return index
    label_col = columns[0]
    for row in table_data.get("rows") or []:
        if not isinstance(row, dict):
            continue
        label = norm_label(row.get(label_col))
        for col in columns[1:]:
            index[(label, norm_label(col))].append(row.get(col))
    return index


def score_table(gt_cells: List[Dict[str, Any]], table_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """정답 셀마다 결과를 돌려준다. result: 맞음 / 행·열 바뀜 맞음 / 값 다름 / 칸 없음"""
    index = index_ai_table(table_data)
    used: Dict[Tuple[str, str], int] = defaultdict(int)
    results = []
    for cell in gt_cells:
        row_key, col_key = norm_label(cell["row_label"]), norm_label(cell["column"])
        key, transposed = (row_key, col_key), False
        if key not in index:
            key, transposed = (col_key, row_key), True
        values = index.get(key) or []
        n = used[key]
        used[key] += 1
        raw = values[n] if n < len(values) else None
        actual, _ = parse_cell_value(raw)
        if n >= len(values):
            result = "칸 없음"
        elif is_number(actual) and same_number(actual, cell["expected"]):
            result = "행·열 바뀜 맞음" if transposed else "맞음"
        else:
            result = "값 다름"
        results.append({**cell, "actual": raw, "result": result,
                        "rule_violation": isinstance(raw, str) and is_number(actual)})
    return results


def eval_cell_accuracy(gt: Dict[str, List[Dict[str, Any]]], links: Dict[str, Dict[str, str]],
                       payload_by_id: Dict[str, Dict[str, Any]],
                       gt_tables: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    per_table = []
    detail = []
    total = correct = transposed = violations = 0
    extracted_tables = extracted_cells = extracted_correct = 0
    gt_tables = gt_tables or {}
    for table_id in sorted(gt):
        cells = gt[table_id]
        link = links.get(table_id)
        if not link:
            per_table.append({"table_id": table_id, "state": "미연결", "cells": len(cells)})
            continue
        element_id = (link.get("element_id") or "").strip()
        payload = payload_by_id.get(element_id)
        if link.get("link_status") not in SCORABLE_LINKS:
            state = f"판정: {link.get('link_status') or '없음'}"
            scored = [{**c, "actual": None, "result": "칸 없음", "rule_violation": False} for c in cells]
        elif payload is None:
            state = "요소가 컬렉션에 없음"
            scored = [{**c, "actual": None, "result": "칸 없음", "rule_violation": False} for c in cells]
        elif payload.get("review_status") == ReviewStatus.REJECTED.value:
            state = "반려된 요소"
            scored = [{**c, "actual": None, "result": "칸 없음", "rule_violation": False} for c in cells]
        elif table_id in gt_tables and (
                payload.get("doc_name") != gt_tables[table_id]["doc_name"]
                or payload.get("page_number") != gt_tables[table_id]["page_number"]):
            state = f"연결 오류 (요소는 {payload.get('doc_name')} p.{payload.get('page_number')})"
            scored = [{**c, "actual": None, "result": "칸 없음", "rule_violation": False} for c in cells]
        else:
            state = "채점"
            scored = score_table(cells, payload.get("table_data") or {})

        ok = sum(1 for s in scored if s["result"] in ("맞음", "행·열 바뀜 맞음"))
        tr = sum(1 for s in scored if s["result"] == "행·열 바뀜 맞음")
        rv = sum(1 for s in scored if s["rule_violation"])
        total += len(scored)
        correct += ok
        if state == "채점":
            extracted_tables += 1
            extracted_cells += len(scored)
            extracted_correct += ok
        transposed += tr
        violations += rv
        per_table.append({"table_id": table_id, "element_id": element_id, "state": state,
                          "cells": len(scored), "correct": ok, "transposed_cells": tr,
                          "rule_violation_cells": rv,
                          "cell_accuracy": ok / len(scored) if scored else 0.0})
        for s in scored:
            detail.append({"table_id": table_id, "element_id": element_id, "row_label": s["row_label"],
                           "column": s["column"], "expected": s["expected"], "actual": s["actual"],
                           "result": s["result"]})
    return {
        "cell_accuracy": correct / total if total else None,
        "gt_table_coverage": extracted_tables / len(per_table) if per_table else None,
        "cell_accuracy_extracted": extracted_correct / extracted_cells if extracted_cells else None,
        "extracted_tables": extracted_tables,
        "extracted_cells": extracted_cells,
        "extracted_correct": extracted_correct,
        "scored_cells": total,
        "correct_cells": correct,
        "transposed_cells": transposed,
        "rule_violation_cells": violations,
        "linked_tables": sum(1 for t in per_table if t["state"] != "미연결"),
        "total_tables": len(per_table),
        "per_table": per_table,
        "detail": detail,
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"))
    ap.add_argument("--collection", default=os.getenv("QDRANT_COLLECTION", "figindex_elements_v2"))
    ap.add_argument("--cells", default=str(GT_DIR / "cells.csv"))
    ap.add_argument("--links", default=str(GT_DIR / "links.csv"))
    ap.add_argument("--out", help="결과 JSON 저장 경로")
    ap.add_argument("--detail", help="셀별 채점 CSV 저장 경로 (엑셀용 UTF-8 BOM)")
    args = ap.parse_args()

    payloads = scroll_all(args.qdrant_url, args.collection)
    if not payloads:
        sys.exit(f"컬렉션 {args.collection}에서 읽은 요소가 없습니다. Qdrant가 켜져 있는지 확인해 주세요.")
    payload_by_id = {p.get("element_id"): p for p in payloads if p.get("element_id")}

    valid = eval_table_valid_rate(payloads)
    cells = eval_cell_accuracy(load_gt_cells(Path(args.cells)), load_links(Path(args.links)), payload_by_id,
                               load_gt_tables(Path(args.cells)))

    print(f"[table_valid_rate] {valid['valid_count']}/{valid['table_count']} = {valid['table_valid_rate']:.3f} (목표 ≥ 0.90)")
    for reason, n in sorted(valid["invalid_reasons"].items(), key=lambda x: -x[1]):
        print(f"  실패 {n}건: {reason}")
    if valid["invalid_element_ids"]:
        print(f"  실패 요소: {', '.join(valid['invalid_element_ids'])}")
    print(f"\n[저장 규칙 위반] 숫자를 문자열로 저장한 표 {valid['rule_violation_tables']}/{valid['table_count']}개"
          " (table_valid_rate는 이 표들도 통과로 셈)")
    for version, v in valid["rule_violation_by_version"].items():
        print(f"  pipeline_version {version}: 표 {v['violating_tables']}/{v['tables']}개, 칸 {v['violating_cells']}개")

    print(f"\n[cell_accuracy] 연결된 표 {cells['linked_tables']}/{cells['total_tables']}개")
    for t in cells["per_table"]:
        if t["state"] == "미연결":
            continue
        print(f"  {t['table_id']} {t['element_id'] or '-'}  {t['correct']}/{t['cells']}  {t['state']}"
              + (f"  (행·열 바뀜 {t['transposed_cells']})" if t["transposed_cells"] else "")
              + (f"  (규칙 미적용 칸 {t['rule_violation_cells']})" if t["rule_violation_cells"] else ""))
    if cells["cell_accuracy"] is None:
        print("  채점할 셀이 없습니다 (links.csv에 연결된 표가 없음).")
    else:
        print(f"  cell_accuracy = {cells['correct_cells']}/{cells['scored_cells']} = {cells['cell_accuracy']:.3f} (목표 ≥ 0.95, 카드 없는 표 포함)")
        print(f"  ├ gt_table_coverage = {cells['extracted_tables']}/{cells['total_tables']} = {cells['gt_table_coverage']:.3f} (카드가 있는 정답 표 비율)")
        if cells["cell_accuracy_extracted"] is not None:
            print(f"  └ cell_accuracy_extracted = {cells['extracted_correct']}/{cells['extracted_cells']} = "
                  f"{cells['cell_accuracy_extracted']:.3f} (카드가 있는 표 {cells['extracted_tables']}개만)")
        print(f"  규칙 미적용 칸 (쉼표·% 붙은 문자열로 저장됨): {cells['rule_violation_cells']}")
    unlinked = [t["table_id"] for t in cells["per_table"] if t["state"] == "미연결"]
    if unlinked:
        print(f"  미연결 표 {len(unlinked)}개: {', '.join(unlinked)}")

    if args.out:
        result = {**valid, **{k: v for k, v in cells.items() if k != "detail"}}
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.detail:
        with open(args.detail, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=DETAIL_COLUMNS)
            w.writeheader()
            w.writerows(cells["detail"])


if __name__ == "__main__":
    main()
