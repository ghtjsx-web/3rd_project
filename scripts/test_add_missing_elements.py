"""scripts/add_missing_elements.py의 대상 선정·안전장치 테스트 (PyMuPDF·Qdrant 없이)."""
import sys
import unicodedata
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from add_missing_elements import check_target_collection, find_pdf, gt_missing_pages  # noqa: E402

GT_DIR = Path(__file__).resolve().parent.parent / "figindex" / "data" / "gt" / "table"


@pytest.mark.parametrize("name", ["figindex_elements_v2", "figindex_elements", "figindex_test_upload", "my_test"])
def test_service_and_worker_collections_are_refused(name):
    with pytest.raises(SystemExit):
        check_target_collection(name)


def test_test_collection_is_allowed():
    check_target_collection("figindex_test_addmissing")


def test_gt_missing_pages_from_repo_csv():
    pages = gt_missing_pages(GT_DIR)
    assert len(pages) == 13  # 결정 19: 13개 문서
    assert sum(len(v) for v in pages.values()) == 16  # 표 16개, 핵심광물·재자원화·수소는 2페이지씩
    assert pages["RPT_20261109_한국타이어앤테크놀로지_메리츠증권.pdf"] == {7}


def test_find_pdf_ignores_nfc_nfd_and_subfolder(tmp_path):
    sub = tmp_path / "pdfs"
    sub.mkdir()
    name = "보고서_테스트.pdf"
    (sub / unicodedata.normalize("NFD", name)).write_bytes(b"%PDF-1.4")
    found = find_pdf(tmp_path, name)
    assert found is not None and unicodedata.normalize("NFC", found.name) == name
    assert find_pdf(tmp_path, "없는파일.pdf") is None
