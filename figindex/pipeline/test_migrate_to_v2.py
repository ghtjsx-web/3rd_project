"""
v2 컬렉션 마이그레이션 순수 변환 함수(transform_payload) 단위 테스트.

테스트 케이스:
1. 정상 TABLE (옛 표 데이터 -> table_data 검증 통과)
2. 정상 CHART (table_data 없음)
3. 옛 표 데이터가 없는 TABLE
4. TableData 검증에 실패하는 TABLE (rows의 키 != columns) -> 요소는 살고 table_data=None + issue
5. target이 없는 요소
6. authors가 있는 요소
7. schemas.py에 없는 옛 키 -> extra_metadata["legacy"]
8. bbox 변환: [0.1, 0.2, 0.5, 0.9] -> [0.2, 0.1, 0.9, 0.5]
9. 뒤집힌 bbox -> 제외 + issue
10. 같은 doc_name 두 건 -> 같은 doc_id
"""
import sys
from pathlib import Path
import pytest

# 모듈 경로 추가
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

from shared.schemas import ElementType, ReviewStatus
from migrate_to_v2 import (
    filter_duplicate_elements,
    transform_payload,
    LEGACY_KEY_CAPTION,
    LEGACY_KEY_TABLE,
    V2Migrator,
)

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
except ImportError:
    QdrantClient = None
    qmodels = None


def test_case_1_normal_table():
    """1. 정상 TABLE (옛 표 구조 -> table_data 검증 통과)"""
    old = {
        "element_id": "test-elem-1",
        "doc_name": "test_doc_1.pdf",
        "page_number": 1,
        "bbox": [0.1, 0.2, 0.5, 0.75],
        "element_type": ElementType.TABLE.value,
        LEGACY_KEY_CAPTION: "2026년 실적 요약 표",
        LEGACY_KEY_TABLE: {
            "columns": ["구분", "2025", "2026E"],
            "rows": [
                {"구분": "매출액", "2025": 1000, "2026E": 1200},
                {"구분": "영업이익", "2025": 100, "2026E": 150},
            ],
            "unit": "억원",
            "period_labels": ["2025", "2026E"],
        },
        "confidence_score": 0.95,
        "review_status": ReviewStatus.APPROVED.value,
    }
    doc_id_map = {}
    new_p, issues = transform_payload(old, doc_id_map)

    assert new_p is not None
    assert new_p["element_type"] == ElementType.TABLE
    assert new_p["caption"] == "2026년 실적 요약 표"
    assert new_p["table_data"] is not None
    assert new_p["table_data"]["columns"] == ["구분", "2025", "2026E"]
    assert len(new_p["table_data"]["rows"]) == 2
    assert new_p["table_data"]["unit"] == "억원"
    assert "test_doc_1.pdf" in doc_id_map
    assert new_p["doc_id"] == doc_id_map["test_doc_1.pdf"]


def test_case_2_normal_chart():
    """2. 정상 CHART (table_data 없음)"""
    old = {
        "element_id": "test-elem-2",
        "doc_name": "test_doc_2.pdf",
        "page_number": 2,
        "bbox": [0.2, 0.1, 0.7, 0.9],
        "element_type": ElementType.CHART.value,
        LEGACY_KEY_CAPTION: "분기별 주가 추이",
        LEGACY_KEY_TABLE: None,
        "confidence_score": 0.92,
    }
    doc_id_map = {}
    new_p, issues = transform_payload(old, doc_id_map)

    assert new_p is not None
    assert new_p["element_type"] == ElementType.CHART
    assert new_p["caption"] == "분기별 주가 추이"
    assert new_p["table_data"] is None


def test_case_3_table_without_legacy_table():
    """3. 옛 표 데이터가 없는 TABLE (None으로 안전 변환)"""
    old = {
        "element_id": "test-elem-3",
        "doc_name": "test_doc_3.pdf",
        "page_number": 3,
        "bbox": [0.1, 0.1, 0.4, 0.4],
        "element_type": ElementType.TABLE.value,
        LEGACY_KEY_CAPTION: "빈 표",
        LEGACY_KEY_TABLE: None,
        "confidence_score": 0.85,
    }
    doc_id_map = {}
    new_p, issues = transform_payload(old, doc_id_map)

    assert new_p is not None
    assert new_p["element_type"] == ElementType.TABLE
    assert new_p["table_data"] is None


