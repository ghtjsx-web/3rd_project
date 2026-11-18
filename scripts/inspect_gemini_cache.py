#!/usr/bin/env python3
"""
scripts/inspect_gemini_cache.py

빈 표(TABLE인데 table_data 없음) 요소가 Gemini에게서 실제로 어떤 응답을 받았는지
캐시(figindex/data/cache/gemini_cache.json)에서 꺼내 본다. (읽기 전용)

캐시 키는 extractor.get_image_hash와 같은 방식: 크롭 이미지 파일의 SHA-256.
크롭 파일은 image_path(/static/crops/파일명)의 파일명으로 figindex/data/crops에서 찾는다.

사용법 (저장소 루트, Qdrant 실행 중):
    python scripts/inspect_gemini_cache.py                    # pipeline_version 0.0.0이 아닌 빈 표 전부
    python scripts/inspect_gemini_cache.py --all              # 빈 표 전부
    python scripts/inspect_gemini_cache.py --element-id fig-2c3924c3519b
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT / "figindex"))

try:
    from diagnose_empty_tables import is_empty_table, scroll_all
    from shared.schemas import TableData
except ImportError as e:
    sys.exit(f"모듈을 불러오지 못했습니다: {e}\n'pip install pydantic' 후, 저장소 루트에서 실행해 주세요.")

LEGACY_PIPELINE_VERSION = "0.0.0"


def file_sha256(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def describe_table(value: Any) -> str:
    """캐시에 담긴 table_data가 어떤 모양인지 한 줄로 설명한다."""
    if value is None:
        return "null"
    if isinstance(value, dict):
        cols = value.get("columns")
        rows = value.get("rows")
        return (f"dict(columns {len(cols) if isinstance(cols, list) else type(cols).__name__}개, "
                f"rows {len(rows) if isinstance(rows, list) else type(rows).__name__}개, "
                f"키 {sorted(value.keys())})")
    return f"{type(value).__name__}: {json.dumps(value, ensure_ascii=False)[:120]}"


def table_validation_error(value: Any) -> str:
    """캐시의 table_data가 TableData 검증을 통과하면 빈 문자열, 아니면 오류와 행 키 불일치 수."""
    if not isinstance(value, dict):
        return ""
    try:
        TableData(**value)
        error = ""
    except Exception as e:
        error = " / ".join(line.strip() for line in str(e).splitlines()[:3])[:200]
    columns = set(map(str, value.get("columns") or []))
    rows = value.get("rows") or []
    bad = sum(1 for r in rows if not isinstance(r, dict) or set(map(str, r.keys())) != columns)
    note = f"행 키가 columns와 다른 행 {bad}/{len(rows)}개" if bad else "행 키 일치"
    return f"{error or '검증 통과'} ({note})"


def main() -> None:
    parser = argparse.ArgumentParser(description="빈 표 요소의 Gemini 캐시 응답 확인 (읽기 전용)")
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"))
    parser.add_argument("--collection", default=os.getenv("QDRANT_COLLECTION", "figindex_elements_v2"))
    parser.add_argument("--crops-dir", default=str(REPO_ROOT / "figindex" / "data" / "crops"))
    parser.add_argument("--cache-file", default=str(REPO_ROOT / "figindex" / "data" / "cache" / "gemini_cache.json"))
    parser.add_argument("--all", action="store_true", help="옛 파이프라인(0.0.0) 요소까지 포함")
    parser.add_argument("--element-id", action="append", help="특정 요소만 (여러 번 지정 가능)")
    args = parser.parse_args()

    cache_path = Path(args.cache_file)
    if not cache_path.exists():
        sys.exit(f"캐시 파일이 없습니다: {cache_path}")
    cache: Dict[str, Any] = json.loads(cache_path.read_text(encoding="utf-8"))
    print(f"캐시 항목 {len(cache)}개 ({cache_path})")

    targets = []
    for p in scroll_all(args.qdrant_url, args.collection):
        if args.element_id:
            if p.get("element_id") in args.element_id:
                targets.append(p)
        elif is_empty_table(p) and (args.all or p.get("pipeline_version") != LEGACY_PIPELINE_VERSION):
            targets.append(p)

    for p in targets:
        crop = Path(args.crops_dir) / Path(p.get("image_path", "")).name
        digest = file_sha256(crop)
        print(f"\n{p.get('element_id')}  {p.get('doc_name')} p.{p.get('page_number')}  (pipeline {p.get('pipeline_version')})")
        if digest is None:
            print(f"  크롭 파일 없음: {crop}")
            continue
        entry = cache.get(digest)
        if entry is None:
            print("  캐시에 없음 (이 크롭으로 Gemini를 호출한 기록이 없거나 응답이 깨져 저장되지 않음)")
            continue
        print(f"  캐시 element_type: {entry.get('element_type')}")
        print(f"  캐시 caption: {str(entry.get('caption', ''))[:80]}")
        print(f"  캐시 table_data: {describe_table(entry.get('table_data'))}")
        if isinstance(entry.get("table_data"), dict):
            print(f"  TableData 검증: {table_validation_error(entry.get('table_data'))}")


if __name__ == "__main__":
    main()
