#!/usr/bin/env python3
"""
check_extraction.py: Qdrant scroll을 끝까지 페이징하여 저장된 115개 전체 문서별
도표 수, TABLE 수, source_org, publish_date, entities(종목명)를 표로 검사·출력하는 스크립트.

검사 규칙 (⚠ 표시 대상):
1. publish_date가 파일명 날짜와 다른 경우
2. source_org가 파일명의 증권사/출처와 다른 경우
3. 파일명의 종목명이 entities에 없는 경우
4. TABLE 수가 0개인 경우

사용법:
    python scripts/check_extraction.py
    python scripts/check_extraction.py --collection figindex_elements_v2
    python scripts/check_extraction.py --rpt-only
"""

import argparse
import json
import logging
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# shared.schemas import를 위해 sys.path 설정
_CURRENT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _CURRENT_DIR.parent
_FIGINDEX_DIR = _REPO_ROOT / "figindex"
if str(_FIGINDEX_DIR) not in sys.path:
    sys.path.insert(0, str(_FIGINDEX_DIR))

from shared.schemas import ElementType

logger = logging.getLogger(__name__)

# 증권사 정규화 사전 (orchestrator.py 기준 정식 명칭 매핑)
BROKER_ALIASES: Dict[str, str] = {
    "IBK투자증권": "IBK투자증권",
    "미래에셋증권": "미래에셋증권",
    "신한투자증권": "신한투자증권",
    "키움증권": "키움증권",
    "하나증권": "하나증권",
    "대신증권": "대신증권",
    "KB증권": "KB증권",
    "삼성증권": "삼성증권",
    "NH투자증권": "NH투자증권",
    "유안타증권": "유안타증권",
    "한국투자증권": "한국투자증권",
    "메리츠증권": "메리츠증권",
    "교보증권": "교보증권",
    "현대차증권": "현대차증권",
    "한화투자증권": "한화투자증권",
    "SK증권": "SK증권",
    "유진투자증권": "유진투자증권",
    "DB증권": "DB증권",
    "iM증권": "iM증권",
    "다올투자증권": "다올투자증권",
    "LS증권": "LS증권",
    "상상인증권": "상상인증권",
    "신영증권": "신영증권",
    "DS투자증권": "DS투자증권",
    "BNK투자증권": "BNK투자증권",
    "한양증권": "한양증권",
    "부국증권": "부국증권",
    "흥국증권": "흥국증권",
    "케이프투자증권": "케이프투자증권",
    "리딩투자증권": "리딩투자증권",
    "DB금융투자": "DB증권",
    "동부증권": "DB증권",
    "하이투자증권": "iM증권",
    "신한금융투자": "신한투자증권",
    "하나금융투자": "하나증권",
    "하나대투증권": "하나증권",
    "미래에셋대우": "미래에셋증권",
    "대우증권": "미래에셋증권",
    "현대증권": "KB증권",
    "KB투자증권": "KB증권",
    "KTB투자증권": "다올투자증권",
    "이베스트투자증권": "LS증권",
    "이베스트증권": "LS증권",
    "동양증권": "유안타증권",
    "한화증권": "한화투자증권",
    "HMC투자증권": "현대차증권",
    "우리투자증권": "NH투자증권",
    "LIG투자증권": "케이프투자증권",
    "한투": "한국투자증권",
    "한투증권": "한국투자증권",
    "한국투자": "한국투자증권",
    "IBK": "IBK투자증권",
    "IBK투자": "IBK투자증권",
    "미래에셋": "미래에셋증권",
    "신한": "신한투자증권",
    "신한투자": "신한투자증권",
    "키움": "키움증권",
    "하나": "하나증권",
    "대신": "대신증권",
    "KB": "KB증권",
    "삼성": "삼성증권",
    "NH": "NH투자증권",
    "NH투자": "NH투자증권",
    "유안타": "유안타증권",
    "메리츠": "메리츠증권",
    "메리츠종금증권": "메리츠증권",
    "교보": "교보증권",
    "현대차": "현대차증권",
    "한화": "한화투자증권",
    "한화투자": "한화투자증권",
    "SK": "SK증권",
    "유진": "유진투자증권",
    "유진투자": "유진투자증권",
    "DB": "DB증권",
    "iM": "iM증권",
    "IM증권": "iM증권",
    "다올": "다올투자증권",
    "다올투자": "다올투자증권",
    "LS": "LS증권",
    "상상인": "상상인증권",
    "신영": "신영증권",
    "DS": "DS투자증권",
}

