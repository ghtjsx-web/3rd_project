#!/usr/bin/env python3
"""
scripts/reextract_empty_tables.py

TABLE인데 table_data가 비어 있는 요소를 지금 파이프라인(PIPELINE_VERSION)으로 다시 추출해
**시험용 컬렉션**에 넣는다. 서비스 컬렉션(figindex_elements, figindex_elements_v2)에는 쓰지 않는다.
(figindex/pipeline/AGENTS.md 1절)

하는 일
1. 원본 컬렉션(--source, 기본 figindex_elements_v2)에서 빈 표 요소를 고른다. (읽기만)
2. 시험 컬렉션(QDRANT_COLLECTION)이 없으면 원본과 같은 벡터 설정(dense, sparse IDF 포함)으로 만든다.
3. gemini_cache.json을 한 번 백업하고, 대상 크롭의 캐시 항목만 지운다. (캐시를 끄지 않음)
4. 원래 크롭 이미지·bbox·문서 정보로 extractor.analyze_crop을 다시 부르고,
   orchestrator.index_element_to_qdrant로 시험 컬렉션에 넣는다. (기존 색인과 같은 함수)
5. 전후 비교 CSV를 /data/reextract_report_시각.csv로 남긴다.

실행 (figindex 폴더, pipeline 컨테이너 안):
    docker compose run --rm -e QDRANT_COLLECTION=figindex_test_ryu pipeline \\
        python /scripts/reextract_empty_tables.py --limit 3
    # 특정 요소만
    docker compose run --rm -e QDRANT_COLLECTION=figindex_test_ryu pipeline \\
        python /scripts/reextract_empty_tables.py --element-id fig-60589bd4757d
    # Gemini를 부르지 않고, 직전 재추출 때 캐시에 저장된 응답으로 후처리만 다시 (--model-name은 그 응답을 낸 모델)
    docker compose run --rm -e QDRANT_COLLECTION=figindex_test_ryu pipeline \\
        python /scripts/reextract_empty_tables.py --reuse-cache --model-name gemini-3.5-flash-lite
"""
import argparse
import csv
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
for candidate in (Path("/app"), SCRIPT_DIR.parent / "figindex" / "pipeline", SCRIPT_DIR.parent / "figindex"):
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from shared.schemas import ElementType  # noqa: E402

PROTECTED_COLLECTIONS = {"figindex_elements", "figindex_elements_v2"}
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))


# ---------------------------------------------------------------------------
# 순수 함수 (테스트 대상)
# ---------------------------------------------------------------------------

def check_target_collection(name: str) -> None:
    """서비스 컬렉션이나 이름 규칙에 안 맞는 컬렉션에는 쓰지 않는다."""
    if name in PROTECTED_COLLECTIONS:
        raise SystemExit(f"'{name}'은 서비스 컬렉션이라 쓸 수 없습니다. QDRANT_COLLECTION=figindex_test_<이름>으로 실행해 주세요.")
    if not name.startswith("figindex_test_"):
        raise SystemExit(f"시험 컬렉션 이름은 figindex_test_로 시작해야 합니다: '{name}'")


def is_empty_table(payload: Dict[str, Any]) -> bool:
    if payload.get("element_type") != ElementType.TABLE.value:
        return False
    table = payload.get("table_data")
    return not (isinstance(table, dict) and table.get("rows"))


def select_targets(points: List[Dict[str, Any]], element_ids: Optional[List[str]], limit: Optional[int]) -> List[Dict[str, Any]]:
    """빈 표 요소를 고른다. element_ids가 있으면 그 요소만 (빈 표가 아니어도)."""
    if element_ids:
        wanted = set(element_ids)
        chosen = [p for p in points if p["payload"].get("element_id") in wanted]
    else:
        chosen = [p for p in points if is_empty_table(p["payload"])]
        chosen.sort(key=lambda p: (p["payload"].get("doc_name", ""), p["payload"].get("page_number", 0)))
    return chosen[:limit] if limit else chosen


