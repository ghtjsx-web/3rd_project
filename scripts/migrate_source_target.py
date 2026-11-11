"""
기존 Qdrant 색인 데이터를 Gemini 재호출 없이 새로운 '출처(source_org) / 대상(extra_metadata.target)' 구조로 보정하는 마이그레이션 스크립트.

사용 예시:
  1) 미리보기 (--dry-run):
     python scripts/migrate_source_target.py --dry-run
  2) 실제 적용:
     python scripts/migrate_source_target.py
"""

import argparse
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

REPO_ROOT = Path(__file__).resolve().parent.parent
FIGINDEX_DIR = REPO_ROOT / "figindex"
PIPELINE_DIR = FIGINDEX_DIR / "pipeline"

for p in (str(PIPELINE_DIR), str(FIGINDEX_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

load_dotenv(FIGINDEX_DIR / ".env")
load_dotenv(REPO_ROOT / ".env")

from orchestrator import parse_new_filename  # noqa: E402

IGNORED_ENTITY_DEFAULTS = {"", "증권사", "금융분석", "출처미상"}


def build_entities(target: str, source_org: str, hashtags: List[str]) -> List[str]:
    """extractor.py와 동일한 규칙으로 entities 목록을 재구성합니다."""
    raw = [target, source_org] + list(hashtags or [])
    result: List[str] = []
    seen = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        cleaned = item.replace("#", "").strip()
        if not cleaned or cleaned in IGNORED_ENTITY_DEFAULTS or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def build_updated_extra_metadata(
    old_extra: Dict[str, Any],
    doc_type: str,
    target: str,
    source_org: str,
) -> Dict[str, Any]:
    """기존 extra_metadata를 보존하면서 target 및 doc_type별 하위 호환 필드를 갱신합니다."""
    updated = dict(old_extra or {})
    updated["target"] = target
    if doc_type == "REPORT":
        updated["company"] = target
        updated["broker"] = source_org
    else:
        updated["company"] = None
        updated["broker"] = None
        updated["ticker"] = None
        updated["analyst"] = None
    return updated


def get_client(qdrant_mode: str, qdrant_url: str, local_path: str) -> QdrantClient:
    if qdrant_mode.lower() == "local":
        return QdrantClient(path=local_path)
    return QdrantClient(url=qdrant_url, timeout=15.0)


def ensure_indexes(client: QdrantClient, collection_name: str) -> None:
    for field_name in ("doc_type", "source_org", "extra_metadata.target"):
        try:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=qmodels.PayloadSchemaType.KEYWORD,
            )
        except Exception:
            pass


def run_migration(
    client: QdrantClient,
    collection_name: str,
    dry_run: bool = True,
) -> Dict[str, Any]:
    print("=" * 72)
    print(f" FigIndex Qdrant Payload 마이그레이션 ({'DRY-RUN 미리보기' if dry_run else '실제 적용'})")
    print(f" - Collection: {collection_name}")
    print("=" * 72)

    if not dry_run:
        ensure_indexes(client, collection_name)

    total_points = 0
    updated_points = 0
    unchanged_points = 0
    failed_docs: Counter = Counter()
    doc_changes: Dict[str, Dict[str, Any]] = {}

    offset = None
    while True:
        records, next_offset = client.scroll(
            collection_name=collection_name,
            limit=300,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not records:
            break

        for rec in records:
            total_points += 1
            payload = dict(rec.payload or {})
            doc_name = str(payload.get("doc_name") or "").strip()

            parsed = parse_new_filename(doc_name) if doc_name else None
            if not parsed:
                failed_docs[doc_name or f"<empty doc_name id={rec.id}>"] += 1
                continue

            new_doc_type = parsed["doc_type"]
            new_source_org = parsed["source_org"]
            new_target = parsed["target"]
            old_extra = dict(payload.get("extra_metadata") or {})
            new_extra = build_updated_extra_metadata(
                old_extra=old_extra,
                doc_type=new_doc_type,
                target=new_target,
                source_org=new_source_org,
            )
            new_entities = build_entities(
                target=new_target,
                source_org=new_source_org,
                hashtags=payload.get("hashtags") or [],
            )

            is_changed = (
                payload.get("doc_type") != new_doc_type
                or payload.get("source_org") != new_source_org
                or payload.get("extra_metadata") != new_extra
                or payload.get("entities") != new_entities
            )

            if is_changed:
                updated_points += 1
                if doc_name not in doc_changes:
                    doc_changes[doc_name] = {
                        "count": 0,
                        "old_doc_type": payload.get("doc_type"),
                        "new_doc_type": new_doc_type,
                        "old_source_org": payload.get("source_org"),
                        "new_source_org": new_source_org,
                        "old_target": old_extra.get("target") or old_extra.get("company"),
                        "new_target": new_target,
                    }
                doc_changes[doc_name]["count"] += 1

                if not dry_run:
                    client.set_payload(
                        collection_name=collection_name,
                        payload={
                            "doc_type": new_doc_type,
                            "source_org": new_source_org,
                            "extra_metadata": new_extra,
                            "entities": new_entities,
                        },
                        points=[rec.id],
                    )
            else:
                unchanged_points += 1

        if next_offset is None:
            break
        offset = next_offset

    print(f"\n[요약] 전체 포인트: {total_points}개")
    print(f"  - 변경 대상: {updated_points}개 포인트 ({len(doc_changes)}개 문서)")
    print(f"  - 변경 불필요(이미 최신): {unchanged_points}개 포인트")
    print(f"  - 파싱 실패(변경 안 함): {sum(failed_docs.values())}개 포인트 ({len(failed_docs)}개 문서)")

    if doc_changes:
        print("\n[문서별 변경 내역]")
        for doc_name, info in sorted(doc_changes.items()):
            print(
                f"  * {doc_name} ({info['count']}건): "
                f"doc_type [{info['old_doc_type']} -> {info['new_doc_type']}], "
                f"source_org [{info['old_source_org']} -> {info['new_source_org']}], "
                f"target [{info['old_target']} -> {info['new_target']}]"
            )

    if failed_docs:
        print("\n[파싱 실패 문서 목록 - payload 수정 건너뜀]")
        for doc_name, cnt in sorted(failed_docs.items()):
            print(f"  - {doc_name} ({cnt}건)")

    if dry_run:
        print("\n[안내] --dry-run 모드이므로 Qdrant 데이터는 수정되지 않았습니다.")
    else:
        print("\n[완료] Qdrant payload 마이그레이션 적용을 완료했습니다.")

    return {
        "total_points": total_points,
        "updated_points": updated_points,
        "unchanged_points": unchanged_points,
        "failed_docs": dict(failed_docs),
    }


def main():
    parser = argparse.ArgumentParser(
        description="기존 Qdrant payload의 doc_type, source_org, extra_metadata.target, entities를 재파싱해 보정합니다."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제로 Qdrant를 수정하지 않고 변경될 내용만 미리 출력합니다.",
    )
    parser.add_argument(
        "--qdrant-mode",
        default=os.getenv("QDRANT_MODE", "server"),
        choices=["server", "local"],
        help="Qdrant 연결 모드 (server 또는 local)",
    )
    parser.add_argument(
        "--qdrant-url",
        default=os.getenv("QDRANT_URL", "http://localhost:6333"),
        help="Qdrant 서버 URL (기본값: 환경변수 QDRANT_URL 또는 http://localhost:6333)",
    )
    parser.add_argument(
        "--local-path",
        default=os.getenv("QDRANT_LOCAL_PATH", str(FIGINDEX_DIR / "data" / "qdrant_local")),
        help="local 모드일 때 Qdrant 데이터 경로",
    )
    parser.add_argument(
        "--collection",
        default=os.getenv("QDRANT_COLLECTION", "figindex_elements"),
        help="Qdrant 컬렉션 이름",
    )
    args = parser.parse_args()

    client = get_client(args.qdrant_mode, args.qdrant_url, args.local_path)
    run_migration(client=client, collection_name=args.collection, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