_BROKER_ALIASES_LOWER: Dict[str, str] = {k.lower(): v for k, v in BROKER_ALIASES.items()}


def normalize_broker_name(source: str) -> str:
    """REPORT 출처(증권사)를 정식 명칭으로 정규화합니다."""
    if not source:
        return ""
    cleaned = unicodedata.normalize("NFC", source).strip()
    if cleaned in BROKER_ALIASES:
        return BROKER_ALIASES[cleaned]
    lower_key = cleaned.lower()
    if lower_key in _BROKER_ALIASES_LOWER:
        return _BROKER_ALIASES_LOWER[lower_key]
    return cleaned


def normalize_date_string(date_digits: str) -> Optional[str]:
    """숫자 날짜 문자열(YYYYMMDD, YYYYMM, YYYY)을 YYYY-MM-DD 형식으로 변환합니다."""
    digits = date_digits.strip()
    if not re.fullmatch(r"\d{4}|\d{6}|\d{8}", digits):
        return None
    try:
        if len(digits) == 4:
            return f"{digits}-01-01"
        if len(digits) == 6:
            return f"{digits[:4]}-{digits[4:6]}-01"
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    except Exception:
        return None


def parse_doc_name_metadata(raw_name: str) -> Optional[Dict[str, Any]]:
    """
    파일명에서 날짜, 대상/종목명, 출처를 파싱합니다 (RPT, PUB, PAP, IR 및 한글 접두어 지원).
    """
    norm_name = unicodedata.normalize("NFC", Path(raw_name).name).strip()
    stem = re.sub(r"\.pdf$", "", norm_name, flags=re.IGNORECASE).strip()

    # RPT 전용 형식 (RPT_YYYYMMDD_종목_증권사)
    if stem.upper().startswith("RPT_"):
        parts = stem[4:].split("_")
        if len(parts) >= 4 and re.fullmatch(r"\d+", parts[-1].strip()):
            parts = parts[:-1]
        if len(parts) >= 3:
            date_str = parts[0].strip()
            source_raw = parts[-1].strip()
            company = "_".join(p.strip() for p in parts[1:-1]).strip()
            pub_date = normalize_date_string(date_str)
            norm_source = normalize_broker_name(source_raw)
            return {
                "doc_type": "REPORT",
                "publish_date": pub_date,
                "target": company,
                "company": company,
                "source_org": norm_source,
                "raw_source_org": source_raw,
            }

    # 기타 표준 형식: {종류}_{날짜}_{제목/대상}_{출처}
    prefixes = [
        ("슬라이드_IR_", "IR"),
        ("통계보도자료_", "PUBLIC_REPORT"),
        ("공공보고서_", "PUBLIC_REPORT"),
        ("보도자료_", "PUBLIC_REPORT"),
        ("보고서_", "PUBLIC_REPORT"),
        ("리포트_", "PUBLIC_REPORT"),
        ("논문_", "PAPER"),
        ("PUB_", "PUBLIC_REPORT"),
        ("PAP_", "PAPER"),
        ("IR_", "IR"),
    ]
    for prefix, d_type in prefixes:
        if stem.upper().startswith(prefix.upper()):
            parts = stem[len(prefix):].split("_")
            if len(parts) >= 4 and re.fullmatch(r"\d+", parts[-1].strip()):
                parts = parts[:-1]
            if len(parts) >= 3:
                date_str = parts[0].strip()
                source_raw = parts[-1].strip()
                target_str = "_".join(p.strip() for p in parts[1:-1]).strip()
                pub_date = normalize_date_string(date_str)
                return {
                    "doc_type": d_type,
                    "publish_date": pub_date,
                    "target": target_str,
                    "company": target_str if d_type == "REPORT" else None,
                    "source_org": source_raw,
                    "raw_source_org": source_raw,
                }

    # 컴팩트 형식: {한글종류}{YYYYMMDD}{제목}_{출처}
    compact_prefixes = ["통계보도자료", "공공보고서", "보도자료", "보고서", "리포트", "논문"]
    for prefix in compact_prefixes:
        if stem.startswith(prefix):
            rem = stem[len(prefix):]
            if re.match(r"^\d{8}", rem):
                date_str = rem[:8]
                rest = rem[8:]
                if "_" in rest:
                    if rest.count("_") >= 2:
                        base_p, maybe_dup = rest.rsplit("_", 1)
                        if re.fullmatch(r"\d+", maybe_dup.strip()):
                            rest = base_p
                    t_str, s_str = rest.rsplit("_", 1)
                    pub_date = normalize_date_string(date_str)
                    return {
                        "doc_type": "PUBLIC_REPORT" if "보고" in prefix or "보도" in prefix or "리포트" in prefix else "PAPER",
                        "publish_date": pub_date,
                        "target": t_str.strip(),
                        "company": None,
                        "source_org": s_str.strip(),
                        "raw_source_org": s_str.strip(),
                    }

    return None


