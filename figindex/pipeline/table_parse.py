"""
Vision 응답의 table_data를 TableData로 만드는 함수.

Gemini가 준 표가 대체로 맞아도 아래처럼 형식이 조금 어긋나면 TableData 검증이 실패해 표 전체가 버려졌다.
- period_labels, unit_by_row, unit_by_column이 null
- 어떤 행에 columns의 칸이 빠졌거나, columns에 없는 키가 있음

여기서는 그런 형식만 맞춘 뒤 검증한다. 값(셀 내용)은 바꾸지 않는다.
- null 목록·사전 필드 → 빈 목록·빈 사전
- 행 키를 columns에 맞춤: 빠진 칸은 None, columns에 없는 키는 버림 (AGENTS.md 4절: rows 키 = columns)
- 행 단위 사전이 아닌 행(문자열 등)은 버림
"""
from typing import Any, Dict, Optional, Tuple

from shared.schemas import ElementType, TableData


def coerce_table_data(raw: Any) -> Tuple[Optional[TableData], str]:
    """(TableData 또는 None, 메모)를 돌려준다. 메모는 맞춘 내용이나 실패 이유."""
    if raw is None:
        return None, "table_data 없음"
    if not isinstance(raw, dict):
        return None, f"table_data 형식이 dict가 아님 ({type(raw).__name__})"

    columns = [str(c) for c in (raw.get("columns") or [])]
    raw_rows = raw.get("rows") or []
    if not columns or not isinstance(raw_rows, list) or not raw_rows:
        return None, "columns 또는 rows가 비어 있음"

    fixed_rows = 0
    dropped_rows = 0
    rows = []
    for row in raw_rows:
        if not isinstance(row, dict):
            dropped_rows += 1
            continue
        keys = {str(k) for k in row.keys()}
        if keys != set(columns):
            fixed_rows += 1
        str_row = {str(k): v for k, v in row.items()}
        rows.append({c: str_row.get(c) for c in columns})
    if not rows:
        return None, "사전 형태의 행이 없음"

    data: Dict[str, Any] = {
        "columns": columns,
        "rows": rows,
        "unit": raw.get("unit"),
        "unit_by_row": raw.get("unit_by_row") or {},
        "unit_by_column": raw.get("unit_by_column") or {},
        "period_labels": raw.get("period_labels") or [],
    }
    try:
        table = TableData(**data)
    except Exception:
        # 행·열 단위 지정이 잘못된 경우가 많다. 단위 지정만 빼고 한 번 더 시도한다.
        data["unit_by_row"] = {}
        data["unit_by_column"] = {}
        try:
            table = TableData(**data)
        except Exception as e:
            return None, f"TableData 검증 실패: {str(e).splitlines()[0][:150]}"
        fixed_rows_note = "행·열 단위 지정 제외, "
    else:
        fixed_rows_note = ""

    note = f"{fixed_rows_note}행 키 맞춤 {fixed_rows}개, 버린 행 {dropped_rows}개"
    return table, note


def is_empty_table_payload(payload: Dict[str, Any]) -> bool:
    """TABLE인데 표 데이터가 비어 있는 payload인지."""
    if payload.get("element_type") != ElementType.TABLE.value:
        return False
    table = payload.get("table_data")
    return not (isinstance(table, dict) and table.get("rows"))
