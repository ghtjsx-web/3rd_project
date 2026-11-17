"""
figindex/pipeline/test_sparse_and_point_id.py

1. PYTHONHASHSEED가 다른 두 프로세스에서 build_sparse_vector 결과가 100% 동일한지 검증
2. generate_point_id가 동일한 (doc_id, page_number, bbox) 입력에 대해 항상 동일한 UUID를 생성하는지 검증
"""
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIGINDEX_DIR = REPO_ROOT / "figindex"
if str(FIGINDEX_DIR) not in sys.path:
    sys.path.insert(0, str(FIGINDEX_DIR))

from shared.sparse import (
    build_sparse_vector,
    generate_point_id,
    FIGINDEX_POINT_NAMESPACE,
)


def test_build_sparse_vector_deterministic_across_hashseed():
    """PYTHONHASHSEED가 다른 두 서브프로세스에서 build_sparse_vector가 동일한 출력을 내는지 검증"""
    text = "카카오 3Q26 실적 Review 및 2026E 연간 영업이익 추이 전망 Target 120,000원"
    
    code = f"""
import sys, json
from pathlib import Path
sys.path.insert(0, r"{str(FIGINDEX_DIR)}")
from shared.sparse import build_sparse_vector

vec = build_sparse_vector({json.dumps(text)})
print(json.dumps(vec, sort_keys=True))
"""
    # 1. PYTHONHASHSEED = 0
    env0 = os.environ.copy()
    env0["PYTHONHASHSEED"] = "0"
    res0 = subprocess.run(
        [sys.executable, "-c", code],
        env=env0,
        capture_output=True,
        text=True,
        check=True
    )
    vec0 = json.loads(res0.stdout.strip())

    # 2. PYTHONHASHSEED = 9999
    env1 = os.environ.copy()
    env1["PYTHONHASHSEED"] = "9999"
    res1 = subprocess.run(
        [sys.executable, "-c", code],
        env=env1,
        capture_output=True,
        text=True,
        check=True
    )
    vec1 = json.loads(res1.stdout.strip())

    # 검증: 두 프로세스 간 토큰 ID 및 가중치 완전 일치
    assert len(vec0) > 0, "Sparse vector should not be empty"
    assert vec0 == vec1, f"Vectors under different hash seeds must match! {vec0} vs {vec1}"


def test_generate_point_id_deterministic():
    """동일 입력에 대한 point id 결정론적 생성 및 소수점 셋째 자리 반올림 정규화 검증"""
    doc_id = "doc_test_12345"
    page_number = 3
    bbox1 = [0.1234, 0.4567, 0.7891, 0.9876]
    bbox2 = [0.1231, 0.4572, 0.7889, 0.9879]  # 소수 셋째 자리 반올림 시 bbox1과 동일: [0.123, 0.457, 0.789, 0.988]

    pid1 = generate_point_id(doc_id, page_number, bbox1)
    pid2 = generate_point_id(doc_id, page_number, bbox2)

    assert pid1 == pid2, f"Expected same point_id for rounded bbox, got {pid1} vs {pid2}"

    # 서로 다른 입력 시 다른 point id 생성 확인
    pid_diff_page = generate_point_id(doc_id, page_number + 1, bbox1)
    pid_diff_doc = generate_point_id("doc_another_67890", page_number, bbox1)
    pid_diff_bbox = generate_point_id(doc_id, page_number, [0.5, 0.5, 0.9, 0.9])

    assert pid1 != pid_diff_page
    assert pid1 != pid_diff_doc
    assert pid1 != pid_diff_bbox
