"""검수 요청이 실제로 값을 바꿨는지 판단하는 도우미.

화면은 승인할 때 고치지 않은 값도 함께 보낸다. 저장된 값과 형식만 다를 뿐
내용이 같으면 바뀌지 않은 것으로 보고, 저장된 값을 그대로 둔다.
- table_data: 요청 값은 TableData를 거쳐 기본값(unit_by_row 등)이 채워진다.
  저장된 값도 같은 방식으로 맞춘 뒤 비교한다.
- caption: 화면은 비어 있는 캡션을 ""로 보낸다. None과 ""는 같은 값으로 본다.
"""

from typing import Any, Optional

from shared.schemas import TableData


def _normalize_table_data(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, TableData):
        return value.model_dump()
    try:
        return TableData.model_validate(value).model_dump()
    except Exception:
        # 저장된 값이 규칙에 맞지 않으면 원래 값 그대로 비교한다.
        return value


def table_data_changed(before: Any, requested: Any) -> bool:
    """요청한 table_data가 저장된 값과 내용이 다르면 True."""
    return _normalize_table_data(before) != _normalize_table_data(requested)


def _normalize_caption(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value if value.strip() else None


def caption_changed(before: Optional[str], requested: Optional[str]) -> bool:
    """요청한 caption이 저장된 값과 다르면 True. None과 빈 문자열은 같게 본다."""
    return _normalize_caption(before) != _normalize_caption(requested)