def test_case_4_table_with_invalid_legacy_table():
    """4. TableData 검증에 실패하는 TABLE (rows의 키 != columns) -> 요소는 살고 table_data=None + issue"""
    old = {
        "element_id": "test-elem-4",
        "doc_name": "test_doc_4.pdf",
        "page_number": 4,
        "bbox": [0.1, 0.1, 0.4, 0.4],
        "element_type": ElementType.TABLE.value,
        LEGACY_KEY_CAPTION: "키 불일치 표",
        LEGACY_KEY_TABLE: {
            "columns": ["구분", "2025"],
            "rows": [
                {"구분": "매출액", "잘못된열이름": 1000}  # 2025가 없음
            ],
            "unit": "억원",
        },
        "confidence_score": 0.85,
    }
    doc_id_map = {}
    new_p, issues = transform_payload(old, doc_id_map)

    # 요소는 살아야 함 (new_p is not None)
    assert new_p is not None
    # table_data는 None이어야 함
    assert new_p["table_data"] is None
    # issues에 검증 실패 사유가 기록되어야 함
    assert any("TableData 검증 실패" in iss for iss in issues)


def test_case_5_element_without_target():
    """5. target이 없는 요소 (extra_metadata에 target이 없어도 정상 통과)"""
    old = {
        "element_id": "test-elem-5",
        "doc_name": "test_doc_5.pdf",
        "page_number": 1,
        "bbox": [0.1, 0.2, 0.3, 0.4],
        "element_type": ElementType.CHART.value,
        "confidence_score": 0.88,
        "extra_metadata": {
            "broker": "테스트증권",
            "company": "테스트기업",
            # target 없음
        },
    }
    doc_id_map = {}
    new_p, issues = transform_payload(old, doc_id_map)

    assert new_p is not None
    assert "target" not in new_p["extra_metadata"]
    assert new_p["extra_metadata"]["broker"] == "테스트증권"


def test_case_6_element_with_authors():
    """6. authors가 있는 요소 (authors가 extra_metadata['legacy']로 가지 않고 최상위에 유지)"""
    old = {
        "element_id": "test-elem-6",
        "doc_name": "test_paper_6.pdf",
        "page_number": 1,
        "bbox": [0.1, 0.2, 0.3, 0.4],
        "element_type": ElementType.DIAGRAM.value,
        "confidence_score": 0.90,
        "authors": ["홍길동", "김철수"],
    }
    doc_id_map = {}
    new_p, issues = transform_payload(old, doc_id_map)

    assert new_p is not None
    assert new_p["authors"] == ["홍길동", "김철수"]
    assert "legacy" not in new_p.get("extra_metadata", {}) or "authors" not in new_p["extra_metadata"]["legacy"]


def test_case_7_unknown_keys_to_legacy():
    """7. schemas.py에 없는 옛 키 -> extra_metadata['legacy']로 보존"""
    old = {
        "element_id": "test-elem-7",
        "doc_name": "test_doc_7.pdf",
        "page_number": 1,
        "bbox": [0.1, 0.2, 0.3, 0.4],
        "element_type": ElementType.CHART.value,
        "confidence_score": 0.85,
        "unknown_old_field": "보존해야할옛값",
        LEGACY_KEY_TABLE: {"some": "data"},  # CHART인데 옛 표 데이터가 있는 경우
    }
    doc_id_map = {}
    new_p, issues = transform_payload(old, doc_id_map)

    assert new_p is not None
    legacy = new_p["extra_metadata"].get("legacy", {})
    assert legacy.get("unknown_old_field") == "보존해야할옛값"
    assert legacy.get(LEGACY_KEY_TABLE) == {"some": "data"}


def test_case_8_bbox_transformation():
    """8. bbox 변환: [0.1, 0.2, 0.5, 0.9] -> [0.2, 0.1, 0.9, 0.5]"""
    # 옛 bbox: [ymin, xmin, ymax, xmax] = [0.1, 0.2, 0.5, 0.9]
    # 새 bbox: [x0, y0, x1, y1] = [0.2, 0.1, 0.9, 0.5]
    old = {
        "element_id": "test-elem-8",
        "doc_name": "test_doc_8.pdf",
        "page_number": 1,
        "bbox": [0.1, 0.2, 0.5, 0.9],
        "element_type": ElementType.CHART.value,
        "confidence_score": 0.91,
    }
    doc_id_map = {}
    new_p, issues = transform_payload(old, doc_id_map)

    assert new_p is not None
    assert new_p["bbox"] == [0.2, 0.1, 0.9, 0.5]