def query_all_qdrant_points(qdrant_url: str, collection: str) -> List[Dict[str, Any]]:
    """Qdrant REST API scroll을 끝까지 페이징하여 모든 포인트를 로드합니다."""
    scroll_url = f"{qdrant_url.rstrip('/')}/collections/{collection}/points/scroll"
    all_points: List[Dict[str, Any]] = []
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
        all_points.extend(points)

        next_offset = result.get("next_page_offset")
        if not next_offset:
            break

    return all_points


def collect_document_stats(points: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Qdrant 포인트들로부터 문서별 통계 및 메타데이터를 집계합니다."""
    doc_stats: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "doc_name": "",
            "total_elements": 0,
            "table_count": 0,
            "source_org": "",
            "publish_date": "",
            "entities": [],
            "doc_type": "",
        }
    )

    for pt in points:
        payload = pt.get("payload") or {}
        raw_doc_name = payload.get("doc_name") or ""
        norm_doc_name = unicodedata.normalize("NFC", raw_doc_name).strip()
        if not norm_doc_name:
            continue

        entry = doc_stats[norm_doc_name]
        entry["doc_name"] = norm_doc_name
        entry["total_elements"] += 1

        el_type = payload.get("element_type")
        if el_type == ElementType.TABLE.value:
            entry["table_count"] += 1

        if not entry["source_org"]:
            entry["source_org"] = payload.get("source_org") or ""
        if not entry["publish_date"]:
            entry["publish_date"] = payload.get("publish_date") or ""
        if not entry["doc_type"]:
            entry["doc_type"] = payload.get("doc_type") or ""

        # entities 수집
        raw_ents = payload.get("entities")
        if isinstance(raw_ents, list):
            for e in raw_ents:
                norm_e = unicodedata.normalize("NFC", str(e)).strip()
                if norm_e and norm_e not in entry["entities"]:
                    entry["entities"].append(norm_e)
        elif isinstance(raw_ents, str) and raw_ents:
            norm_e = unicodedata.normalize("NFC", raw_ents).strip()
            if norm_e and norm_e not in entry["entities"]:
                entry["entities"].append(norm_e)

    return doc_stats


def evaluate_document(
    doc_name: str,
    stats: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """문서 메타데이터를 검증하고 경고 여부와 사유 목록을 반환합니다."""
    reasons: List[str] = []
    parsed_fn = parse_doc_name_metadata(doc_name)

    stored_source_org = stats.get("source_org") or ""
    stored_pub_date = str(stats.get("publish_date") or "")
    entities_list = stats.get("entities") or []

    if parsed_fn:
        file_date = parsed_fn.get("publish_date")
        file_target = parsed_fn.get("target") or parsed_fn.get("company")
        file_source = parsed_fn.get("source_org") or ""
        raw_file_source = parsed_fn.get("raw_source_org") or ""

        # 1. publish_date 비교 (파일명 날짜와 다르면 ⚠)
        if file_date and stored_pub_date:
            norm_stored_date = stored_pub_date[:10]
            norm_file_date = str(file_date)[:10]
            if norm_stored_date != norm_file_date:
                reasons.append(
                    f"publish_date 불일치 (저장값='{norm_stored_date}' != 파일명='{norm_file_date}')"
                )

        # 2. source_org 비교 (파일명 증권사/출처와 다르면 ⚠)
        if file_source:
            norm_stored_src = normalize_broker_name(stored_source_org)
            norm_file_src = normalize_broker_name(file_source)
            if (stored_source_org != file_source) and (stored_source_org != raw_file_source) and (norm_stored_src != norm_file_src):
                reasons.append(
                    f"source_org 불일치 (저장값='{stored_source_org}' != 파일명='{file_source}')"
                )

        # 3. entities에 파일명 종목명이 없으면 ⚠ (REPORT 타입 또는 RPT 문서)
        if parsed_fn.get("doc_type") == "REPORT" and file_target:
            target_in_entities = any(
                (file_target == ent or file_target in ent or ent in file_target)
                for ent in entities_list
            )
            if not target_in_entities:
                ent_display = str(entities_list[:5]) if entities_list else "[]"
                reasons.append(f"종목명 누락 (파일명='{file_target}' not in {ent_display})")

    # 4. TABLE 수가 0개인 경우 ⚠
    if stats.get("table_count", 0) == 0:
        reasons.append("TABLE 0개")

    is_warn_doc = len(reasons) > 0
    return is_warn_doc, reasons


def get_display_width(text: str) -> int:
    """터미널 표시 너비를 계산합니다 (한글/전각=2칸, 영문/기호=1칸)."""
    width = 0
    for ch in text:
        eaw = unicodedata.east_asian_width(ch)
        if eaw in ("W", "F"):
            width += 2
        else:
            width += 1
    return width


def pad_display_text(text: str, target_width: int, align_right: bool = False) -> str:
    """터미널 표시 너비에 맞춰 공백 패딩을 적용합니다."""
    cur_width = get_display_width(text)
    pad_len = max(0, target_width - cur_width)
    if align_right:
        return (" " * pad_len) + text
    return text + (" " * pad_len)


def format_table_output(records: List[Dict[str, Any]]) -> str:
    """터미널 표 형식으로 포맷팅합니다 (한글 너비 자동 보정)."""
    headers = [
        "상태",
        "문서명 (doc_name)",
        "도표 수",
        "TABLE 수",
        "source_org",
        "publish_date",
        "entities (종목명)",
    ]

    raw_rows = []
    for r in records:
        warn_mark = "⚠" if r["is_warn"] else "OK"
        ents_str = ", ".join(r["entities"]) if r["entities"] else "-"
        if len(ents_str) > 28:
            ents_str = ents_str[:25] + "..."

        row = [
            warn_mark,
            r["doc_name"],
            str(r["total_elements"]),
            str(r["table_count"]),
            r["source_org"] or "-",
            str(r["publish_date"])[:10] if r["publish_date"] else "-",
            ents_str,
        ]
        raw_rows.append(row)

    # 컬럼별 최대 표시 너비 계산
    col_widths = [get_display_width(h) for h in headers]
    for row in raw_rows:
        for idx, val in enumerate(row):
            col_widths[idx] = max(col_widths[idx], get_display_width(val))

    sep_line = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"
    header_line = "| " + " | ".join(pad_display_text(h, col_widths[i]) for i, h in enumerate(headers)) + " |"

    formatted_rows = []
    for row in raw_rows:
        row_cells = []
        for i, val in enumerate(row):
            is_num_col = (i in (2, 3))
            row_cells.append(pad_display_text(val, col_widths[i], align_right=is_num_col))
        formatted_rows.append("| " + " | ".join(row_cells) + " |")

    lines = [
        sep_line,
        header_line,
        sep_line,
    ]
    lines.extend(formatted_rows)
    lines.append(sep_line)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="저장된 115개 전체 문서별 도표 수, TABLE 수, source_org, publish_date, entities 추출 결과를 검사합니다."
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
        default=os.getenv("QDRANT_URL", "http://localhost:6333"),
        help="Qdrant 서버 URL (기본값: http://localhost:6333)",
    )
    parser.add_argument(
        "--rpt-only",
        action="store_true",
        help="증권 리포트(RPT_*.pdf) 문서만 필터링하여 출력합니다.",
    )
    parser.add_argument(
        "--filter-docs",
        type=str,
        default=None,
        help="검사할 특정 문서명 목록 (쉼표 구분 또는 파일 경로)",
    )
    args = parser.parse_args()

    print(f"[Info] Qdrant scroll 페이징 연결: {args.qdrant_url} (컬렉션: {args.collection})")
    points = query_all_qdrant_points(args.qdrant_url, args.collection)
    print(f"[Info] 총 로드된 포인트 수: {len(points)}개")

    doc_stats_map = collect_document_stats(points)
    print(f"[Info] 총 고유 문서 수: {len(doc_stats_map)}개 (페이징 완료)")

    # 대상 문서 필터링
    target_docs_filter: Optional[Set[str]] = None
    if args.filter_docs:
        filter_path = Path(args.filter_docs)
        if filter_path.is_file():
            with open(filter_path, "r", encoding="utf-8") as f:
                target_docs_filter = {
                    unicodedata.normalize("NFC", line.strip())
                    for line in f
                    if line.strip()
                }
        else:
            target_docs_filter = {
                unicodedata.normalize("NFC", name.strip())
                for name in args.filter_docs.split(",")
                if name.strip()
            }

    records: List[Dict[str, Any]] = []
    warn_records: List[Dict[str, Any]] = []

    for doc_name, stats in sorted(doc_stats_map.items()):
        if target_docs_filter and doc_name not in target_docs_filter:
            continue

        if args.rpt_only and not (doc_name.upper().startswith("RPT_") or stats.get("doc_type") == "REPORT"):
            continue

        is_warn_doc, reasons = evaluate_document(doc_name, stats)

        rec = {
            "doc_name": doc_name,
            "total_elements": stats["total_elements"],
            "table_count": stats["table_count"],
            "source_org": stats["source_org"],
            "publish_date": stats["publish_date"],
            "entities": stats["entities"],
            "is_warn": is_warn_doc,
            "reasons": reasons,
        }
        records.append(rec)
        if is_warn_doc:
            warn_records.append(rec)

    # 출력 테이블 생성
    print("\n" + "=" * 125)
    print(f"                          FigIndex 저장 문서 전체 추출 결과 검사 리포트 ({len(records)}개 문서)")
    print("=" * 125)

    table_text = format_table_output(records)
    print(table_text)

    # 통계 요약
    total_docs_cnt = len(records)
    warn_docs_cnt = len(warn_records)
    normal_docs_cnt = total_docs_cnt - warn_docs_cnt
    sum_elements = sum(r["total_elements"] for r in records)
    sum_tables = sum(r["table_count"] for r in records)

    print("\n[검사 통계]")
    print(f"  - 검사 대상 문서 수: {total_docs_cnt}개 (정상: {normal_docs_cnt}개, ⚠ 점검 필요: {warn_docs_cnt}개)")
    print(f"  - 총 도표 수: {sum_elements}개 | 총 TABLE 수: {sum_tables}개")

    # 맨 아래 ⚠ 점검 필요 문서 따로 모아 출력
    print("\n" + "=" * 125)
    print(f"                      ⚠ 점검 필요 문서 목록 (총 {warn_docs_cnt}건)")
    print("=" * 125)

    if not warn_records:
        print("  특이사항 없음 (모든 문서의 추출 결과가 정상입니다).")
    else:
        for idx, wr in enumerate(warn_records, 1):
            reasons_str = " / ".join(wr["reasons"])
            print(f" {idx:2d}. [{wr['doc_name']}]")
            print(f"     - 추출 정보: source_org='{wr['source_org']}', publish_date='{wr['publish_date']}', TABLE={wr['table_count']}/{wr['total_elements']}개, entities={wr['entities'][:4]}")
            print(f"     - ⚠ 경고 사유: {reasons_str}")
            print("     " + "-" * 115)

    print("=" * 125 + "\n")


if __name__ == "__main__":
    main()
