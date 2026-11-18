#!/usr/bin/env python3
"""
scripts/verify_compare_numbers.py: 비교 매트릭스 표 숫자 정확도 검증 스크립트.

기능:
1. data/compare_matrix.json의 MATCHED 표(69건)를 대상으로 각 표의 원본 PDF bbox 영역 텍스트 추출.
2. table_data의 모든 숫자 셀을 정규화하여 bbox 글자 내 존재 여부 검증.
3. 표별, 지표별, vision_model별 일치율 및 90% 미만 목록 출력.
4. 사람이 확인할 검수용 시트 data/eval/compare_numbers_check.csv 생성.
5. 크롭 이미지와 검증 결과를 나란히 보여주는 data/eval/compare_numbers_check.html 생성.
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# figindex 모듈 import 설정
_CURRENT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _CURRENT_DIR.parent
_FIGINDEX_DIR = _REPO_ROOT / "figindex"
if str(_FIGINDEX_DIR) not in sys.path:
    sys.path.insert(0, str(_FIGINDEX_DIR))

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

from pipeline.pdf_text import has_text_layer, read_text_in_bbox

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def scroll_all_qdrant_points(qdrant_url: str, collection: str) -> Dict[str, Dict[str, Any]]:
    """Qdrant에서 모든 포인트를 조회하여 element_id -> payload 매핑 딕셔너리를 반환합니다."""
    scroll_url = f"{qdrant_url.rstrip('/')}/collections/{collection}/points/scroll"
    el_map: Dict[str, Dict[str, Any]] = {}
    next_offset: Optional[Any] = None

    while True:
        body: Dict[str, Any] = {
            "limit": 100,
            "with_payload": True,
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
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            logger.error(f"Qdrant 조회 실패 ({scroll_url}): {e}")
            sys.exit(1)

        result = data.get("result", {})
        points = result.get("points", [])
        for p in points:
            payload = p.get("payload", {})
            eid = payload.get("element_id")
            if eid:
                el_map[eid] = payload

        next_offset = result.get("next_page_offset")
        if not next_offset:
            break

    return el_map


def normalize_cell_value(val: Any) -> Optional[str]:
    """표 셀의 값을 정규화(쉼표 제거, 괄호는 음수, %·단위 기호 제거)하여 숫자 문자열로 반환합니다.
    숫자가 아니거나 빈 값이면 None을 반환합니다.
    """
    if val is None:
        return None
    s = str(val).strip()
    if not s or s in ["-", "—", "―", "N/A", "NA", "null", "None"]:
        return None
    # 한글 설명이나 텍스트가 포함된 경우 숫자 셀이 아님
    if re.search(r"[가-힣]", s):
        return None

    # 괄호 형태 음수: (1,090) -> -1090
    m = re.match(r"^\((.*)\)$", s)
    is_neg = False
    if m:
        is_neg = True
        s = m.group(1).strip()
    elif s.startswith("△") or s.startswith("▼"):
        is_neg = True
        s = s[1:].strip()
    elif s.startswith("▲"):
        s = s[1:].strip()
    elif s.startswith("-"):
        is_neg = True
        s = s[1:].strip()
    elif s.startswith("+"):
        s = s[1:].strip()

    # 쉼표 및 공백 제거
    s = s.replace(",", "").replace(" ", "")

    # 단위 및 기호 제거
    s = re.sub(r"(?:%[pP]?|[pP]|원|배|[xX]|pt)$", "", s).strip()

    # 유효한 정수 또는 실수인지 확인
    if not re.fullmatch(r"^\d+(?:\.\d+)?$", s):
        return None

    if is_neg and float(s) != 0.0:
        return f"-{s}"
    return s


def normalize_text_numbers(text: str) -> str:
    """PDF에서 추출한 bbox 텍스트를 동일한 규칙으로 정규화합니다."""
    t = text
    # (1,090) -> -1090
    t = re.sub(r"\(\s*([0-9,]+(?:\.[0-9]+)?)\s*\)", r" -\1 ", t)
    # △1090, ▼1090 -> -1090
    t = re.sub(r"[△▼]\s*([0-9,]+(?:\.[0-9]+)?)", r" -\1 ", t)
    # ▲1090 -> 1090
    t = re.sub(r"[▲]\s*([0-9,]+(?:\.[0-9]+)?)", r" \1 ", t)
    # 숫자 사이 쉼표 제거 (1,090 -> 1090)
    t = re.sub(r"(\d),(\d)", r"\1\2", t)
    # 숫자 뒤 붙은 단위/기호 분리 제거
    t = re.sub(r"(\d)(?:%[pP]?|[pP]|원|배|[xX]|pt)", r"\1 ", t)
    return t


def check_number_in_text(num_str: str, norm_text: str) -> bool:
    """정규화된 숫자가 bbox 텍스트 안에 온전한 숫자로 존재하는지 경계(boundary) 매칭합니다."""
    # 1. 원본 숫자 패턴
    patterns = [re.escape(num_str)]
    # 2. 정수 <-> 실수 (.0) 상호 호환 (예: 1090 <-> 1090.0)
    if num_str.endswith(".0"):
        patterns.append(re.escape(num_str[:-2]))
    elif "." not in num_str:
        patterns.append(re.escape(num_str + ".0"))

    for pat in patterns:
        regex = rf"(?<![\d\.]){pat}(?![\d\.])"
        if re.search(regex, norm_text):
            return True
    return False


def find_2026_col(cols: List[str]) -> Optional[str]:
    """주어진 열 목록에서 2026E(또는 2026F)에 해당하는 가장 적절한 열 이름을 선택합니다."""
    if not cols or len(cols) < 2:
        return None
    data_cols = cols[1:]
    candidates = []
    # 차이, diff, YoY, 증감, 기존, 변경 전 열 제외
    for c in data_cols:
        if "2026" in c and not any(x in c for x in ["차이", "diff", "YoY", "yoy", "변화율", "QoQ", "기존", "변경 전", "변경전"]):
            candidates.append(c)
    if not candidates:
        candidates = [c for c in data_cols if "2026" in c]

    # 신규/변경 후 우선
    for c in candidates:
        if any(x in c for x in ["신규", "변경 후", "변경후"]):
            return c
    for c in candidates:
        if c in ["2026E", "2026F"]:
            return c
    return candidates[0] if candidates else None


def extract_sales_and_op_profit(rows: List[Dict[str, Any]], col0: str, col_target: str) -> Tuple[Optional[Tuple[str, str]], Optional[Tuple[str, str]]]:
    """행 목록에서 매출액(영업수익)과 영업이익의 (행 라벨, 시스템값)을 추출합니다."""
    sales_info = None
    op_info = None

    # 1. 매출액 / 영업수익 탐색 (우선순위: 완전 일치)
    for r in rows:
        lbl = str(r.get(col0, "")).strip()
        if lbl in ["매출액", "영업수익", "매출액(십억원)", "매출액 (십억원)", "매출액 (억원)", "매출액(억원)"]:
            val = r.get(col_target)
            if val is not None:
                sales_info = (lbl, str(val))
                break
    if sales_info is None:
        for r in rows:
            lbl = str(r.get(col0, "")).strip()
            if (lbl.startswith("매출액") or lbl.startswith("영업수익")) and not any(x in lbl for x in ["률", "YoY", "yoy", "원가", "총이익", "별도", "해외", "국내", "-", "증감", "QoQ"]):
                val = r.get(col_target)
                if val is not None:
                    sales_info = (lbl, str(val))
                    break

    # 2. 영업이익 탐색 (우선순위: 완전 일치)
    for r in rows:
        lbl = str(r.get(col0, "")).strip()
        if lbl in ["영업이익", "영업이익(십억원)", "영업이익 (십억원)", "영업이익 (억원)", "영업이익(억원)"]:
            val = r.get(col_target)
            if val is not None:
                op_info = (lbl, str(val))
                break
    if op_info is None:
        for r in rows:
            lbl = str(r.get(col0, "")).strip()
            if lbl.startswith("영업이익") and not any(x in lbl for x in ["률", "YoY", "yoy", "별도", "해외", "국내", "-", "증감", "외", "QoQ"]):
                val = r.get(col_target)
                if val is not None:
                    op_info = (lbl, str(val))
                    break

    return sales_info, op_info


def main():
    parser = argparse.ArgumentParser(description="비교 매트릭스 표 숫자 정확도 검증")
    parser.add_argument("--matrix", default="data/compare_matrix.json", help="compare_matrix.json 경로")
    parser.add_argument("--qdrant-url", default="http://localhost:6333", help="Qdrant URL")
    parser.add_argument("--collection", default="figindex_elements_v2", help="Qdrant 컬렉션 이름")
    parser.add_argument("--csv-out", default="data/eval/compare_numbers_check.csv", help="검수용 CSV 출력 경로")
    parser.add_argument("--html-out", default="data/eval/compare_numbers_check.html", help="검수용 HTML 출력 경로")
    args = parser.parse_args()

    if fitz is None:
        print("[Error] PyMuPDF(fitz) 라이브러리가 필요합니다. pip install pymupdf 를 실행하십시오.")
        sys.exit(1)

    matrix_path = _REPO_ROOT / args.matrix
    if not matrix_path.exists():
        print(f"[Error] 매트릭스 파일이 없습니다: {matrix_path}")
        sys.exit(1)

    with open(matrix_path, "r", encoding="utf-8") as f:
        matrix_data = json.load(f)

    # Qdrant 포인트 로드
    logger.info(f"Qdrant 컬렉션 '{args.collection}' 조회 중...")
    el_map = scroll_all_qdrant_points(args.qdrant_url, args.collection)
    logger.info(f"Qdrant 요소 매핑 완료 (총 {len(el_map)}개 요소)")

    # 1. 대상 MATCHED 표 수집
    matched_items = []
    for group in matrix_data:
        comp = group.get("company")
        metric = group.get("metric")
        for doc in group.get("documents", []):
            if doc.get("matched"):
                matched_items.append((comp, metric, doc))

    logger.info(f"검증 대상 MATCHED 표: {len(matched_items)}건")

    # 캐시된 PDF 문서 객체
    pdf_cache: Dict[str, Any] = {}

    table_results = []
    metric_stats = defaultdict(lambda: {"matched": 0, "total": 0, "tables": 0, "rates": []})
    vision_stats = defaultdict(lambda: {"matched": 0, "total": 0, "tables": 0, "rates": []})

    csv_rows = []
    target_groups_5 = ["카카오", "KTnG", "SK텔레콤", "삼양식품", "코스맥스"]

    for comp, metric, doc in matched_items:
        eid = doc.get("element_id")
        doc_name = doc.get("doc_name")
        page_num = doc.get("page_number", 1)
        caption = doc.get("caption", "")
        source_org = doc.get("source_org", "")

        q_info = el_map.get(eid, {})
        bbox = q_info.get("bbox")
        image_path = q_info.get("image_path") or f"/static/crops/{eid}_p{page_num}.png"
        vmodel = q_info.get("extra_metadata", {}).get("vision_model")
        if not vmodel:
            vmodel = "unknown"

        # PDF 파일 경로
        pdf_path = _REPO_ROOT / "figindex" / "data" / "pdfs" / doc_name
        if not pdf_path.exists():
            pdf_path = _REPO_ROOT / "data" / "pdfs" / doc_name

        if str(pdf_path) not in pdf_cache:
            if pdf_path.exists():
                pdf_cache[str(pdf_path)] = fitz.open(str(pdf_path))
            else:
                pdf_cache[str(pdf_path)] = None

        fitz_doc = pdf_cache[str(pdf_path)]
        if fitz_doc is None:
            logger.warning(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")
            continue

        page = fitz_doc[page_num - 1]
        has_text = has_text_layer(page)

        td = doc.get("table_data") or {}
        cols = td.get("columns", [])
        rows = td.get("rows", [])

        if not has_text:
            # 텍스트 레이어 없음 (스캔본 등)
            total_cells = sum(
                1 for r in rows for c in cols[1:] if normalize_cell_value(r.get(c)) is not None
            )
            t_res = {
                "comp": comp,
                "org": source_org,
                "metric": metric,
                "doc_name": doc_name,
                "page": page_num,
                "caption": caption,
                "vmodel": vmodel,
                "image_path": image_path,
                "has_text": False,
                "matched_cnt": 0,
                "total_cnt": total_cells,
                "rate": 0.0,
            }
            table_results.append(t_res)
            metric_stats[metric]["tables"] += 1
            metric_stats[metric]["total"] += total_cells
            metric_stats[metric]["rates"].append(0.0)
            vision_stats[vmodel]["tables"] += 1
            vision_stats[vmodel]["total"] += total_cells
            vision_stats[vmodel]["rates"].append(0.0)
            continue

        raw_bbox_text = read_text_in_bbox(page, bbox)
        norm_bbox_text = normalize_text_numbers(raw_bbox_text)

        total_cells = 0
        matched_cells = 0

        for r in rows:
            for c in cols[1:]:
                val = r.get(c)
                norm_num = normalize_cell_value(val)
                if norm_num is not None:
                    total_cells += 1
                    if check_number_in_text(norm_num, norm_bbox_text):
                        matched_cells += 1

        rate = (matched_cells / total_cells * 100.0) if total_cells > 0 else 100.0
        t_res = {
            "comp": comp,
            "org": source_org,
            "metric": metric,
            "doc_name": doc_name,
            "page": page_num,
            "caption": caption,
            "vmodel": vmodel,
            "image_path": image_path,
            "has_text": True,
            "matched_cnt": matched_cells,
            "total_cnt": total_cells,
            "rate": rate,
        }
        table_results.append(t_res)

        metric_stats[metric]["tables"] += 1
        metric_stats[metric]["matched"] += matched_cells
        metric_stats[metric]["total"] += total_cells
        metric_stats[metric]["rates"].append(rate)

        vision_stats[vmodel]["tables"] += 1
        vision_stats[vmodel]["matched"] += matched_cells
        vision_stats[vmodel]["total"] += total_cells
        vision_stats[vmodel]["rates"].append(rate)

        # 5개 그룹 ANNUAL_ESTIMATE 검수 시트 추출
        if metric == "ANNUAL_ESTIMATE" and comp in target_groups_5:
            col_2026 = find_2026_col(cols)
            if col_2026:
                col0 = cols[0] if cols else ""
                sales_info, op_info = extract_sales_and_op_profit(rows, col0, col_2026)

                # 매출액 / 영업수익 행
                if sales_info:
                    s_label, s_val = sales_info
                    s_norm = normalize_cell_value(s_val)
                    in_pdf = "Y" if (s_norm and check_number_in_text(s_norm, norm_bbox_text)) else "N"
                    csv_rows.append({
                        "종목": comp,
                        "증권사": source_org,
                        "행": "매출액" if "매출" in s_label else "영업수익",
                        "기간": "2026E",
                        "시스템값": s_val,
                        "PDF글자에 존재 여부": in_pdf,
                        "페이지": page_num,
                        "크롭 경로": image_path,
                        "정답값": "",
                        "비고": "",
                    })

                # 영업이익 행
                if op_info:
                    op_label, op_val = op_info
                    op_norm = normalize_cell_value(op_val)
                    in_pdf = "Y" if (op_norm and check_number_in_text(op_norm, norm_bbox_text)) else "N"
                    csv_rows.append({
                        "종목": comp,
                        "증권사": source_org,
                        "행": "영업이익",
                        "기간": "2026E",
                        "시스템값": op_val,
                        "PDF글자에 존재 여부": in_pdf,
                        "페이지": page_num,
                        "크롭 경로": image_path,
                        "정답값": "",
                        "비고": "",
                    })

    # CSV 파일 작성 (data/eval/compare_numbers_check.csv)
    csv_out_path = _REPO_ROOT / args.csv_out
    csv_out_path.parent.mkdir(parents=True, exist_ok=True)
    csv_fieldnames = [
        "종목", "증권사", "행", "기간", "시스템값",
        "PDF글자에 존재 여부", "페이지", "크롭 경로", "정답값", "비고"
    ]
    with open(csv_out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fieldnames)
        writer.writeheader()
        for r in csv_rows:
            writer.writerow(r)

    # HTML 파일 작성 (data/eval/compare_numbers_check.html)
    html_out_path = _REPO_ROOT / args.html_out
    html_out_path.parent.mkdir(parents=True, exist_ok=True)
    generate_html(csv_rows, html_out_path)

    # 콘솔 출력
    print("=" * 80)
    print("           비교 매트릭스 표 숫자 정확도 검증 보고서 (MATCHED 69건)")
    print("=" * 80)

    # 1. 표별 숫자 일치율 및 전체 평균
    print("\n[1] 표별 숫자 일치율 (일부 요약)")
    print("-" * 80)
    for idx, r in enumerate(table_results, 1):
        status_txt = f"{r['rate']:.1f}% ({r['matched_cnt']}/{r['total_cnt']})" if r["has_text"] else "텍스트 없음"
        # 터미널 가독성을 위해 일부 축약
        print(f"[{idx:02d}/69] {r['comp']:8s} | {r['org']:8s} | {r['metric']:16s} | p.{r['page']:02d} | 일치율: {status_txt:>12s} | {r['caption'][:28]}")

    all_rates = [r["rate"] for r in table_results if r["has_text"]]
    total_matched_sum = sum(r["matched_cnt"] for r in table_results)
    total_cells_sum = sum(r["total_cnt"] for r in table_results)
    overall_avg = (sum(all_rates) / len(all_rates)) if all_rates else 0.0

    print("-" * 80)
    print(f"▶ 전체 평균 일치율: {overall_avg:.2f}% (총 {len(table_results)}개 표 중 {len(all_rates)}개 텍스트 검증, 총 {total_matched_sum}/{total_cells_sum} 숫자 일치)")

    # 2. 지표별 평균 일치율
    print("\n[2] 지표별 평균 일치율")
    print("-" * 80)
    for m in ["TARGET_PRICE", "ANNUAL_ESTIMATE", "QUARTERLY_RESULT"]:
        m_info = metric_stats.get(m, {"rates": [], "matched": 0, "total": 0, "tables": 0})
        m_rates = m_info["rates"]
        m_avg = (sum(m_rates) / len(m_rates)) if m_rates else 0.0
        print(f" - {m:<18s}: {m_avg:6.2f}% (표 {m_info['tables']:2d}건, 숫자 {m_info['matched']}/{m_info['total']})")

    # 3. vision_model별 평균 일치율
    print("\n[3] extra_metadata.vision_model별 평균 일치율")
    print("-" * 80)
    for vm, v_info in vision_stats.items():
        v_rates = v_info["rates"]
        v_avg = (sum(v_rates) / len(v_rates)) if v_rates else 0.0
        print(f" - {vm:<18s}: {v_avg:6.2f}% (표 {v_info['tables']:2d}건, 숫자 {v_info['matched']}/{v_info['total']})")

    # 4. 일치율 90% 미만인 표 목록
    low_rate_tables = [r for r in table_results if r["rate"] < 90.0]
    print("\n[4] 일치율 90% 미만 표 목록")
    print("-" * 80)
    if not low_rate_tables:
        print("  ▶ 없음 (모든 표의 일치율이 90% 이상입니다.)")
    else:
        for lr in low_rate_tables:
            print(f"  - 종목: {lr['comp']} | 증권사: {lr['org']} | 지표: {lr['metric']} | 일치율: {lr['rate']:.1f}% ({lr['matched_cnt']}/{lr['total_cnt']}) | 캡션: {lr['caption']} | 크롭: {lr['image_path']}")

    # 5. 검수 시트 생성 결과 요약
    print("\n[5] 검수 파일 생성 결과")
    print("-" * 80)
    print(f"  - CSV : {csv_out_path.resolve()} ({len(csv_rows)}건)")
    print(f"  - HTML: {html_out_path.resolve()}")
    print("=" * 80)


def generate_html(rows: List[Dict[str, Any]], out_path: Path):
    """검수용 인터랙티브 HTML 보고서를 생성합니다."""
    # 통계
    total = len(rows)
    y_cnt = sum(1 for r in rows if r.get("PDF글자에 존재 여부") == "Y")
    n_cnt = total - y_cnt
    y_pct = (y_cnt / total * 100.0) if total > 0 else 0.0

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>비교 매트릭스 숫자 검증 시트 (ANNUAL_ESTIMATE 2026E)</title>
<style>
  :root {{
    --bg: #f8fafc;
    --card-bg: #ffffff;
    --text-primary: #0f172a;
    --text-secondary: #475569;
    --border: #e2e8f0;
    --primary: #2563eb;
    --success: #16a34a;
    --danger: #dc2626;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    background-color: var(--bg);
    color: var(--text-primary);
    margin: 0;
    padding: 24px;
  }}
  .container {{
    max-width: 1400px;
    margin: 0 auto;
  }}
  h1 {{
    font-size: 24px;
    font-weight: 700;
    margin-bottom: 8px;
    color: var(--text-primary);
  }}
  .subtitle {{
    font-size: 14px;
    color: var(--text-secondary);
    margin-bottom: 24px;
  }}
  .kpi-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }}
  .kpi-card {{
    background: var(--card-bg);
    padding: 16px 20px;
    border-radius: 8px;
    border: 1px solid var(--border);
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
  }}
  .kpi-title {{
    font-size: 13px;
    color: var(--text-secondary);
    margin-bottom: 6px;
    font-weight: 500;
  }}
  .kpi-value {{
    font-size: 28px;
    font-weight: 700;
  }}
  .kpi-value.green {{ color: var(--success); }}
  .kpi-value.blue {{ color: var(--primary); }}
  .table-card {{
    background: var(--card-bg);
    border-radius: 8px;
    border: 1px solid var(--border);
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
    text-align: left;
  }}
  th {{
    background: #f1f5f9;
    padding: 12px 14px;
    font-weight: 600;
    color: var(--text-secondary);
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }}
  td {{
    padding: 12px 14px;
    border-bottom: 1px solid var(--border);
    vertical-align: middle;
  }}
  tr:hover {{
    background-color: #f8fafc;
  }}
  .badge {{
    display: inline-block;
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    text-align: center;
  }}
  .badge.y {{
    background-color: #dcfce7;
    color: #15803d;
  }}
  .badge.n {{
    background-color: #fee2e2;
    color: #b91c1c;
  }}
  .crop-preview {{
    position: relative;
    display: inline-block;
  }}
  .crop-img {{
    max-width: 260px;
    max-height: 120px;
    border-radius: 4px;
    border: 1px solid var(--border);
    cursor: pointer;
    transition: transform 0.2s;
  }}
  .crop-img:hover {{
    transform: scale(2.2);
    z-index: 999;
    position: relative;
    box-shadow: 0 8px 24px rgba(0,0,0,0.25);
  }}
  .input-box {{
    width: 90%;
    padding: 6px 8px;
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: 13px;
  }}
  .sys-val {{
    font-family: monospace;
    font-weight: 600;
    font-size: 15px;
    color: #1e293b;
  }}
</style>
</head>
<body>
<div class="container">
  <h1>비교 매트릭스 숫자 검증 시트</h1>
  <div class="subtitle">대상: 5개 동일 날짜 그룹 (카카오, KTnG, SK텔레콤, 삼양식품, 코스맥스) ANNUAL_ESTIMATE 2026E 매출액·영업이익</div>

  <div class="kpi-row">
    <div class="kpi-card">
      <div class="kpi-title">총 검수 항목</div>
      <div class="kpi-value blue">{total}개</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-title">PDF 텍스트 일치 건수</div>
      <div class="kpi-value green">{y_cnt}개</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-title">일치율</div>
      <div class="kpi-value green">{y_pct:.1f}%</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-title">불일치 건수</div>
      <div class="kpi-value">{n_cnt}개</div>
    </div>
  </div>

  <div class="table-card">
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>종목</th>
          <th>증권사</th>
          <th>행</th>
          <th>기간</th>
          <th>시스템 추출값</th>
          <th>PDF 존재 여부</th>
          <th>페이지</th>
          <th>크롭 이미지 (마우스 오버시 확대)</th>
          <th style="min-width: 110px;">정답값 확인</th>
          <th style="min-width: 140px;">비고</th>
        </tr>
      </thead>
      <tbody>
"""
    for idx, r in enumerate(rows, 1):
        badge_cls = "y" if r["PDF글자에 존재 여부"] == "Y" else "n"
        badge_txt = "존재 (Y)" if r["PDF글자에 존재 여부"] == "Y" else "미존재 (N)"
        crop_path = r["크롭 경로"]
        # 상대 경로 계산: data/eval/ -> ../../figindex/data/crops/...
        crop_filename = Path(crop_path).name
        local_rel_img = f"../../figindex/data/crops/{crop_filename}"

        html += f"""        <tr>
          <td>{idx}</td>
          <td><strong>{r['종목']}</strong></td>
          <td>{r['증권사']}</td>
          <td><span style="font-weight: 500;">{r['행']}</span></td>
          <td><span style="color: #64748b;">{r['기간']}</span></td>
          <td><span class="sys-val">{r['시스템값']}</span></td>
          <td><span class="badge {badge_cls}">{badge_txt}</span></td>
          <td>p.{r['페이지']}</td>
          <td>
            <div class="crop-preview">
              <img class="crop-img" src="{local_rel_img}" alt="{r['행']}" loading="lazy" onerror="this.onerror=null; this.src='{crop_path}';">
            </div>
          </td>
          <td><input type="text" class="input-box" placeholder="정답값 입력"></td>
          <td><input type="text" class="input-box" placeholder="메모 입력"></td>
        </tr>
"""

    html += """      </tbody>
    </table>
  </div>
</div>
</body>
</html>
"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    main()
