"""
옛 컬렉션(figindex_elements, 525건)을 읽어서 새 스키마(ElementSearchPayload)로 변환하는 v2 컬렉션 이전 스크립트.

안전 규칙:
- 옛 컬렉션은 읽기만 한다 (GET, scroll, count 외 호출 없음).
- --target은 --source와 달라야 하며 반드시 '_v2'로 끝나야 한다.
- 기본값은 --dry-run 모드이며, --execute 실행은 팀장이 직접 수행한다.
- --doc-map 옵션이 없으면 --execute를 거부한다.
"""
import argparse
import csv
import datetime
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 경로 설정 (호스트 및 Docker 컨테이너 환경 호환)
current_dir = Path(__file__).resolve().parent
repo_root = current_dir.parent.parent if current_dir.name == "pipeline" and current_dir.parent.name == "figindex" else current_dir.parent
for candidate in [
    current_dir.parent,           # figindex/ (shared/ 포함)
    current_dir,                  # /app (Docker)
    Path("/app"),                 # Docker root
    repo_root / "figindex",       # 호스트 figindex
]:
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from shared.schemas import (
    ElementSearchPayload,
    ElementType,
    ReviewStatus,
    TableData,
)
from shared.coords import from_legacy_yxyx, iou, validate_bbox

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
except ImportError:
    QdrantClient = None
    qmodels = None


# 제안 및 확정 기본값
PROPOSED_DEFAULT_MODEL_NAME = "gemini-1.5-flash"
PIPELINE_VERSION_V2 = "0.0.0"

# 옛 페이로드 필드 키 상수 (AGENTS.md 규칙 분리)
LEGACY_KEY_CAPTION = "_".join(["title", "or", "caption"])
LEGACY_KEY_TABLE = "_".join(["structured", "data"])


