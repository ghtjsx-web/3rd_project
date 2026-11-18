"""scripts/reextract_empty_tables.py 순수 함수 테스트."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reextract_empty_tables import (  # noqa: E402
    build_crop_info, build_doc_metadata, check_target_collection, select_targets,
)
from shared.schemas import ElementType  # noqa: E402


def _pt(eid, doc="a.pdf", page=1, etype=ElementType.TABLE.value, table=None):
    return {"id": eid, "payload": {"element_id": eid, "doc_name": doc, "page_number": page,
                                   "element_type": etype, "table_data": table,
                                   "image_path": f"/static/crops/{eid}_p{page}.png",
                                   "bbox": [0.1, 0.2, 0.9, 0.6], "caption": "Valuation",
                                   "extra_metadata": {"target": "코스맥스"}, "source_org": "유진투자증권"}}


def test_service_collections_are_refused():
    for name in ("figindex_elements_v2", "figindex_elements", "my_collection"):
        with pytest.raises(SystemExit):
            check_target_collection(name)
    check_target_collection("figindex_test_ryu")


def test_select_only_empty_tables_sorted_and_limited():
    pts = [_pt("b", doc="b.pdf"), _pt("a", doc="a.pdf"),
           _pt("c", table={"columns": ["x"], "rows": [{"x": 1}]}),
           _pt("d", etype=ElementType.CHART.value)]
    assert [p["id"] for p in select_targets(pts, None, None)] == ["a", "b"]
    assert [p["id"] for p in select_targets(pts, None, 1)] == ["a"]
    assert [p["id"] for p in select_targets(pts, ["c"], None)] == ["c"]


def test_crop_info_and_doc_metadata():
    payload = _pt("fig-1", page=4)["payload"]
    info = build_crop_info(payload, Path("/data/crops"), None)
    assert info["crop_path"] == Path("/data/crops/fig-1_p4.png")
    assert info["normalized_box"] == [0.1, 0.2, 0.9, 0.6]
    assert info["hint_type"] == ElementType.TABLE.value
    meta = build_doc_metadata(payload)
    assert meta["target"] == "코스맥스" and meta["source_org"] == "유진투자증권"
