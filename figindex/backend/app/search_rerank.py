"""검색 후보를 표 행·열 이름으로 다시 정렬하는 도우미.

색인 글자(caption·summary·hashtags 등)에는 표의 행 이름(매출액·영업이익)과 열 이름(2025, 2026E)이
들어가지 않는다. 그래서 "삼성전자 2025년 매출액 영업이익"처럼 기업명 + 지표 + 연도로 찾으면
캡션이 "요약 재무제표"인 정답 표가 밀린다. 하이브리드 후보 안에서 아래 조건을 만족하는 표를 앞으로 올린다.

- 지표: 검색어의 지표 단어(shared.normalize 사전)가 표의 행 이름이나 열 이름에 있다
- 기간: 검색어에 연도가 있으면 그 연도의 연간 열(2025, 2026E 등)이 있다.
  검색어에 "분기"가 있으면 연간 대신 분기 열(3Q26 등)을 본다 (연간과 분기는 다른 지표로 본다)
"""

import re
from typing import Any, Dict, List, Optional, Sequence

from shared.normalize import METRIC_ALIASES, normalize_metric, normalize_period

# 조건 하나를 만족할 때마다 앞으로 당기는 순위 수. 5 = 검색 결과 한 화면(상위 5개)만큼.
RERANK_SHIFT = 5

_YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
_ASCII = re.compile(r"^[a-z0-9 /%]+$")


def query_metrics(query: str) -> List[str]:
    """검색어에 들어 있는 대표 지표명. 영문 별칭(op, per 등)은 단어 경계가 맞을 때만."""
    lowered = query.lower()
    found = []
    for metric, aliases in METRIC_ALIASES.items():
        for alias in aliases:
            if _ASCII.match(alias):
                hit = re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", lowered)
            else:
                hit = alias in lowered
            if hit:
                found.append(metric)
                break
    return found


def _table_names(table_data: Optional[Dict[str, Any]]) -> List[str]:
    """열 이름 + 행 이름(첫 열 값). 행·열이 뒤바뀐 표(열이 지표, 행이 연도)도 함께 본다."""
    if not table_data:
        return []
    columns = [str(c) for c in table_data.get("columns") or []]
    if not columns:
        return []
    row_names = [str(row.get(columns[0], "")) for row in table_data.get("rows") or [] if isinstance(row, dict)]
    return columns + row_names


def rerank_bonus(query: str, table_data: Optional[Dict[str, Any]]) -> int:
    """표가 만족하는 조건 수 (0~2)."""
    names = _table_names(table_data)
    if not names:
        return 0
    bonus = 0
    metrics = query_metrics(query)
    if metrics and any(normalize_metric(n) in metrics for n in names):
        bonus += 1
    years = {int(y) for y in _YEAR.findall(query)}
    wants_quarter = "분기" in query
    if years or wants_quarter:
        periods = [p for p in (normalize_period(n) for n in names) if p]
        if any((p["quarter"] is not None) == wants_quarter and (not years or p["year"] in years) for p in periods):
            bonus += 1
    return bonus


def rerank_points(query: str, points: Sequence[Any]) -> List[Any]:
    """Qdrant 결과(payload에 table_data)를 조건 수만큼 앞으로 당겨 다시 정렬한다. 같으면 원래 순서."""
    keyed = []
    for rank_index, point in enumerate(points):
        bonus = rerank_bonus(query, (point.payload or {}).get("table_data"))
        keyed.append((rank_index - RERANK_SHIFT * bonus, rank_index, point))
    return [p for _, _, p in sorted(keyed, key=lambda k: (k[0], k[1]))]