def test_case_9_inverted_bbox_excluded():
    """9. 뒤집힌 bbox -> 제외 (new_p is None) + issue 기록"""
    # ymin > ymax인 뒤집힌 bbox: [0.78, 0.2, 0.3, 0.9] -> new: [0.2, 0.78, 0.9, 0.3] (y0 > y1)
    old = {
        "element_id": "test-elem-9",
        "doc_name": "test_doc_9.pdf",
        "page_number": 1,
        "bbox": [0.78, 0.2, 0.3, 0.9],
        "element_type": ElementType.CHART.value,
        "confidence_score": 0.82,
    }
    doc_id_map = {}
    new_p, issues = transform_payload(old, doc_id_map)

    assert new_p is None
    assert any("유효하지 않은 bbox" in iss for iss in issues)


def test_case_10_same_doc_name_same_doc_id():
    """10. 같은 doc_name 두 건 -> 같은 doc_id 발급"""
    old1 = {
        "element_id": "test-elem-10-1",
        "doc_name": "shared_doc.pdf",
        "page_number": 1,
        "bbox": [0.1, 0.1, 0.4, 0.4],
        "element_type": ElementType.CHART.value,
        "confidence_score": 0.90,
    }
    old2 = {
        "element_id": "test-elem-10-2",
        "doc_name": "shared_doc.pdf",
        "page_number": 2,
        "bbox": [0.2, 0.2, 0.5, 0.5],
        "element_type": ElementType.TABLE.value,
        "confidence_score": 0.90,
    }
    doc_id_map = {}
    new_p1, _ = transform_payload(old1, doc_id_map)
    new_p2, _ = transform_payload(old2, doc_id_map)

    assert new_p1 is not None
    assert new_p2 is not None
    assert new_p1["doc_id"] == new_p2["doc_id"]
    assert new_p1["doc_name"] == "shared_doc.pdf"
    assert len(doc_id_map) == 1


def test_case_11_legacy_to_canonical_doc_name_and_doc_id():
    """11. 옛 이름 -> 새 이름 변환과 doc_id 일치"""
    doc_map = {"BGF리테일1106.pdf": "RPT_20261106_BGF리테일_IBK투자증권.pdf"}
    old1 = {
        "element_id": "elem-legacy",
        "doc_name": "BGF리테일1106.pdf",
        "page_number": 1,
        "bbox": [0.1, 0.1, 0.4, 0.4],
        "element_type": ElementType.CHART.value,
        "confidence_score": 0.90,
    }
    old2 = {
        "element_id": "elem-canonical",
        "doc_name": "RPT_20261106_BGF리테일_IBK투자증권.pdf",
        "page_number": 2,
        "bbox": [0.2, 0.2, 0.5, 0.5],
        "element_type": ElementType.TABLE.value,
        "confidence_score": 0.90,
    }
    doc_id_map = {}
    new_p1, _ = transform_payload(old1, doc_id_map, doc_name_map=doc_map)
    new_p2, _ = transform_payload(old2, doc_id_map, doc_name_map=doc_map)

    assert new_p1 is not None and new_p2 is not None
    assert new_p1["doc_name"] == "RPT_20261106_BGF리테일_IBK투자증권.pdf"
    assert new_p2["doc_name"] == "RPT_20261106_BGF리테일_IBK투자증권.pdf"
    assert new_p1["doc_id"] == new_p2["doc_id"]
    assert len(doc_id_map) == 1


def test_case_12_duplicate_pair_keeps_canonical_only():
    """12. 중복 쌍에서 새 이름 쪽만 남고 옛 이름 쪽은 제외됨"""
    doc_map = {"BGF리테일1106.pdf": "RPT_20261106_BGF리테일_IBK투자증권.pdf"}
    records = [
        {
            "id": 1,
            "payload": {
                "element_id": "elem-canonical",
                "doc_name": "RPT_20261106_BGF리테일_IBK투자증권.pdf",
                "page_number": 1,
                "bbox": [0.1, 0.2, 0.5, 0.75],
                "element_type": ElementType.CHART.value,
            }
        },
        {
            "id": 2,
            "payload": {
                "element_id": "elem-legacy",
                "doc_name": "BGF리테일1106.pdf",
                "page_number": 1,
                "bbox": [0.101, 0.201, 0.501, 0.751],  # IoU >= 0.9 중복
                "element_type": ElementType.CHART.value,
            }
        }
    ]
    kept, dropped = filter_duplicate_elements(records, doc_map, iou_threshold=0.9)
    assert len(kept) == 1
    assert kept[0]["payload"]["element_id"] == "elem-canonical"
    assert len(dropped) == 1
    assert dropped[0]["element_id"] == "elem-legacy"
    assert dropped[0]["kept_element_id"] == "elem-canonical"


