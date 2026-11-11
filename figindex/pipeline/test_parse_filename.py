"""
새 PDF 파일명 형식 및 기존 파일명 호환성 테스트 스크립트
실행 방법:
  docker compose run --rm pipeline python test_parse_filename.py
"""

from orchestrator import parse_new_filename, ExtractionPipelineOrchestrator


class _DummyPage:
    def __init__(self, text: str):
        self._text = text

    def get_text(self, mode: str = "text") -> str:
        return self._text


class _DummyDoc:
    def __init__(self, cover_text: str):
        self._pages = [_DummyPage(cover_text)]

    def __len__(self) -> int:
        return len(self._pages)

    def __getitem__(self, idx: int) -> _DummyPage:
        return self._pages[idx]


def main():
    test_cases = [
        (
            "RPT_20261109_현대백화점_대신증권.pdf",
            "현대백화점 (069960)\n2026.11.09\n대신증권 유정현 연구원\n유통업종",
        ),
        (
            "RPT_20261106_삼성전자_키움증권_2.pdf",
            "삼성전자 (005930)\n2026.11.05\n키움증권 박유악 연구원\n반도체",
        ),
        (
            "PUB_20261020_반도체수출동향_산업연구원.pdf",
            "2026년 10월 반도체 수출 동향\n산업연구원 홍길동 연구위원",
        ),
        (
            "현대백화점1106.pdf",
            "현대백화점 (069960)\n대신증권 유정현 연구원\n유통",
        ),
    ]

    orchestrator = ExtractionPipelineOrchestrator()

    for filename, dummy_cover in test_cases:
        parsed = parse_new_filename(filename)
        meta = orchestrator.extract_document_metadata(_DummyDoc(dummy_cover), filename)
        print("=" * 60)
        print(f"입력 파일명        : {filename}")
        print(f"parse_new_filename : {parsed}")
        print(f"extract_metadata   : {meta}")


if __name__ == "__main__":
    main()

