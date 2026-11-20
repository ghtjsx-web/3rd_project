"""
figindex/shared/index_text.py

도표 검색 색인 텍스트(text_to_embed) 생성 모듈.

Dense(OpenAI) 및 Sparse(BM25/CRC32) 벡터 색인 시 동일한 텍스트를 사용하며,
기존 텍스트 구성(caption, summary, hashtags, doc_title, source_org, entities)에 더해
TABLE 요소의 경우 열 이름(columns)과 행 이름(rows의 첫 열 라벨)을 부가하여
"삼성전자 2025년 매출액 영업이익"과 같은 구체적인 계정/연도 질의에 대한 검색 재현율을 높입니다.
"""

import re
from typing import Any, Dict, List, Optional

# 긴 표(예: 50~100행 재무제표)의 모든 행 라벨이 색인 텍스트에 들어가면
# 캡션·요약의 중요 단어 가중치가 희석되거나 임베딩 토큰 한도를 초과할 수 있으므로
# 표에서 추출할 고유 행·열 이름의 최대 개수를 40개로 제한합니다.
MAX_TABLE_NAMES = 40

_NUMERIC_PATTERN = re.compile(r"^[-+]?\d+(?:\.\d+)?$")


def _is_numeric_row_name(s: str) -> bool:
    """행 이름이 순수 숫자(예: '1', '12.5', '-3')인지 검사합니다."""
    cleaned = s.replace(",", "").strip()
    return bool(_NUMERIC_PATTERN.fullmatch(cleaned))


def build_index_text(payload: Dict[str, Any]) -> str:
    """
    Qdrant payload 또는 element.model_dump(mode="json") 딕셔너리로부터
    Dense/Sparse 공용 색인 텍스트를 생성합니다.

    1. 기본 텍스트: 기존 식과 글자 하나까지 동일하게 유지
       f"{caption} {summary} {' '.join(hashtags)} {doc_title or ''} {source_org or ''} {' '.join(entities)}"
    2. table_data가 유효한 경우에만 뒤에 열 이름과 행 이름을 공백으로 연결하여 추가:
       - 열 이름(columns): 원문 유지 (연도 '2025', '2026E' 등 보존)
       - 행 이름(rows 각 행의 columns[0] 값): 빈 값 및 순수 숫자 행 이름('1', '12.5' 등) 제외
       - 중복 이름은 최초 등장 순서 유지하며 1회만 반영
       - 최대 MAX_TABLE_NAMES(40)개로 제한
    3. table_data가 없거나 비어 있으면 기본 텍스트와 100% 동일한 문자열 반환.
    """
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")

    caption = payload.get("caption") or ""
    summary = payload.get("summary") or ""
    hashtags = payload.get("hashtags") or []
    doc_title = payload.get("doc_title") or ""
    source_org = payload.get("source_org") or ""
    entities = payload.get("entities") or []

    hashtags_str = " ".join(hashtags) if isinstance(hashtags, list) else str(hashtags)
    entities_str = " ".join(entities) if isinstance(entities, list) else str(entities)

    base_text = f"{caption} {summary} {hashtags_str} {doc_title} {source_org} {entities_str}"

    table_data = payload.get("table_data")
    if not isinstance(table_data, dict):
        return base_text

    columns = table_data.get("columns") or []
    if not isinstance(columns, list) or not columns:
        return base_text

    table_names: List[str] = []
    seen = set()

    # 1. 열 이름(columns) 추가 - 연도("2025", "2026E") 등 남김
    for col in columns:
        if col is None:
            continue
        c_str = str(col).strip()
        if not c_str:
            continue
        if c_str not in seen:
            seen.add(c_str)
            table_names.append(c_str)

    # 2. 행 이름(rows 각 행의 columns[0] 값) 추가
    first_col = columns[0]
    rows = table_data.get("rows") or []
    if isinstance(rows, list):
        for r in rows:
            if not isinstance(r, dict):
                continue
            val = r.get(first_col)
            if val is None:
                continue
            r_str = str(val).strip()
            if not r_str:
                continue
            # 순수 숫자로만 구성된 행 이름(예: '1', '12.5')은 제외
            if _is_numeric_row_name(r_str):
                continue
            if r_str not in seen:
                seen.add(r_str)
                table_names.append(r_str)

    if not table_names:
        return base_text

    # 최대 개수 제한
    selected_names = table_names[:MAX_TABLE_NAMES]
    return f"{base_text} {' '.join(selected_names)}"