def test_case_13_non_duplicate_legacy_element_survives():
    """13. 옛 이름에만 있는 비중복 요소는 새 이름으로 살아남음"""
    doc_map = {"BGF리테일1106.pdf": "RPT_20261106_BGF리테일_IBK투자증권.pdf"}
    records = [
        {
            "id": 1,
            "payload": {
                "element_id": "elem-canonical",
                "doc_name": "RPT_20261106_BGF리테일_IBK투자증권.pdf",
                "page_number": 1,
                "bbox": [0.1, 0.2, 0.5, 0.75],
                "element_type": ElementType.CHART.value,
            }
        },
        {
            "id": 2,
            "payload": {
                "element_id": "elem-legacy-unique",
                "doc_name": "BGF리테일1106.pdf",
                "page_number": 5,  # 다른 페이지 (비중복)
                "bbox": [0.1, 0.2, 0.5, 0.75],
                "element_type": ElementType.CHART.value,
            }
        }
    ]
    kept, dropped = filter_duplicate_elements(records, doc_map, iou_threshold=0.9)
    assert len(kept) == 2
    assert len(dropped) == 0

    doc_id_map = {}
    p1, _ = transform_payload(kept[0]["payload"], doc_id_map, doc_name_map=doc_map)
    p2, _ = transform_payload(kept[1]["payload"], doc_id_map, doc_name_map=doc_map)
    assert p2["doc_name"] == "RPT_20261106_BGF리테일_IBK투자증권.pdf"
    assert p1["doc_id"] == p2["doc_id"]


def test_case_14_table_data_failure_changes_approved_to_pending():
    """14. table_data 검증 실패 + APPROVED -> PENDING_REVIEW 및 migration_note 남김"""
    old = {
        "element_id": "test-elem-fail",
        "doc_name": "test_doc.pdf",
        "page_number": 1,
        "bbox": [0.1, 0.1, 0.4, 0.4],
        "element_type": ElementType.TABLE.value,
        LEGACY_KEY_CAPTION: "실패 표",
        LEGACY_KEY_TABLE: {
            "columns": ["구분", "2025"],
            "rows": [
                {"구분": "매출액", "잘못된열": 1000}
            ],
            "unit": "억원",
        },
        "confidence_score": 0.95,
        "review_status": ReviewStatus.APPROVED.value,
    }
    doc_id_map = {}
    new_p, issues = transform_payload(old, doc_id_map)

    assert new_p is not None
    assert new_p["table_data"] is None
    # APPROVED -> PENDING_REVIEW 변경 검증
    assert new_p["review_status"] == ReviewStatus.PENDING_REVIEW.value
    legacy = new_p["extra_metadata"].get("legacy", {})
    assert "migration_note" in legacy
    assert ReviewStatus.PENDING_REVIEW.value in legacy["migration_note"]


def test_case_15_pipeline_version_is_fixed_legacy():
    """15. pipeline_version == '0.0.0'"""
    old = {
        "element_id": "test-elem-ver",
        "doc_name": "test_doc.pdf",
        "page_number": 1,
        "bbox": [0.1, 0.1, 0.4, 0.4],
        "element_type": ElementType.CHART.value,
        "confidence_score": 0.90,
    }
    doc_id_map = {}
    new_p, _ = transform_payload(old, doc_id_map)

    assert new_p is not None
    assert new_p["pipeline_version"] == "0.0.0"


def _snapshot_migration_dir():
    """실제 migration 폴더의 파일 목록과 수정 시각 스냅샷을 반환합니다."""
    candidates = [
        Path("/data/migration"),
        repo_root / "figindex" / "data" / "migration",
        current_dir.parent / "data" / "migration",
    ]
    real_dir = next((c for c in candidates if c.exists()), None)
    if not real_dir or not real_dir.exists():
        return {}
    return {f.name: f.stat().st_mtime for f in real_dir.iterdir() if f.is_file()}


