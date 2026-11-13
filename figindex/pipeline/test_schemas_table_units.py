"""
TableData 행별·열별 단위(unit_by_row, unit_by_column) 및 unit_for() 메서드 단위 테스트.

테스트 케이스:
1. 기존 형식(unit만 있음) 그대로 통과
2. unit_by_row로 행마다 다른 단위 -> unit_for 결과 확인
3. unit_by_column -> unit_for 결과 확인
4. 행과 열 둘 다 있을 때 행이 우선
5. 없는 행 라벨이나 열 이름을 키로 쓰면 검증 실패 (어떤 키가 틀렸는지 에러 메시지 확인)
6. v2 컬렉션의 table_data 전체가 새 TableData로 여전히 통과 (서버 미가동 시 skip)
"""
import os
import sys
from pathlib import Path
import pytest

# 경로 설정
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

from shared.schemas import TableData


def test_case_1_legacy_format_with_unit_only():
    """1. 기존 형식(unit만 존재)이 그대로 검증 통과하고 unit_for가 올바르게 작동하는지 확인"""
    td = TableData(
        columns=["구분", "2024", "2025E"],
        rows=[
            {"구분": "매출액", "2024": 1000, "2025E": 1200},
            {"구분": "영업이익", "2024": 100, "2025E": 150},
        ],
        unit="억원",
    )
    assert td.unit == "억원"
    assert td.unit_by_row == {}
    assert td.unit_by_column == {}
    assert td.unit_for("매출액", "2024") == "억원"
    assert td.unit_for("영업이익", "2025E") == "억원"


def test_case_2_unit_by_row():
    """2. unit_by_row로 행마다 다른 단위를 지정하고 unit_for 결과 확인"""
    td = TableData(
        columns=["항목", "2024", "2025E"],
        rows=[
            {"항목": "매출액", "2024": 1500, "2025E": 1800},
            {"항목": "영업이익률", "2024": 10.5, "2025E": 12.0},
            {"항목": "EPS", "2024": 3500, "2025E": 4200},
        ],
        unit=None,
        unit_by_row={
            "매출액": "십억원",
            "영업이익률": "%",
            "EPS": "원",
        },
    )
    assert td.unit_for("매출액", "2024") == "십억원"
    assert td.unit_for("영업이익률", "2025E") == "%"
    assert td.unit_for("EPS", "2024") == "원"


def test_case_3_unit_by_column():
    """3. unit_by_column으로 열마다 다른 단위를 지정하고 unit_for 결과 확인"""
    td = TableData(
        columns=["구분", "출하량", "가동률", "판매단가"],
        rows=[
            {"구분": "제품A", "출하량": 500, "가동률": 95.0, "판매단가": 12000},
            {"구분": "제품B", "출하량": 300, "가동률": 88.5, "판매단가": 8500},
        ],
        unit=None,
        unit_by_column={
            "출하량": "천톤",
            "가동률": "%",
            "판매단가": "달러",
        },
    )
    assert td.unit_for("제품A", "출하량") == "천톤"
    assert td.unit_for("제품B", "가동률") == "%"
    assert td.unit_for("제품A", "판매단가") == "달러"
    # 지정되지 않은 첫 열(구분)은 전체 unit(None) 반환
    assert td.unit_for("제품A", "구분") is None


def test_case_4_row_priority_over_column_and_unit():
    """4. 행별 단위, 열별 단위, 전체 단위가 모두 있을 때 행별 단위가 최우선 순위인지 확인"""
    td = TableData(
        columns=["구분", "수량", "비율"],
        rows=[
            {"구분": "특별항목", "수량": 10, "비율": 5.0},
            {"구분": "일반항목", "수량": 20, "비율": 10.0},
        ],
        unit="기본단위",
        unit_by_row={"특별항목": "특수단위"},
        unit_by_column={"수량": "개", "비율": "%"},
    )
    # 특별항목: 행 단위 "특수단위"가 열 단위 "개" 및 기본단위 "기본단위"보다 우선
    assert td.unit_for("특별항목", "수량") == "특수단위"
    assert td.unit_for("특별항목", "비율") == "특수단위"

    # 일반항목: 행 단위가 없으므로 열 단위 적용
    assert td.unit_for("일반항목", "수량") == "개"
    assert td.unit_for("일반항목", "비율") == "%"

    # 행 단위도 열 단위도 없는 열: 기본 unit 반환
    assert td.unit_for("일반항목", "구분") == "기본단위"


def test_case_5_invalid_row_or_column_keys_raise_error():
    """5. 없는 행 라벨이나 열 이름을 키로 쓰면 검증 실패 및 실패 키 이름 포함 확인"""
    # 5.1 존재하지 않는 열 이름을 unit_by_column에 지정한 경우
    with pytest.raises(ValueError) as exc_col:
        TableData(
            columns=["구분", "2024"],
            rows=[{"구분": "항목1", "2024": 100}],
            unit_by_column={"존재하지않는열": "억원"},
        )
    assert "unit_by_column" in str(exc_col.value)
    assert "존재하지않는열" in str(exc_col.value)

    # 5.2 존재하지 않는 행 라벨을 unit_by_row에 지정한 경우
    with pytest.raises(ValueError) as exc_row:
        TableData(
            columns=["구분", "2024"],
            rows=[
                {"구분": "실제항목A", "2024": 100},
                {"구분": "실제항목B", "2024": 200},
            ],
            unit_by_row={"가짜항목C": "원"},
        )
    assert "unit_by_row" in str(exc_row.value)
    assert "가짜항목C" in str(exc_row.value)


def test_case_6_v2_collection_tables_validation():
    """6. 실제 v2 컬렉션(figindex_elements_v2)의 모든 table_data가 새 TableData 스키마로 100% 통과하는지 검증 (읽기 전용)"""
    import json
    import urllib.request
    import urllib.error

    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333").rstrip("/")

    # 서버 연결 확인
    try:
        check_req = urllib.request.Request(f"{qdrant_url}/collections/figindex_elements_v2")
        with urllib.request.urlopen(check_req, timeout=3.0) as resp:
            if resp.status != 200:
                pytest.skip("figindex_elements_v2 컬렉션에 접근할 수 없어 건너뜁니다.")
    except Exception as e:
        pytest.skip(f"Qdrant 서버({qdrant_url})에 접근할 수 없어 건너뜁니다: {e}")

    # 전체 포인트 scroll 조회 (읽기 전용)
    offset = None
    all_table_data_count = 0

    while True:
        req_body = {
            "limit": 100,
            "offset": offset,
            "with_payload": True,
            "with_vector": False,
        }
        scroll_req = urllib.request.Request(
            f"{qdrant_url}/collections/figindex_elements_v2/points/scroll",
            data=json.dumps(req_body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(scroll_req, timeout=10.0) as resp:
                res = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            pytest.skip(f"scroll 요청 실패: {e}")

        result = res.get("result", {})
        points = result.get("points", [])
        if not points:
            break

        for pt in points:
            payload = pt.get("payload", {})
            td_dict = payload.get("table_data")
            if td_dict is not None:
                # 새 TableData로 파싱 검증
                td_obj = TableData(**td_dict)
                assert isinstance(td_obj.columns, list)
                assert isinstance(td_obj.rows, list)
                all_table_data_count += 1

        offset = result.get("next_page_offset")
        if offset is None:
            break

    assert all_table_data_count > 0, "v2 컬렉션에서 검증할 table_data를 찾지 못했습니다."

