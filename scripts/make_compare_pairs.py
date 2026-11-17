#!/usr/bin/env python3
"""
make_compare_pairs.py: Qdrant 전체 문서의 extra_metadata.company 기준으로 묶어
문서가 2개 이상인 종목의 비교 그룹을 생성하고 data/compare_pairs.json에 저장하는 스크립트.

기능:
1. Qdrant 전체 문서의 extra_metadata.company 고유값 목록 출력 및 표기 유사 이름 경고 (예: KTnG / KT&G)
2. 문서가 2개 이상인 종목만 그룹화
3. 그룹마다 문서 목록(doc_name, source_org, publish_date) 및 '모두 같은 날짜인지(same_publish_date)' 여부 포함
4. data/compare_pairs.json에 저장
5. 문서 수가 많은 순으로 콘솔 요약 출력

사용법:
    python scripts/make_compare_pairs.py
    python scripts/make_compare_pairs.py --collection figindex_elements_v2 --output data/compare_pairs.json
"""

import argparse
import difflib
import itertools
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

logger = logging.getLogger(__name__)


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


def collect_documents_from_points(points: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """포인트 목록에서 doc_name 기준으로 고유 문서를 집계합니다."""
    docs: Dict[str, Dict[str, Any]] = {}

    for pt in points:
        payload = pt.get("payload") or {}
        raw_doc_name = payload.get("doc_name") or ""
        norm_doc_name = unicodedata.normalize("NFC", raw_doc_name).strip()
        if not norm_doc_name:
            continue

        if norm_doc_name not in docs:
            extra = payload.get("extra_metadata") or {}
            # extra_metadata.target 최우선, 없으면 extra_metadata.company 또는 payload.target/company
            comp = None
            if isinstance(extra, dict):
                comp = extra.get("target") or extra.get("company")
            if not comp:
                comp = payload.get("target") or payload.get("company")

            norm_comp = unicodedata.normalize("NFC", str(comp)).strip() if comp else None

            pub_date_raw = payload.get("publish_date")
            pub_date_str = str(pub_date_raw)[:10] if pub_date_raw else None

            docs[norm_doc_name] = {
                "doc_name": norm_doc_name,
                "company": norm_comp,
                "source_org": payload.get("source_org") or "",
                "publish_date": pub_date_str,
                "doc_type": payload.get("doc_type") or "",
            }

    return docs


def find_similar_company_names(company_list: List[str]) -> List[Tuple[str, str, str]]:
    """
    company 이름 목록에서 표기가 비슷한 쌍(예: KTnG / KT&G, 공백/특수문자 차이, 높은 문자 유사도)을 탐지합니다.
    """
    def normalize_for_match(s: str) -> str:
        cleaned = re.sub(r"[\s_\-\.]", "", s).lower()
        cleaned = cleaned.replace("&", "n")
        return cleaned

    similar_pairs: List[Tuple[str, str, str]] = []
    for c1, c2 in itertools.combinations(company_list, 2):
        n1 = normalize_for_match(c1)
        n2 = normalize_for_match(c2)
        if n1 == n2:
            similar_pairs.append((c1, c2, "특수문자/대소문자/정규화 일치 (예: KTnG / KT&G)"))
            continue

        raw_n1 = re.sub(r"[\s&_\-\.]", "", c1).lower()
        raw_n2 = re.sub(r"[\s&_\-\.]", "", c2).lower()
        if raw_n1 == raw_n2:
            similar_pairs.append((c1, c2, "특수문자 차이"))
            continue

        # difflib 유사도
        ratio = difflib.SequenceMatcher(None, raw_n1, raw_n2).ratio()
        if ratio >= 0.75 and min(len(raw_n1), len(raw_n2)) >= 2:
            similar_pairs.append((c1, c2, f"문자 유사도 {ratio:.2f}"))

    return similar_pairs


def build_comparison_groups(docs: Dict[str, Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str], List[Tuple[str, str, str]]]:
    """
    Qdrant 문서들의 extra_metadata.company 기준으로 묶어
    2개 이상 문서가 있는 종목만 그룹으로 생성합니다.
    """
    # 1. company 고유값 수집
    company_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for doc_info in docs.values():
        comp = doc_info.get("company")
        if comp:
            company_groups[comp].append(doc_info)

    unique_companies = sorted(list(company_groups.keys()))

    # 2. 유사 표기 탐지
    similar_pairs = find_similar_company_names(unique_companies)

    # 3. 문서가 2개 이상인 종목만 그룹화
    paired_groups: List[Dict[str, Any]] = []
    for comp, doc_list in company_groups.items():
        if len(doc_list) < 2:
            continue

        # 발행일, 출처, 파일명 기준 정렬
        sorted_docs = sorted(
            doc_list,
            key=lambda x: (x.get("publish_date") or "", x.get("source_org") or "", x.get("doc_name") or ""),
        )

        # 모두 같은 날짜인지 여부 확인
        dates_set = {d["publish_date"] for d in sorted_docs if d.get("publish_date")}
        all_have_date = len(dates_set) > 0 and len(dates_set) == 1 and all(d.get("publish_date") for d in sorted_docs)
        same_date_flag = bool(all_have_date)

        doc_entries = [
            {
                "doc_name": d["doc_name"],
                "source_org": d["source_org"],
                "publish_date": d["publish_date"],
            }
            for d in sorted_docs
        ]

        paired_groups.append({
            "company": comp,
            "count": len(doc_entries),
            "same_publish_date": same_date_flag,
            "documents": doc_entries,
        })

    # 문서 수가 많은 순(내림차순), 종목명 가나다순 정렬
    paired_groups.sort(key=lambda x: (-x["count"], x["company"]))
    return paired_groups, unique_companies, similar_pairs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Qdrant 전체 문서의 extra_metadata.company 기준으로 묶어 2개 이상인 종목 그룹을 data/compare_pairs.json에 저장합니다."
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
        "--output",
        type=str,
        default="data/compare_pairs.json",
        help="결과를 저장할 JSON 파일 경로 (기본값: data/compare_pairs.json)",
    )
    args = parser.parse_args()

    print(f"[Info] Qdrant 연결: {args.qdrant_url} (컬렉션: {args.collection})")
    points = query_all_qdrant_points(args.qdrant_url, args.collection)
    print(f"[Info] 전체 포인트 수: {len(points)}개")

    docs = collect_documents_from_points(points)
    print(f"[Info] 전체 고유 문서 수: {len(docs)}개")

    # 그룹화 및 고유값/유사값 분석
    paired_groups, unique_companies, similar_pairs = build_comparison_groups(docs)

    # 1. company 고유값 목록 출력
    print("\n" + "=" * 90)
    print(f"               Qdrant 전체 문서 extra_metadata.company 고유값 목록 (총 {len(unique_companies)}개)")
    print("=" * 90)
    for idx, comp in enumerate(unique_companies, 1):
        print(f" {idx:3d}. {comp}")

    # 2. 표기 유사 이름 경고 출력
    print("\n" + "-" * 90)
    print(f"                      [표기 유사 company 탐지 결과 (경고 {len(similar_pairs)}건)]")
    print("-" * 90)
    if not similar_pairs:
        print("  표기 유사 company가 발견되지 않았습니다.")
    else:
        for idx, (c1, c2, reason) in enumerate(similar_pairs, 1):
            print(f"  ⚠ [{idx}] '{c1}' <-> '{c2}' ({reason})")
    print("-" * 90)

    # 3. 콘솔 요약 (문서 수가 많은 순)
    print("\n" + "=" * 90)
    print(f"              비교 가능 종목 그룹 요약 (문서 2개 이상: 총 {len(paired_groups)}개 종목)")
    print("=" * 90)
    if not paired_groups:
        print("  문서가 2개 이상인 종목이 없습니다.")
    else:
        for idx, grp in enumerate(paired_groups, 1):
            same_date_str = "모두 동일 날짜" if grp["same_publish_date"] else "서로 다른 날짜"
            doc_names_str = ", ".join(d["doc_name"] for d in grp["documents"])
            print(f" [{idx:2d}] {grp['company']} : {grp['count']}개 문서 ({same_date_str})")
            for d in grp["documents"]:
                print(f"       - {d['doc_name']} | 출처: {d['source_org']} | 발행일: {d['publish_date']}")

    # 4. JSON 파일 저장 (data/compare_pairs.json 및 figindex/data/compare_pairs.json)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(paired_groups, f, ensure_ascii=False, indent=2)
    print(f"\n[성공] 결과 저장 완료: {out_path.resolve()}")

    # 보조 경로 (figindex/data/compare_pairs.json) 저장
    alt_path = Path("figindex/data/compare_pairs.json")
    if out_path.resolve() != alt_path.resolve():
        try:
            alt_path.parent.mkdir(parents=True, exist_ok=True)
            with open(alt_path, "w", encoding="utf-8") as f:
                json.dump(paired_groups, f, ensure_ascii=False, indent=2)
            print(f"[성공] 추가 경로 저장 완료: {alt_path.resolve()}")
        except Exception as e:
            logger.warning(f"추가 경로 저장 실패: {e}")

    print("=" * 90 + "\n")


if __name__ == "__main__":
    main()
