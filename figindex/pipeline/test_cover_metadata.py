"""파일명이 RPT_날짜_종목_증권사 형식이 아닐 때 표지에서 메타데이터를 채우는지 (11-18).

실행: pytest figindex/pipeline/test_cover_metadata.py -v
"""
from datetime import date

import pytest

import test_metadata_generalization as base  # 의존 패키지 스텁과 orchestrator import를 함께 쓴다
import orchestrator as orch_mod

ROWS = (
    "entity_name,entity_type,aliases,ticker\n"
    "삼성전자,COMPANY,삼전|Samsung Electronics,005930\n"
    "SK하이닉스,COMPANY,하이닉스|SK hynix,000660\n"
    "엘앤에프,COMPANY,LNF|L&F,066970\n"
    "한국은행,ORG,한은,\n"
)


class Page:
    def __init__(self, text):
        self.text = text

    def get_text(self, mode="text"):
        return self.text


class Doc:
    def __init__(self, *texts):
        self.pages = [Page(t) for t in texts]

    def __len__(self):
        return len(self.pages)

    def __getitem__(self, i):
        return self.pages[i]


@pytest.fixture
def orch(tmp_path, monkeypatch):
    p = tmp_path / "entity_dictionary.csv"
    p.write_text(ROWS, encoding="utf-8")
    monkeypatch.setattr(orch_mod, "_ENTITY_INDEX_CACHE", orch_mod.load_company_index(p))
    return base._make_bare_orchestrator()


def test_raw_broker_filename_uses_cover(orch):
    cover = "Company Report\n삼성전자 (005930)\n3Q26 Review: 메모리 회복\nKB증권 리서치센터 김철수 연구원\n2026.11.18"
    meta = orch.extract_document_metadata(Doc(cover), "삼성전자_3Q26 Review_20261118.pdf")
    assert meta["doc_type"] == "REPORT"
    assert meta["target"] == "삼성전자"
    assert meta["ticker"] == "005930"
    assert meta["source_org"] == "KB증권"
    assert meta["publish_date"] == date(2026, 11, 18)


def test_short_broker_alias_is_not_matched_inside_company_name(orch):
    cover = "SK하이닉스(000660)\nHBM 점유율 확대\n유진투자증권 홍길동 연구원\n2026년 11월 3일"
    meta = orch.extract_document_metadata(Doc(cover), "hynix_note.pdf")
    assert meta["target"] == "SK하이닉스"
    assert meta["source_org"] == "유진투자증권"
    assert meta["publish_date"] == date(2026, 11, 3)


def test_company_name_without_ticker_and_broker_on_last_page(orch):
    cover = "엘앤에프\n양극재 출하 회복\n발행 2026. 11. 9"
    last = "Compliance Notice\n본 자료는 iM증권 리서치센터에서 작성되었습니다."
    meta = orch.extract_document_metadata(Doc(cover, "본문", last), "download (3).pdf")
    assert meta["target"] == "엘앤에프"
    assert meta["source_org"] == "iM증권"
    assert meta["publish_date"] == date(2026, 11, 9)


def test_nothing_found_leaves_none_instead_of_guessing(orch):
    meta = orch.extract_document_metadata(Doc("Research\n산업 동향 정리"), "report_final.pdf")
    assert meta["target"] is None
    assert meta["source_org"] is None
    assert meta["publish_date"] is None


def test_rpt_filename_target_is_normalized_to_entity_name(orch):
    meta = orch.extract_document_metadata(Doc("표지"), "RPT_20261109_LNF_iM증권.pdf")
    assert meta["target"] == "엘앤에프"
    assert meta["source_org"] == "iM증권"
    assert meta["publish_date"] == date(2026, 11, 9)


def test_org_entities_are_not_used_as_report_target(orch):
    meta = orch.extract_document_metadata(Doc("한국은행 기준금리 결정 이후 은행업 점검\n2026-10-30"), "bank_note.pdf")
    assert meta["target"] is None
    assert meta["publish_date"] == date(2026, 10, 30)


def test_filename_mmdd_is_this_year_unless_future():
    today = date(2026, 11, 18)
    assert orch_mod.find_date_in_doc_name("BGF리테일1106", today) == date(2026, 11, 6)
    assert orch_mod.find_date_in_doc_name("BGF리테일1230", today) == date(2025, 12, 30)
    assert orch_mod.find_date_in_doc_name("x_20261118_y", today) == date(2026, 11, 18)
    assert orch_mod.find_date_in_doc_name("report_final", today) is None