def build_crop_info(payload: Dict[str, Any], crops_dir: Path, text_layer_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """기존 요소 정보로 cropper.crop_and_save가 돌려주는 것과 같은 모양의 crop_info를 만든다."""
    image_path = payload.get("image_path", "")
    return {
        "element_id": payload["element_id"],
        "crop_path": crops_dir / Path(image_path).name,
        "relative_path": image_path,
        "hint_type": payload.get("element_type", ElementType.TABLE.value),
        "caption_hint": payload.get("caption", ""),
        "normalized_box": list(payload.get("bbox") or [0.0, 0.0, 1.0, 1.0]),
        "text_layer_info": text_layer_info,
    }


def build_doc_metadata(payload: Dict[str, Any]) -> Dict[str, Any]:
    """extractor.build_prompt·analyze_crop가 읽는 문서 정보."""
    target = (payload.get("extra_metadata") or {}).get("target")
    return {
        "doc_id": payload.get("doc_id"),
        "doc_title": payload.get("doc_title"),
        "doc_type": payload.get("doc_type"),
        "source_org": payload.get("source_org"),
        "target": target,
        "company": target,
    }


# ---------------------------------------------------------------------------
# Qdrant REST
# ---------------------------------------------------------------------------

def _request(method: str, url: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def scroll_points(qdrant_url: str, collection: str) -> List[Dict[str, Any]]:
    points: List[Dict[str, Any]] = []
    offset = None
    while True:
        body: Dict[str, Any] = {"limit": 256, "with_payload": True, "with_vector": False}
        if offset is not None:
            body["offset"] = offset
        result = _request("POST", f"{qdrant_url}/collections/{collection}/points/scroll", body)["result"]
        points.extend({"id": p["id"], "payload": p.get("payload") or {}} for p in result["points"])
        offset = result.get("next_page_offset")
        if offset is None:
            return points


def ensure_test_collection(qdrant_url: str, source: str, target: str) -> None:
    """시험 컬렉션이 없으면 원본과 같은 벡터 설정으로 만든다."""
    try:
        _request("GET", f"{qdrant_url}/collections/{target}")
        print(f"[시험 컬렉션] '{target}' 있음")
        return
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    params = _request("GET", f"{qdrant_url}/collections/{source}")["result"]["config"]["params"]
    body = {"vectors": params["vectors"]}
    if params.get("sparse_vectors"):
        body["sparse_vectors"] = params["sparse_vectors"]
    _request("PUT", f"{qdrant_url}/collections/{target}", body)
    print(f"[시험 컬렉션] '{target}' 생성 ('{source}'와 같은 벡터 설정)")


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="빈 표 요소를 시험 컬렉션에 재추출")
    parser.add_argument("--source", default="figindex_elements_v2", help="읽기만 하는 원본 컬렉션")
    parser.add_argument("--limit", type=int, help="앞에서부터 N개만")
    parser.add_argument("--element-id", action="append", help="특정 요소만 (여러 번 지정 가능)")
    parser.add_argument("--reuse-cache", action="store_true",
                        help="Gemini를 부르지 않고 캐시의 응답으로 후처리만 다시 한다. 캐시에 없는 요소는 건너뜀")
    parser.add_argument("--model-name", help="--reuse-cache 때 기록할 모델 이름 (캐시 응답을 낸 모델)")
    args = parser.parse_args()
    if args.model_name and not args.reuse_cache:
        raise SystemExit("--model-name은 --reuse-cache와 함께만 씁니다.")
    if args.model_name:
        # extractor는 캐시를 쓴 경우 VISION_MODEL 값을 model_name으로 기록한다
        os.environ["VISION_MODEL"] = args.model_name

    target = os.getenv("QDRANT_COLLECTION", "")
    check_target_collection(target)
    qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
    crops_dir = Path(os.getenv("CROPS_DIR", str(DATA_DIR / "crops")))
    pdfs_dir = Path(os.getenv("PDFS_DIR", str(DATA_DIR / "pdfs")))

    targets = select_targets(scroll_points(qdrant_url, args.source), args.element_id, args.limit)
    print(f"[대상] {args.source}에서 {len(targets)}개 → {target}")
    if not targets:
        return
    ensure_test_collection(qdrant_url, args.source, target)

    # 무거운 모듈은 여기서 불러온다 (Gemini·OpenAI·PyMuPDF)
    import fitz
    from orchestrator import ExtractionPipelineOrchestrator
    from shared.schemas import ElementSearchPayload, PIPELINE_VERSION

    orchestrator = ExtractionPipelineOrchestrator()
    assert orchestrator.collection_name == target, "orchestrator가 시험 컬렉션을 가리키지 않습니다."
    extractor = orchestrator.extractor

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    cache_backup = extractor.cache_file.with_name(f"gemini_cache.before_reextract_{stamp}.json")
    if extractor.cache_file.exists():
        shutil.copy2(extractor.cache_file, cache_backup)
        print(f"[캐시 백업] {cache_backup}")

    report_rows = []
    for point in targets:
        old = point["payload"]
        eid = old.get("element_id")
        row = {"요소 ID": eid, "파일명": old.get("doc_name"), "페이지 번호": old.get("page_number"),
               "이전 확신도": old.get("confidence_score"), "이전 상태": old.get("review_status")}
        try:
            crop_path = crops_dir / Path(old.get("image_path", "")).name
            if not crop_path.exists():
                raise FileNotFoundError(f"크롭 파일 없음: {crop_path}")

            text_layer_info = None
            pdf_path = pdfs_dir / old.get("doc_name", "")
            if pdf_path.exists():
                with fitz.open(str(pdf_path)) as doc:
                    x0, y0, x1, y1 = old["bbox"]
                    # cropper.extract_text_layer_in_bbox는 [ymin, xmin, ymax, xmax] 순서를 받는다
                    text_layer_info = orchestrator.cropper.extract_text_layer_in_bbox(
                        doc[old["page_number"] - 1], (y0, x0, y1, x1))

            img_hash = extractor.get_image_hash(crop_path)
            if args.reuse_cache:
                if img_hash not in extractor.cache:
                    raise LookupError("캐시에 응답이 없어 건너뜀 (--reuse-cache는 Gemini를 부르지 않음)")
            elif extractor.cache.pop(img_hash, None) is not None:
                extractor._save_cache()

            element = extractor.analyze_crop(
                crop_info=build_crop_info(old, crops_dir, text_layer_info),
                doc_name=old.get("doc_name", ""),
                page_number=old["page_number"],
                doc_metadata=build_doc_metadata(old),
                detection_score=float((old.get("signals") or {}).get("detection_score") or 0.92),
                doc_id=old.get("doc_id"),
            )
            new = ElementSearchPayload(
                **element.model_dump(),
                doc_name=old.get("doc_name"), doc_title=old.get("doc_title"), doc_type=old.get("doc_type"),
                domain=old.get("domain"), source_org=old.get("source_org"), authors=old.get("authors") or [],
                publish_date=old.get("publish_date"), collection_id=old.get("collection_id"),
            )
            extra = dict(old.get("extra_metadata") or {})
            extra.update(new.extra_metadata or {})
            how = "캐시 응답으로 후처리만 다시" if args.reuse_cache else "Gemini 재호출"
            extra["reextract_note"] = f"{stamp} 빈 표 재추출, {how} (이전 pipeline {old.get('pipeline_version')})"
            new.extra_metadata = extra
            orchestrator.index_element_to_qdrant(new)

            rows = len(new.table_data.rows) if new.table_data else 0
            row.update({"새 유형": new.element_type.value, "새 표 행 수": rows,
                        "새 확신도": new.confidence_score, "새 상태": new.review_status.value,
                        "pipeline_version": PIPELINE_VERSION, "모델": new.model_name, "메모": ""})
            print(f"  {eid}: {new.element_type.value}, 표 {rows}행, 확신도 {new.confidence_score:.2f} ({new.review_status.value})")
        except Exception as e:  # 한 건이 실패해도 나머지는 계속
            row["메모"] = f"실패: {str(e)[:150]}"
            print(f"  {eid}: 실패 - {e}")
        report_rows.append(row)

    report = DATA_DIR / f"reextract_report_{stamp}.csv"
    fields = ["요소 ID", "파일명", "페이지 번호", "이전 확신도", "이전 상태", "새 유형", "새 표 행 수",
              "새 확신도", "새 상태", "pipeline_version", "모델", "메모"]
    with open(report, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(report_rows)
    ok = sum(1 for r in report_rows if r.get("새 표 행 수"))
    print(f"[완료] {len(report_rows)}개 중 표가 채워진 것 {ok}개. 보고서: {report} (PC에서는 figindex/data/ 아래)")


if __name__ == "__main__":
    main()