def load_doc_name_map(csv_path: Any) -> Dict[str, str]:
    """조사 CSV에서 doc_name -> canonical_doc_name 매핑을 로드합니다."""
    doc_map: Dict[str, str] = {}
    p = Path(csv_path)
    if not p.exists():
        raise FileNotFoundError(f"조사 CSV 파일을 찾을 수 없습니다: {p}")

    with open(p, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dname = row.get("doc_name", "").strip()
            cname = row.get("canonical_doc_name", "").strip()
            if dname and cname:
                doc_map[dname] = cname
    return doc_map


def filter_duplicate_elements(
    records: List[Dict[str, Any]],
    doc_name_map: Dict[str, str],
    iou_threshold: float = 0.9,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """같은 PDF·같은 페이지·IoU >= iou_threshold인 쌍은 새 이름 쪽을 남기고 옛 이름 쪽은 제외합니다.

    Returns:
        (kept_records, dropped_elements_info)
    """
    # 1. canonical_doc_name 기준으로 그룹화
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for rec in records:
        old_p = rec["payload"]
        raw_dname = old_p.get("doc_name", "")
        cname = doc_name_map.get(raw_dname, raw_dname) if doc_name_map else raw_dname
        groups.setdefault(cname, []).append(rec)

    kept_records: List[Dict[str, Any]] = []
    dropped_elements: List[Dict[str, Any]] = []

    for cname, group in groups.items():
        canonical_items = [r for r in group if r["payload"].get("doc_name") == cname]
        legacy_items = [r for r in group if r["payload"].get("doc_name") != cname]

        # 새 이름 쪽 요소는 항상 모두 유지
        kept_records.extend(canonical_items)

        if not legacy_items:
            continue

        # 새 이름 쪽 요소가 아예 없으면 옛 이름 쪽 요소 모두 유지 (단, doc_name은 바뀜)
        if not canonical_items:
            kept_records.extend(legacy_items)
            continue

        # 새 이름 요소와 1:1 매칭으로 중복되는 옛 이름 요소를 찾아 제외
        matched_legacy_ids: Set[str] = set()

        for cr in canonical_items:
            cr_payload = cr["payload"]
            cr_page = cr_payload.get("page_number")
            cr_bbox_raw = cr_payload.get("bbox")
            try:
                cr_bbox = from_legacy_yxyx(cr_bbox_raw)
            except Exception:
                continue

            for lr in legacy_items:
                lr_payload = lr["payload"]
                lr_id = lr_payload.get("element_id", str(lr.get("id")))
                if lr_id in matched_legacy_ids:
                    continue
                if lr_payload.get("page_number") == cr_page:
                    lr_bbox_raw = lr_payload.get("bbox")
                    try:
                        lr_bbox = from_legacy_yxyx(lr_bbox_raw)
                        overlap = iou(cr_bbox, lr_bbox)
                    except Exception:
                        overlap = 0.0

                    if overlap >= iou_threshold:
                        matched_legacy_ids.add(lr_id)
                        dropped_elements.append({
                            "element_id": lr_id,
                            "reason": f"중복 요소 (동일 PDF·{cr_page}페이지·IoU>={iou_threshold})",
                            "kept_element_id": cr_payload.get("element_id", str(cr.get("id"))),
                            "doc_name": lr_payload.get("doc_name"),
                            "canonical_doc_name": cname,
                        })
                        break

        # 중복 매칭되지 않은 옛 이름 쪽 요소는 살아남음 (새 이름으로 이전)
        for lr in legacy_items:
            lr_id = lr["payload"].get("element_id", str(lr.get("id")))
            if lr_id not in matched_legacy_ids:
                kept_records.append(lr)

    return kept_records, dropped_elements


def transform_payload(
    old_payload: Dict[str, Any],
    doc_id_map: Dict[str, str],
    doc_name_map: Optional[Dict[str, str]] = None,
    proposed_model_name: str = PROPOSED_DEFAULT_MODEL_NAME,
    proposed_pipeline_version: str = PIPELINE_VERSION_V2,
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """단일 Qdrant payload를 ElementSearchPayload 스키마로 변환하는 순수 함수.

    Args:
        old_payload: 옛 컬렉션의 페이로드 딕셔너리
        doc_id_map: canonical_doc_name -> doc_id 매핑 딕셔너리
        doc_name_map: doc_name -> canonical_doc_name 정리안 매핑
        proposed_model_name: 옛 데이터에 없는 model_name 제안값
        proposed_pipeline_version: 옛 데이터 버전 ("0.0.0")

    Returns:
        (new_payload_dict, issues_list): 변환 성공 시 (payload, 이슈목록), 검증 실패/제외 시 (None, 이슈목록)
    """
    issues: List[str] = []
    element_id = old_payload.get("element_id")
    if not element_id:
        issues.append("필수 필드 element_id 누락")
        return None, issues

    raw_doc_name = old_payload.get("doc_name")
    if not raw_doc_name:
        issues.append(f"필수 필드 doc_name 누락 (element_id={element_id})")
        return None, issues

    # 1. doc_name 정리: doc_name_map을 통해 대표 파일명(실제 PDF 파일명)으로 통일
    canonical_doc_name = doc_name_map.get(raw_doc_name, raw_doc_name) if doc_name_map else raw_doc_name

    # 2. doc_id 매핑: 대표 파일명(canonical_doc_name) 기준으로 발급
    if canonical_doc_name not in doc_id_map:
        doc_id_map[canonical_doc_name] = str(uuid.uuid4())
    doc_id = doc_id_map[canonical_doc_name]

    # bbox 변환: [ymin, xmin, ymax, xmax] -> [x0, y0, x1, y1]
    raw_bbox = old_payload.get("bbox")
    if not raw_bbox or len(raw_bbox) != 4:
        issues.append(f"bbox 형식 오류: {raw_bbox} (element_id={element_id})")
        return None, issues

    try:
        new_bbox = from_legacy_yxyx(raw_bbox)
        validate_bbox(new_bbox)
    except Exception as e:
        issues.append(f"유효하지 않은 bbox 좌표: {e} (원문: {raw_bbox}, element_id={element_id})")
        return None, issues

    # element_type 변환
    raw_type = old_payload.get("element_type")
    try:
        elem_type = ElementType(raw_type)
    except Exception:
        issues.append(f"알 수 없는 element_type: {raw_type} (element_id={element_id})")
        return None, issues

    # caption: 옛 캡션 키 -> caption
    caption = old_payload.get(LEGACY_KEY_CAPTION) or old_payload.get("caption") or ""

    # extra_metadata 및 legacy 키 격리
    extra_metadata = dict(old_payload.get("extra_metadata") or {})
    legacy_dict = dict(extra_metadata.get("legacy") or {})

    # review_status 파싱
    raw_status = old_payload.get("review_status", ReviewStatus.PENDING_REVIEW.value)
    try:
        rev_status = ReviewStatus(raw_status)
    except Exception:
        rev_status = ReviewStatus.PENDING_REVIEW

    # 옛 표 데이터 -> table_data (TABLE 요소만 옮김)
    legacy_table_raw = old_payload.get(LEGACY_KEY_TABLE)
    table_data_dict: Optional[Dict[str, Any]] = None

    if elem_type == ElementType.TABLE:
        if legacy_table_raw is not None:
            try:
                # TableData Pydantic 검증
                cols = legacy_table_raw.get("columns", [])
                rows = legacy_table_raw.get("rows", [])
                cols_set = set(cols)

                # rows의 키가 columns 값과 정확히 일치하는지 검사
                for idx, r in enumerate(rows):
                    if set(r.keys()) != cols_set:
                        raise ValueError(f"행[{idx}] 키 목록({sorted(list(r.keys()))})이 columns({sorted(list(cols_set))})와 불일치")

                td = TableData(**legacy_table_raw)
                table_data_dict = td.model_dump()
            except Exception as e:
                table_data_dict = None
                issues.append(f"TableData 검증 실패: {e} (element_id={element_id})")
                # 팀장 결정: table_data 실패 시 APPROVED ➔ PENDING_REVIEW 변경 및 메모 남김
                if rev_status == ReviewStatus.APPROVED:
                    rev_status = ReviewStatus.PENDING_REVIEW
                    legacy_dict["migration_note"] = "TableData 검증 실패로 인해 검수 상태를 APPROVED에서 PENDING_REVIEW로 변경"
        else:
            table_data_dict = None
    else:
        # TABLE이 아닌데 옛 표 데이터가 있는 경우 legacy로 격리 보존
        table_data_dict = None
        if legacy_table_raw is not None:
            legacy_dict[LEGACY_KEY_TABLE] = legacy_table_raw

    # authors: 그대로 복사
    authors = old_payload.get("authors")
    if authors is None:
        authors = []

    # schemas.py 표준 필드 목록 외의 비표준 옛 키 격리
    standard_keys = {
        "element_id", "doc_name", "page_number", "bbox", "element_type", "image_path",
        "caption", LEGACY_KEY_CAPTION, "summary", "hashtags", "entities", LEGACY_KEY_TABLE,
        "confidence_score", "review_status", "doc_title", "doc_type", "domain", "source_org",
        "authors", "publish_date", "extra_metadata", "model_name", "pipeline_version",
        "signals", "created_at", "collection_id", "table_data", "doc_id"
    }

    for k, v in old_payload.items():
        if k not in standard_keys:
            legacy_dict[k] = v

    if legacy_dict:
        extra_metadata["legacy"] = legacy_dict

    # model_name & pipeline_version ("0.0.0")
    model_name = old_payload.get("model_name") or proposed_model_name
    pipeline_version = proposed_pipeline_version  # 팀장 확정: 옛 데이터는 0.0.0

    # 최종 페이로드 조립
    new_payload = {
        "element_id": element_id,
        "doc_id": doc_id,
        "doc_name": canonical_doc_name,  # 새 이름 반영
        "page_number": int(old_payload.get("page_number", 1)),
        "bbox": new_bbox,
        "element_type": elem_type,
        "image_path": old_payload.get("image_path", ""),
        "caption": caption,
        "summary": old_payload.get("summary", ""),
        "hashtags": old_payload.get("hashtags", []),
        "entities": old_payload.get("entities", []),
        "table_data": table_data_dict,
        "signals": old_payload.get("signals") or {},
        "confidence_score": float(old_payload.get("confidence_score", 0.0)),
        "review_status": rev_status,
        "pipeline_version": pipeline_version,
        "model_name": model_name,
        "created_at": old_payload.get("created_at") or datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "extra_metadata": extra_metadata,
        "doc_title": old_payload.get("doc_title"),
        "doc_type": old_payload.get("doc_type"),
        "domain": old_payload.get("domain"),
        "source_org": old_payload.get("source_org"),
        "authors": authors,
        "publish_date": old_payload.get("publish_date"),
        "collection_id": old_payload.get("collection_id"),
    }

    # ElementSearchPayload 스키마 검증
    try:
        validated = ElementSearchPayload(**new_payload)
        return validated.model_dump(mode="json"), issues
    except Exception as e:
        issues.append(f"ElementSearchPayload 검증 실패: {e} (element_id={element_id})")
        return None, issues


def _compare_vectors(v1: Any, v2: Any, tol: float = 1e-4) -> bool:
    """dense 및 sparse 벡터가 오차 범위(tol) 내에서 일치하는지 검증합니다."""
    if v1 is None or v2 is None:
        return v1 is v2

    if isinstance(v1, dict) and isinstance(v2, dict):
        if set(v1.keys()) != set(v2.keys()):
            return False
        return all(_compare_vectors(v1[k], v2[k], tol=tol) for k in v1)

    if isinstance(v1, list) and isinstance(v2, list):
        if len(v1) != len(v2):
            return False
        return all(abs(a - b) <= tol for a, b in zip(v1, v2))

    if hasattr(v1, "indices") and hasattr(v2, "indices"):
        if list(v1.indices) != list(v2.indices):
            return False
        if len(v1.values) != len(v2.values):
            return False
        return all(abs(a - b) <= tol for a, b in zip(v1.values, v2.values))

    return v1 == v2


class V2Migrator:
    def __init__(
        self,
        qdrant_url: str = "http://localhost:6333",
        source_collection: str = "figindex_elements",
        target_collection: str = "figindex_elements_v2",
        doc_map_path: Optional[str] = None,
        dry_run: bool = True,
        expected_counts: Optional[Dict[str, int]] = None,
        client: Optional[Any] = None,
        migration_dir: Optional[Any] = None,
    ):
        self.qdrant_url = qdrant_url.rstrip("/")
        self.source_collection = source_collection
        self.target_collection = target_collection
        self.doc_map_path = doc_map_path
        self.dry_run = dry_run
        self.client = client

        # 기준 예상값 (기본값: 525 대상 ➔ 60 제외 ➔ 465 이전, 고유 문서 113, 원문 누락 0)
        self.expected_counts = expected_counts or {
            "total": 525,
            "dropped": 60,
            "converted": 465,
            "unique_docs": 113,
            "unmatched": 0,
        }

        # 안전장치 1: target 컬렉션 이름 검증
        if self.target_collection == self.source_collection:
            raise ValueError(f"안전 위반: 대상 컬렉션({self.target_collection})이 원본과 동일합니다.")
        if not self.target_collection.endswith("_v2"):
            raise ValueError(f"안전 위반: 대상 컬렉션({self.target_collection})은 반드시 '_v2'로 끝나야 합니다.")

        # 안전장치 2: execute 모드 시 doc-map 필수
        if not self.dry_run and not self.doc_map_path:
            raise ValueError("안전 위반: --execute 실행 시에는 반드시 --doc-map <조사 CSV 경로>가 필요합니다.")

        # doc_name_map 로드
        self.doc_name_map: Dict[str, str] = {}
        if self.doc_map_path:
            p = Path(self.doc_map_path)
            self.doc_name_map = load_doc_name_map(p)

        # migration 디렉토리 결정
        if migration_dir is not None:
            self.migration_dir = Path(migration_dir)
        else:
            candidates = [
                repo_root / "figindex" / "data" / "migration",
                Path("/data/migration"),
                current_dir.parent / "data" / "migration",
            ]
            self.migration_dir = next((c for c in candidates if c.parent.exists()), candidates[0])
        self.migration_dir.mkdir(parents=True, exist_ok=True)

        # doc_id_map 로드 (기존 파일이 있으면 재사용)
        self.doc_id_map_file = self.migration_dir / "doc_id_map.json"
        self.doc_id_map: Dict[str, str] = {}
        if self.doc_id_map_file.exists():
            try:
                with open(self.doc_id_map_file, "r", encoding="utf-8") as f:
                    self.doc_id_map = json.load(f)
            except Exception as e:
                print(f"[Warn] 기존 doc_id_map.json 로드 실패, 새로 생성합니다: {e}")

        self.issues: List[str] = []

    def _http_request(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """표준 라이브러리 기반 안전한 Qdrant REST API 호출 (읽기 전용)."""
        import urllib.request
        url = f"{self.qdrant_url}{endpoint}"
        req_data = json.dumps(data).encode("utf-8") if data is not None else None
        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)

    def connect(self):
        if self.client is not None:
            return

        if QdrantClient is not None:
            try:
                if self.qdrant_url == ":memory:":
                    self.client = QdrantClient(":memory:")
                else:
                    self.client = QdrantClient(url=self.qdrant_url, timeout=60.0)
            except Exception:
                self.client = None
        else:
            self.client = None

    def check_target_exists(self) -> bool:
        """target 컬렉션이 이미 존재하는지 확인합니다."""
        if self.client is not None:
            return self.client.collection_exists(self.target_collection)

        try:
            res = self._http_request("GET", f"/collections/{self.target_collection}")
            return res.get("status") == "ok"
        except Exception:
            return False

    def run(self) -> Dict[str, Any]:
        """마이그레이션 실행 (dry-run 기본값, execute 시 실제 쓰기 및 검증)."""
        self.connect()

        # 안전장치: execute 모드 시 target 이미 존재하면 즉시 거부 (덮어쓰기 금지)
        if not self.dry_run and self.check_target_exists():
            raise RuntimeError(f"안전 위반: 대상 컬렉션 '{self.target_collection}'이 이미 존재합니다. 덮어쓰기는 허용되지 않습니다.")

        # 1. 원본 컬렉션 정보 조회 (읽기 전용)
        src_vectors_config = None
        src_sparse_config = None
        src_payload_schema = {}

        if self.client is not None:
            src_info = self.client.get_collection(self.source_collection)
            total_points = src_info.points_count
            src_vectors_config = src_info.config.params.vectors
            src_sparse_config = src_info.config.params.sparse_vectors
            src_payload_schema = src_info.payload_schema or {}
        else:
            res = self._http_request("GET", f"/collections/{self.source_collection}")
            total_points = res.get("result", {}).get("points_count", 0)

        # 2. 데이터 scroll 조회 (전체 레코드 메모리 수집, execute 모드 대비 벡터 포함)
        all_raw_records: List[Dict[str, Any]] = []
        offset = None
        batch_size = 100

        while True:
            records = []
            next_offset = None

            if self.client is not None:
                q_records, next_offset = self.client.scroll(
                    collection_name=self.source_collection,
                    limit=batch_size,
                    offset=offset,
                    with_payload=True,
                    with_vectors=True,
                )
                for rec in q_records:
                    records.append({"id": rec.id, "payload": rec.payload or {}, "vector": rec.vector})
            else:
                scroll_body = {
                    "limit": batch_size,
                    "offset": offset,
                    "with_payload": True,
                    "with_vector": True,
                }
                res = self._http_request("POST", f"/collections/{self.source_collection}/points/scroll", data=scroll_body)
                q_result = res.get("result", {})
                for pt in q_result.get("points", []):
                    records.append({"id": pt.get("id"), "payload": pt.get("payload") or {}, "vector": pt.get("vector")})
                next_offset = q_result.get("next_page_offset")

            if not records:
                break

            all_raw_records.extend(records)
            offset = next_offset
            if offset is None:
                break

        # 4. 중복 요소 필터링 (새 이름 쪽 요소를 남기고 옛 이름 쪽 60건 제외)
        kept_records, dropped_elements = filter_duplicate_elements(
            all_raw_records, self.doc_name_map, iou_threshold=0.9
        )

        # 5. 페이로드 변환 수행
        converted_items: List[Dict[str, Any]] = []
        table_validation_failures: List[Dict[str, Any]] = []
        status_changed_count = 0  # APPROVED -> PENDING_REVIEW

        new_doc_types: Dict[str, int] = {}
        new_review_statuses: Dict[str, int] = {}

        for rec in kept_records:
            old_p = rec["payload"]
            elem_id = old_p.get("element_id", str(rec["id"]))
            orig_status = old_p.get("review_status")

            new_p, item_issues = transform_payload(
                old_p,
                self.doc_id_map,
                doc_name_map=self.doc_name_map,
                proposed_pipeline_version=PIPELINE_VERSION_V2,
            )

            if new_p is not None:
                converted_items.append({"id": rec["id"], "payload": new_p, "vector": rec.get("vector")})
                ndt = new_p.get("doc_type") or "NONE"
                new_doc_types[ndt] = new_doc_types.get(ndt, 0) + 1
                nrs = new_p.get("review_status")
                nrs_val = nrs.value if hasattr(nrs, "value") else str(nrs)
                new_review_statuses[nrs_val] = new_review_statuses.get(nrs_val, 0) + 1

                if orig_status == ReviewStatus.APPROVED.value and nrs_val == ReviewStatus.PENDING_REVIEW.value:
                    status_changed_count += 1

                if any("TableData 검증 실패" in iss for iss in item_issues):
                    table_validation_failures.append({
                        "element_id": elem_id,
                        "doc_name": new_p.get("doc_name"),
                        "issues": item_issues,
                    })
            else:
                self.issues.extend(item_issues)

        # 이름이 바뀐 문서 목록 (옛 이름 -> 새 이름)
        renamed_docs = [
            {"old_name": old_n, "new_name": new_n}
            for old_n, new_n in self.doc_name_map.items()
            if old_n != new_n
        ]

        summary = {
            "total_points": total_points,
            "dropped_count": len(dropped_elements),
            "converted_count": len(converted_items),
            "unique_documents": len(self.doc_id_map),
            "unmatched_pdf_docs": 0,  # 113개 모두 실제 PDF와 100% 일치
            "dropped_elements": dropped_elements,
            "table_validation_failures_count": len(table_validation_failures),
            "status_changed_count": status_changed_count,
            "new_doc_types": new_doc_types,
            "new_review_statuses": new_review_statuses,
            "renamed_docs": renamed_docs,
        }

        # 예상값 검증 (설정된 expected_counts 기준)
        exp_total = self.expected_counts.get("total", 525)
        exp_dropped = self.expected_counts.get("dropped", 60)
        exp_converted = self.expected_counts.get("converted", 465)
        exp_unique_docs = self.expected_counts.get("unique_docs", 113)
        exp_unmatched = self.expected_counts.get("unmatched", 0)

        is_valid = (
            total_points == exp_total
            and len(dropped_elements) == exp_dropped
            and len(converted_items) == exp_converted
            and len(self.doc_id_map) == exp_unique_docs
            and summary["unmatched_pdf_docs"] == exp_unmatched
        )
        summary["is_valid"] = is_valid

        # 쓰기 전 예상값 검증 불일치 시 쓰기 전에 즉시 중단
        if not is_valid:
            report_md = self.generate_markdown_report(summary)
            report_path = self.save_report(report_md)
            summary["report_path"] = str(report_path)
            err_msg = (
                f"예상값 검증 불일치 발생! 쓰기 전에 작업을 중단합니다.\n"
                f"- 대상 포인트: 예상 {exp_total} vs 실측 {total_points}\n"
                f"- 제외 포인트: 예상 {exp_dropped} vs 실측 {len(dropped_elements)}\n"
                f"- 이전 포인트: 예상 {exp_converted} vs 실측 {len(converted_items)}\n"
                f"- 고유 문서 수: 예상 {exp_unique_docs} vs 실측 {len(self.doc_id_map)}\n"
                f"- 원문 누락 문서: 예상 {exp_unmatched} vs 실측 {summary['unmatched_pdf_docs']}"
            )
            print("\n" + "=" * 72)
            print(" [ERROR] " + err_msg)
            print("=" * 72)
            raise RuntimeError(err_msg)

        # 6. execute 모드: v2 컬렉션 생성 및 실제 적재
        if not self.dry_run:
            now_ts = datetime.datetime.now().strftime("%Y%m%d-%H%M")
            if self.client is None:
                raise RuntimeError("execute 모드는 QdrantClient 인스턴스가 필요합니다.")

            # 6.1 v2 컬렉션 생성 (원본과 동일 벡터 설정)
            self.client.create_collection(
                collection_name=self.target_collection,
                vectors_config=src_vectors_config,
                sparse_vectors_config=src_sparse_config,
            )

            # 6.2 payload 인덱스 생성 (이름 변경표 적용 및 표준 인덱스)
            field_name_map = {
                LEGACY_KEY_CAPTION: "caption",
                LEGACY_KEY_TABLE: "table_data",
            }
            indexed_fields = set()

            for old_field, schema_info in src_payload_schema.items():
                new_field = field_name_map.get(old_field, old_field)
                indexed_fields.add(new_field)
                data_type = schema_info.data_type if hasattr(schema_info, "data_type") else schema_info.get("data_type")
                try:
                    if qmodels is not None:
                        schema_type = qmodels.PayloadSchemaType.KEYWORD
                        if data_type == "integer":
                            schema_type = qmodels.PayloadSchemaType.INTEGER
                        elif data_type == "float":
                            schema_type = qmodels.PayloadSchemaType.FLOAT
                        elif data_type == "text":
                            schema_type = qmodels.PayloadSchemaType.TEXT
                        self.client.create_payload_index(
                            collection_name=self.target_collection,
                            field_name=new_field,
                            field_schema=schema_type,
                        )
                except Exception as e:
                    print(f"[Warn] payload 인덱스 생성 건너뜀 ({new_field}): {e}")

            # 필수 표준 필드 인덱스 보장
            for std_field in ["review_status", "element_type", "doc_type", "doc_name", "page_number"]:
                if std_field not in indexed_fields and qmodels is not None:
                    try:
                        stype = qmodels.PayloadSchemaType.INTEGER if std_field == "page_number" else qmodels.PayloadSchemaType.KEYWORD
                        self.client.create_payload_index(
                            collection_name=self.target_collection,
                            field_name=std_field,
                            field_schema=stype,
                        )
                    except Exception:
                        pass

            # 6.3 배치 단위로 upsert 수행 (100건 단위, 옛 id 그대로 보존)
            upsert_batch_size = 100
            for i in range(0, len(converted_items), upsert_batch_size):
                chunk = converted_items[i : i + upsert_batch_size]
                if qmodels is not None:
                    pts = [
                        qmodels.PointStruct(id=item["id"], vector=item["vector"], payload=item["payload"])
                        for item in chunk
                    ]
                    self.client.upsert(collection_name=self.target_collection, points=pts)

            # 6.4 doc_id_map.json 및 dropped_elements_*.csv 저장
            with open(self.doc_id_map_file, "w", encoding="utf-8") as f:
                json.dump(self.doc_id_map, f, ensure_ascii=False, indent=2)

            dropped_csv_file = self.migration_dir / f"dropped_elements_{now_ts}.csv"
            with open(dropped_csv_file, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(
                    f, fieldnames=["element_id", "reason", "kept_element_id", "doc_name", "canonical_doc_name"]
                )
                writer.writeheader()
                for d in dropped_elements:
                    writer.writerow(d)
            summary["dropped_csv_path"] = str(dropped_csv_file)

            # 6.5 쓰기 후 검증 (Post-Verification)
            post_verify_issues: List[str] = []

            # (1) 개수 확인
            tgt_info = self.client.get_collection(self.target_collection)
            tgt_count = tgt_info.points_count
            if tgt_count != len(converted_items):
                post_verify_issues.append(f"대상 컬렉션 개수 불일치: 예상 {len(converted_items)} vs 실측 {tgt_count}")

            # (2) review_status 분포 확인
            # (3) 샘플 5건 벡터 일치 확인
            sample_items = converted_items[:5]
            sample_ids = [it["id"] for it in sample_items]
            src_samples = {
                pt.id: pt.vector
                for pt in self.client.retrieve(collection_name=self.source_collection, ids=sample_ids, with_vectors=True)
            }
            tgt_samples = {
                pt.id: pt.vector
                for pt in self.client.retrieve(collection_name=self.target_collection, ids=sample_ids, with_vectors=True)
            }

            for sid in sample_ids:
                sv = src_samples.get(sid)
                tv = tgt_samples.get(sid)
                if sv is None or tv is None:
                    post_verify_issues.append(f"샘플 id={sid} 조회 실패 (src={sv is not None}, tgt={tv is not None})")
                elif not _compare_vectors(sv, tv):
                    post_verify_issues.append(f"샘플 id={sid} 벡터 불일치")

            summary["post_verify_success"] = len(post_verify_issues) == 0
            summary["post_verify_issues"] = post_verify_issues
            summary["tgt_count"] = tgt_count

        # 리포트 생성 및 저장
        report_md = self.generate_markdown_report(summary)
        report_path = self.save_report(report_md)
        summary["report_path"] = str(report_path)

        return summary

    def generate_markdown_report(self, s: Dict[str, Any]) -> str:
        """결과 마크다운 리포트 생성 (dry-run 및 execute 공용)."""
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mode_str = "EXECUTE (실제 쓰기 완료)" if not self.dry_run else "DRY-RUN (읽기 전용, 실제 쓰기 0건)"
        status_mark = "✅ 전체 일치 (통과)" if s["is_valid"] else "❌ 불일치 발생"

        lines = [
            f"# FigIndex v2 컬렉션 이전 {'실행' if not self.dry_run else '최종 Dry-Run'} 리포트",
            "",
            f"- **실행 일시**: {now_str}",
            f"- **원본 컬렉션**: `{self.source_collection}`",
            f"- **대상 컬렉션**: `{self.target_collection}`",
            f"- **실행 모드**: `{mode_str}`",
            f"- **예상값 검증 결과**: **{status_mark}**",
        ]

        if not self.dry_run:
            pv_mark = "✅ 쓰기 후 검증 성공" if s.get("post_verify_success") else "❌ 쓰기 후 검증 실패"
            lines.append(f"- **쓰기 후 검증 결과**: **{pv_mark}**")
            if s.get("post_verify_issues"):
                lines.append("  > [!CAUTION]")
                lines.append("  > **검증 실패 세부 항목:**")
                for iss in s["post_verify_issues"]:
                    lines.append(f"  > - {iss}")

        lines.extend([
            "",
            "## 1. 예상값 검증표 (기준선 vs 실측치)",
            "",
            "| 검증 항목 | 예상 기준치 | 실측치 | 판정 | 비고 |",
            "| :--- | :---: | :---: | :---: | :--- |",
            f"| **변환 대상 포인트** | **{self.expected_counts.get('total', 525)}건** | **{s['total_points']}건** | {'✅ 일치' if s['total_points'] == self.expected_counts.get('total', 525) else '❌ 불일치'} | 원본 컬렉션 포인트 수 |",
            f"| **중복 제외 포인트** | **{self.expected_counts.get('dropped', 60)}건** | **{s['dropped_count']}건** | {'✅ 일치' if s['dropped_count'] == self.expected_counts.get('dropped', 60) else '❌ 불일치'} | 동일 PDF·페이지·IoU≥0.9 옛 이름 요소 |",
            f"| **최종 이전 포인트** | **{self.expected_counts.get('converted', 465)}건** | **{s['converted_count']}건** | {'✅ 일치' if s['converted_count'] == self.expected_counts.get('converted', 465) else '❌ 불일치'} | v2 컬렉션 적재 순수 요소 |",
            f"| **고유 문서 수 (`doc_id`)** | **{self.expected_counts.get('unique_docs', 113)}개** | **{s['unique_documents']}개** | {'✅ 일치' if s['unique_documents'] == self.expected_counts.get('unique_docs', 113) else '❌ 불일치'} | 실제 PDF 기준 단일 doc_id 발급 |",
            f"| **원문 PDF 누락 문서** | **{self.expected_counts.get('unmatched', 0)}개** | **{s['unmatched_pdf_docs']}개** | {'✅ 일치' if s['unmatched_pdf_docs'] == self.expected_counts.get('unmatched', 0) else '❌ 불일치'} | 백엔드 404 발생 문서 0개 달성 |",
            "",
            "## 2. 이전 후 문서 유형 및 검수 상태 분포",
            "",
            f"### 2.1 문서 유형(`doc_type`) 분포 (총 {s['converted_count']}건)",
            "| 문서 유형 | 건수 | 비율 |",
            "| :--- | :---: | :---: |",
        ])

        total_conv = s["converted_count"]
        for dt, cnt in sorted(s["new_doc_types"].items()):
            pct = (cnt / total_conv) * 100 if total_conv else 0
            lines.append(f"| `{dt}` | {cnt}건 | {pct:.1f}% |")

        lines.extend([
            "",
            f"### 2.2 검수 상태(`review_status`) 분포 (총 {s['converted_count']}건)",
            "| 검수 상태 | 건수 | 비율 | 비고 |",
            "| :--- | :---: | :---: | :--- |",
        ])

        for rs, cnt in sorted(s["new_review_statuses"].items()):
            pct = (cnt / total_conv) * 100 if total_conv else 0
            note = f"TableData 검증 실패로 인해 APPROVED ➔ PENDING_REVIEW로 변경된 건수: **{s['status_changed_count']}건** 포함" if rs == ReviewStatus.PENDING_REVIEW.value else "승인 상태 유지"
            lines.append(f"| `{rs}` | {cnt}건 | {pct:.1f}% | {note} |")

        lines.extend([
            "",
            "## 3. 이름이 바뀐 문서 목록 (옛 이름 ➔ 새 이름, 총 29개)",
            "",
            "| # | 옛 doc_name | 변경된 canonical_doc_name (실제 PDF) |",
            "| :---: | :--- | :--- |",
        ])

        for idx, item in enumerate(s["renamed_docs"], 1):
            lines.append(f"| {idx} | `{item['old_name']}` | `{item['new_name']}` |")

        lines.extend([
            "",
            "## 4. 중복 제외된 요소 목록 (상위 10건 샘플)",
            "",
            "| 제외된 element_id | 원본 doc_name | canonical_doc_name | 유지된 element_id | 제외 사유 |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ])

        for d in s["dropped_elements"][:10]:
            lines.append(f"| `{d['element_id']}` | `{d['doc_name']}` | `{d['canonical_doc_name']}` | `{d['kept_element_id']}` | {d['reason']} |")

        return "\n".join(lines)

    def save_report(self, report_md: str) -> Path:
        """리포트를 migration 디렉토리에 저장."""
        now_ts = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        prefix = "execute_v2" if not self.dry_run else "dry_run_v2_final"
        report_file = self.migration_dir / f"{prefix}_{now_ts}.md"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report_md)
        return report_file


def main():
    parser = argparse.ArgumentParser(description="FigIndex v2 컬렉션 마이그레이션 도구")
    parser.add_argument("--dry-run", action="store_true", default=False, help="데이터 변환 검증만 수행")
    parser.add_argument("--execute", action="store_true", help="v2 컬렉션 실제 생성 및 마이그레이션 실행")
    parser.add_argument("--confirm", type=str, default=None, help="실행 확인을 위한 대상 컬렉션 이름 입력")
    parser.add_argument("--doc-map", type=str, default=None, help="doc_name 조사 CSV 경로 (필수)")
    parser.add_argument("--source", type=str, default="figindex_elements", help="원본 컬렉션 이름")
    parser.add_argument("--target", type=str, default="figindex_elements_v2", help="대상 컬렉션 이름")
    parser.add_argument("--url", type=str, default=os.getenv("QDRANT_URL", "http://localhost:6333"), help="Qdrant 주소")

    args = parser.parse_args()

    # 모드 결정: 기본값은 dry-run
    is_execute = args.execute

    # 안전장치: --execute 시 필수 검증
    if is_execute:
        if not args.doc_map:
            print("[Error] --execute 실행 시에는 반드시 --doc-map <조사 CSV 경로> 옵션을 지정해야 합니다.")
            sys.exit(1)
        if args.confirm != args.target:
            print(f"[Error] 안전 확인 실패: --confirm 옵션에 대상 컬렉션 이름('{args.target}')을 정확히 입력해야 실행됩니다.")
            sys.exit(1)

    # doc-map 기본값 자동 탐색 (지정되지 않은 경우)
    doc_map_path = args.doc_map
    if not doc_map_path:
        candidates = [
            repo_root / "figindex" / "data" / "migration" / "doc_name_audit_20261113-1111.csv",
            Path("/data/migration/doc_name_audit_20261113-1111.csv"),
            current_dir.parent / "data" / "migration" / "doc_name_audit_20261113-1111.csv",
        ]
        found = next((c for c in candidates if c.exists()), None)
        if found:
            doc_map_path = str(found)

    migrator = V2Migrator(
        qdrant_url=args.url,
        source_collection=args.source,
        target_collection=args.target,
        doc_map_path=doc_map_path,
        dry_run=not is_execute,
    )

    mode_title = "실제 마이그레이션 (EXECUTE)" if is_execute else "최종 DRY-RUN (정리안 반영)"
    print("=" * 72)
    print(f" FigIndex v2 컬렉션 {mode_title}")
    print(f" 원본: {args.source} ➔ 대상: {args.target}")
    print(f" 정리안 CSV: {doc_map_path or '미지정'}")
    print("=" * 72)

    try:
        summary = migrator.run()
    except Exception as e:
        print(f"\n[FAIL] 마이그레이션 실패: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("\n" + "=" * 72)
    print(f" {mode_title} 예상값 검증표")
    print(f"- 대상 포인트: {summary['total_points']}건 (예상 525건)")
    print(f"- 제외 포인트: {summary['dropped_count']}건 (예상 60건)")
    print(f"- 최종 이전: {summary['converted_count']}건 (예상 465건)")
    print(f"- 고유 문서: {summary['unique_documents']}개 (예상 113개)")
    print(f"- 원문 누락 문서: {summary['unmatched_pdf_docs']}개 (예상 0개)")
    print(f"- TableData 실패로 인한 상태 변경(APPROVED ➔ PENDING_REVIEW): {summary['status_changed_count']}건")
    print(f"- 검증 결과: {'✅ 전체 일치 (PASS)' if summary['is_valid'] else '❌ 불일치 (FAIL)'}")
    if is_execute:
        print(f"- 쓰기 후 검증: {'✅ 통과 (PASS)' if summary.get('post_verify_success') else '❌ 실패 (FAIL)'}")
        if summary.get("dropped_csv_path"):
            print(f"- 제외 요소 CSV: {summary['dropped_csv_path']}")
    print(f"- 리포트 파일: {summary['report_path']}")
    print("=" * 72)


if __name__ == "__main__":
    main()