def test_case_16_execute_in_memory_success(tmp_path):
    """16. execute 모드 QdrantClient(':memory:') 성공 및 원본 불변, v2 생성/벡터/페이로드 검증 (임시 폴더 격리)"""
    if QdrantClient is None or qmodels is None:
        pytest.skip("qdrant_client 모듈이 설치되어 있지 않아 건너뜁니다.")

    snap_before = _snapshot_migration_dir()

    c = QdrantClient(":memory:")
    src_col = "test_elements"
    tgt_col = "test_elements_v2"

    c.create_collection(
        collection_name=src_col,
        vectors_config={"dense": qmodels.VectorParams(size=4, distance=qmodels.Distance.COSINE)},
        sparse_vectors_config={"sparse": qmodels.SparseVectorParams()},
    )

    # 샘플 포인트 3개 (포인트 1: 대표 문서, 포인트 2: 옛 이름 중복, 포인트 3: 옛 이름 비중복)
    sample_points = [
        qmodels.PointStruct(
            id=1,
            vector={
                "dense": [0.1, 0.2, 0.3, 0.4],
                "sparse": qmodels.SparseVector(indices=[1, 3], values=[0.5, 0.9]),
            },
            payload={
                "element_id": "elem-1",
                "doc_name": "RPT_A.pdf",
                "page_number": 1,
                "bbox": [0.1, 0.1, 0.5, 0.5],
                "element_type": ElementType.CHART.value,
                "confidence_score": 0.95,
                "review_status": ReviewStatus.APPROVED.value,
            },
        ),
        qmodels.PointStruct(
            id=2,
            vector={
                "dense": [0.1, 0.2, 0.3, 0.4],
                "sparse": qmodels.SparseVector(indices=[1, 3], values=[0.5, 0.9]),
            },
            payload={
                "element_id": "elem-2",
                "doc_name": "A_old.pdf",
                "page_number": 1,
                "bbox": [0.1, 0.1, 0.5, 0.5],  # 동일 페이지·동일 좌표 -> 중복 제외 대상
                "element_type": ElementType.CHART.value,
                "confidence_score": 0.95,
                "review_status": ReviewStatus.APPROVED.value,
            },
        ),
        qmodels.PointStruct(
            id=3,
            vector={
                "dense": [0.5, 0.6, 0.7, 0.2],
                "sparse": qmodels.SparseVector(indices=[2, 4], values=[0.3, 0.7]),
            },
            payload={
                "element_id": "elem-3",
                "doc_name": "A_old.pdf",
                "page_number": 2,  # 2페이지 -> 비중복 유지 대상
                "bbox": [0.2, 0.2, 0.6, 0.6],
                "element_type": ElementType.CHART.value,
                "confidence_score": 0.95,
                "review_status": ReviewStatus.APPROVED.value,
            },
        ),
    ]
    c.upsert(collection_name=src_col, points=sample_points)

    # doc_name 조사 CSV 작성 (tmp_path에 작성)
    map_csv = tmp_path / "doc_name_audit.csv"
    map_csv.write_text(
        "doc_name,canonical_doc_name,status\n"
        "A_old.pdf,RPT_A.pdf,RENAMED\n",
        encoding="utf-8-sig",
    )

    # migration_dir=tmp_path 전달로 완벽한 임시 폴더 격리
    migrator = V2Migrator(
        client=c,
        source_collection=src_col,
        target_collection=tgt_col,
        doc_map_path=str(map_csv),
        dry_run=False,
        expected_counts={
            "total": 3,
            "dropped": 1,
            "converted": 2,
            "unique_docs": 1,
            "unmatched": 0,
        },
        migration_dir=tmp_path,
    )

    summary = migrator.run()

    # 1. 검증 결과 확인
    assert summary["is_valid"] is True
    assert summary["post_verify_success"] is True

    # 2. 컬렉션 생성 및 개수 확인
    assert c.collection_exists(tgt_col) is True
    src_info = c.get_collection(src_col)
    tgt_info = c.get_collection(tgt_col)
    assert src_info.points_count == 3  # 원본은 그대로 3건 유지 (불변)
    assert tgt_info.points_count == 2  # v2 컬렉션에는 중복 제외 후 2건 적재

    # 3. v2 레코드 페이로드 및 벡터 검증
    tgt_records, _ = c.scroll(collection_name=tgt_col, limit=10, with_payload=True, with_vectors=True)
    assert len(tgt_records) == 2
    for r in tgt_records:
        assert r.payload["doc_name"] == "RPT_A.pdf"
        assert r.payload["pipeline_version"] == "0.0.0"
        # 벡터 보존 확인
        assert "dense" in r.vector
        assert "sparse" in r.vector

    # 4. 임시 폴더에만 파일이 생성되었는지 확인
    assert (tmp_path / "doc_id_map.json").exists()
    assert any(f.name.startswith("dropped_elements_") for f in tmp_path.iterdir())
    assert any(f.name.startswith("execute_v2_") for f in tmp_path.iterdir())

    # 5. 실제 migration 폴더가 전혀 변경되지 않았는지 단언
    snap_after = _snapshot_migration_dir()
    assert snap_before == snap_after, "실제 migration 폴더가 테스트에 의해 변경되었습니다!"


