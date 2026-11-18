"""
FigIndex 공용 결정론적(Deterministic) Sparse Vector 빌더

형태소 분석기(Kiwi)를 사용하여 한국어 및 영문(SL) 텍스트를 토큰화하고,
zlib.crc32 기반의 고정 해시를 생성하여 프로세스 재시작 및 PYTHONHASHSEED 변경과
무관하게 동일한 토큰에 항상 동일한 sparse 토큰 번호(uint32)를 부여합니다.
"""
import zlib
import uuid
from typing import Dict, List, Optional, Union

FIGINDEX_POINT_NAMESPACE = uuid.UUID("f1618de8-7014-411a-8c2c-7b00355f3400")

_kiwi_instance = None


def get_kiwi():
    """Kiwi 인스턴스를 프로세스 내 싱글톤으로 지연 생성(Lazy Initialization)합니다."""
    global _kiwi_instance
    if _kiwi_instance is None:
        try:
            from kiwipiepy import Kiwi
            _kiwi_instance = Kiwi()
        except ImportError as e:
            raise RuntimeError(
                f"Kiwi 형태소 분석기를 로드할 수 없습니다: {e}. "
                "pip install kiwipiepy 환경을 확인하세요."
            ) from e
    return _kiwi_instance


def build_sparse_vector(text: str) -> Dict[int, float]:
    """
    텍스트를 형태소 분석하여 {token_id: frequency} 형태의 Sparse Vector 딕셔너리를 반환합니다.

    토큰 규칙:
    - 품사 태그: NNG(일반명사), NNP(고유명사), NR(수사), VV(동사), VA(형용사), SL(외래어/영문)
    - 글자 길이: 2글자 이상 (len(form) > 1)
    - 영문(SL) 처리: 대소문자 차이로 인한 검색 불일치를 방지하기 위해 소문자(lower()) 정규화 적용
    - 토큰 번호: zlib.crc32(form.encode('utf-8')) (0 ~ 2^32 - 1 부호 없는 32비트 정수)
    """
    if not text or not isinstance(text, str):
        return {}

    clean_text = text.strip()
    if not clean_text:
        return {}

    kiwi = get_kiwi()
    tokens = kiwi.tokenize(clean_text)
    token_counts: Dict[int, float] = {}
    valid_tags = {"NNG", "NNP", "NR", "VV", "VA", "SL"}

    for t in tokens:
        form = t.form.lower() if t.tag == "SL" else t.form
        if t.tag in valid_tags and len(form) > 1:
            token_id = zlib.crc32(form.encode("utf-8"))
            token_counts[token_id] = token_counts.get(token_id, 0.0) + 1.0

    return token_counts


def generate_point_id(doc_id: str, page_number: int, bbox: Union[List[float], tuple]) -> str:
    """
    doc_id, page_number, bbox로부터 결정론적 UUID5 point id를 생성합니다.
    bbox의 각 좌표를 소수 셋째 자리로 반올림하여 부동소수점 오차에 영향을 받지 않도록 합니다.
    """
    rounded_bbox = [round(float(c), 3) for c in bbox]
    key = f"{doc_id}|{page_number}|{rounded_bbox}"
    return str(uuid.uuid5(FIGINDEX_POINT_NAMESPACE, key))

