"""
doc_name 조사 도구 단위 테스트 (test_audit_doc_names.py)

테스트 케이스:
1. NFC/NFD로 다르게 저장된 같은 한글 파일명이 (B_nfc_normalized)로 맞는지
2. 경로·확장자 차이가 (C_cleaned_match)로 맞는지
3. IoU 0.95인 두 요소는 중복, 0.5인 두 요소는 중복 아님 판정
"""
import sys
import unicodedata
from pathlib import Path

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

from audit_doc_names import (
    clean_filename,
    check_element_duplicates,
    match_doc_name_to_files,
    nfc,
)


def test_nfc_nfd_normalization_match():
    """1. NFD(자모 분리)로 저장된 한글 파일명이 NFC 정규화(B_nfc_normalized)로 매칭되는지 검증."""
    korean_word = "삼성전자_보고서.pdf"
    nfc_name = unicodedata.normalize("NFC", korean_word)
    nfd_name = unicodedata.normalize("NFD", korean_word)

    # NFD와 NFC는 바이트/글자 구성이 다름
    assert nfc_name != nfd_name

    root_files = {
        nfc_name: {
            "doc_name": nfc_name,
            "rel_path": nfc_name,
            "doc_hash": "hash_123",
            "size_bytes": 1000,
        }
    }

    match_type, finfo = match_doc_name_to_files(
        doc_name=nfd_name,
        root_files=root_files,
        subfolder_files={},
        rename_plan={},
        reverse_rename_plan={},
    )

    assert match_type == "B_nfc_normalized"
    assert finfo is not None
    assert finfo["doc_name"] == nfc_name


def test_cleaned_match_path_and_extension():
    """2. 경로 앞부분(C:/.../)이나 확장자 대문자(.PDF), 앞뒤 공백이 C_cleaned_match로 매칭되는지 검증."""
    target_name = "report_2026.pdf"
    root_files = {
        target_name: {
            "doc_name": target_name,
            "rel_path": target_name,
            "doc_hash": "hash_456",
            "size_bytes": 2000,
        }
    }

    # 경로 포함 + 대문자 확장자 + 공백
    doc_name = " /data/pdfs/report_2026.PDF "

    match_type, finfo = match_doc_name_to_files(
        doc_name=doc_name,
        root_files=root_files,
        subfolder_files={},
        rename_plan={},
        reverse_rename_plan={},
    )

    assert match_type == "C_cleaned_match"
    assert finfo is not None
    assert finfo["doc_name"] == target_name


def test_element_duplicates_iou_threshold():
    """3. IoU 0.95인 두 요소는 중복(1건), 0.5인 두 요소는 중복 아님(0건) 검증."""
    # 옛 bbox 형식: [ymin, xmin, ymax, xmax]
    # base: [0.1, 0.2, 0.5, 0.75] (norm [x0, y0, x1, y1] = [0.2, 0.1, 0.75, 0.5])
    elem_base = {
        "element_id": "elem-base",
        "page_number": 1,
        "bbox": [0.1, 0.2, 0.5, 0.75],
    }

    # IoU ~0.95에 근접한 아주 약간의 차이 박스
    elem_near = {
        "element_id": "elem-near",
        "page_number": 1,
        "bbox": [0.101, 0.201, 0.501, 0.751],
    }

    # IoU ~0.5 수준의 중간 겹침 박스
    elem_half = {
        "element_id": "elem-half",
        "page_number": 1,
        "bbox": [0.1, 0.2, 0.35, 0.75],
    }

    # 1) IoU >= 0.9인 경우 중복 카운트 = 1
    dups_high = check_element_duplicates([elem_base], [elem_near], threshold=0.9)
    assert dups_high == 1

    # 2) IoU < 0.9인 경우 중복 카운트 = 0
    dups_low = check_element_duplicates([elem_base], [elem_half], threshold=0.9)
    assert dups_low == 0

    # 3) 페이지가 다른 경우 박스가 같아도 중복 아님
    elem_diff_page = dict(elem_near, page_number=2)
    dups_page = check_element_duplicates([elem_base], [elem_diff_page], threshold=0.9)
    assert dups_page == 0