def test_case_17_execute_aborts_if_target_exists(tmp_path):
    """17. target 컬렉션이 이미 존재하면 거부 (덮어쓰기 방지)"""
    if QdrantClient is None or qmodels is None:
        pytest.skip("qdrant_client 모듈이 설치되어 있지 않아 건너뜁니다.")

    snap_before = _snapshot_migration_dir()

    c = QdrantClient(":memory:")
    src_col = "test_src"
    tgt_col = "test_src_v2"

    c.create_collection(
        collection_name=src_col,
        vectors_config={"dense": qmodels.VectorParams(size=4, distance=qmodels.Distance.COSINE)},
    )
    c.create_collection(
        collection_name=tgt_col,
        vectors_config={"dense": qmodels.VectorParams(size=4, distance=qmodels.Distance.COSINE)},
    )

    map_csv = tmp_path / "doc_map.csv"
    map_csv.write_text("doc_name,canonical_doc_name\n", encoding="utf-8-sig")

    migrator = V2Migrator(
        client=c,
        source_collection=src_col,
        target_collection=tgt_col,
        doc_map_path=str(map_csv),
        dry_run=False,
        migration_dir=tmp_path,
    )

    with pytest.raises(RuntimeError, match="이미 존재합니다"):
        migrator.run()

    snap_after = _snapshot_migration_dir()
    assert snap_before == snap_after


def test_case_18_execute_aborts_if_expected_mismatch(tmp_path):
    """18. 예상값과 실측치가 불일치하면 쓰기 전에 중단"""
    if QdrantClient is None or qmodels is None:
        pytest.skip("qdrant_client 모듈이 설치되어 있지 않아 건너뜁니다.")

    snap_before = _snapshot_migration_dir()

    c = QdrantClient(":memory:")
    src_col = "test_src_mismatch"
    tgt_col = "test_src_mismatch_v2"

    c.create_collection(
        collection_name=src_col,
        vectors_config={"dense": qmodels.VectorParams(size=4, distance=qmodels.Distance.COSINE)},
    )
    # 1개 포인트만 등록
    c.upsert(
        collection_name=src_col,
        points=[
            qmodels.PointStruct(
                id=1,
                vector={"dense": [0.1, 0.2, 0.3, 0.4]},
                payload={
                    "element_id": "elem-1",
                    "doc_name": "RPT_A.pdf",
                    "page_number": 1,
                    "bbox": [0.1, 0.1, 0.5, 0.5],
                    "element_type": ElementType.CHART.value,
                    "confidence_score": 0.95,
                    "review_status": ReviewStatus.APPROVED.value,
                },
            )
        ],
    )

    map_csv = tmp_path / "doc_map.csv"
    map_csv.write_text("doc_name,canonical_doc_name\n", encoding="utf-8-sig")

    migrator = V2Migrator(
        client=c,
        source_collection=src_col,
        target_collection=tgt_col,
        doc_map_path=str(map_csv),
        dry_run=False,
        expected_counts={
            "total": 3,  # 실측 1건과 불일치
            "dropped": 0,
            "converted": 3,
            "unique_docs": 1,
            "unmatched": 0,
        },
        migration_dir=tmp_path,
    )

    with pytest.raises(RuntimeError, match="예상값 검증 불일치"):
        migrator.run()

    # 대상 컬렉션이 생성되지 않았는지 확인
    assert c.collection_exists(tgt_col) is False

    snap_after = _snapshot_migration_dir()
    assert snap_before == snap_after


def test_case_19_confirm_flag_check(monkeypatch):
    """19. CLI 실행 시 --confirm 불일치 시 차단 확인"""
    from migrate_to_v2 import main

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "migrate_to_v2.py",
            "--execute",
            "--doc-map",
            "dummy.csv",
            "--target",
            "figindex_elements_v2",
            "--confirm",
            "wrong_target_name",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1

