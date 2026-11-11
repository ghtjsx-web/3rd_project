"""
메타데이터 일반화(출처 source_org / 대상 target) 및 파일명 파싱 단위 테스트.

실행:
  pytest figindex/pipeline/test_metadata_generalization.py -v
"""

import logging
import sys
import types
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIGINDEX_DIR = REPO_ROOT / "figindex"
PIPELINE_DIR = FIGINDEX_DIR / "pipeline"
SCRIPTS_DIR = REPO_ROOT / "scripts"

for p in (str(PIPELINE_DIR), str(FIGINDEX_DIR), str(SCRIPTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _install_optional_stubs() -> None:
    """로컬 호스트 환경에 Docker 전용 패키지(fitz, kiwipiepy, qdrant_client 등)가 없을 때만 스텁을 등록합니다."""
    if "fitz" not in sys.modules:
        try:
            __import__("fitz")
        except ImportError:
            fitz_mod = types.ModuleType("fitz")
            fitz_mod.Document = MagicMock
            fitz_mod.Page = MagicMock
            fitz_mod.Rect = MagicMock
            sys.modules["fitz"] = fitz_mod

    if "kiwipiepy" not in sys.modules:
        try:
            __import__("kiwipiepy")
        except ImportError:
            kiwi_mod = types.ModuleType("kiwipiepy")
            kiwi_mod.Kiwi = MagicMock
            sys.modules["kiwipiepy"] = kiwi_mod

    if "qdrant_client" not in sys.modules:
        try:
            __import__("qdrant_client")
        except ImportError:
            qc_mod = types.ModuleType("qdrant_client")
            qc_mod.QdrantClient = MagicMock
            qc_http = types.ModuleType("qdrant_client.http")
            qc_models = types.ModuleType("qdrant_client.http.models")
            qc_models.PayloadSchemaType = MagicMock()
            qc_models.Filter = MagicMock
            qc_models.FieldCondition = MagicMock
            qc_models.MatchValue = MagicMock
            qc_models.PointStruct = MagicMock
            qc_models.SparseVector = MagicMock
            qc_http.models = qc_models
            sys.modules["qdrant_client"] = qc_mod
            sys.modules["qdrant_client.http"] = qc_http
            sys.modules["qdrant_client.http.models"] = qc_models

    if "google.genai" not in sys.modules:
        try:
            __import__("google.genai")
        except ImportError:
            google_mod = sys.modules.setdefault("google", types.ModuleType("google"))
            genai_mod = types.ModuleType("google.genai")
            genai_mod.Client = MagicMock
            google_mod.genai = genai_mod
            sys.modules["google.genai"] = genai_mod

    if "PIL" not in sys.modules:
        try:
            __import__("PIL.Image")
        except ImportError:
            pil_mod = types.ModuleType("PIL")
            pil_img = types.ModuleType("PIL.Image")
            pil_img.Image = MagicMock
            pil_img.open = MagicMock
            pil_mod.Image = pil_img
            sys.modules["PIL"] = pil_mod
            sys.modules["PIL.Image"] = pil_img

    if "doclayout_yolo" not in sys.modules:
        try:
            __import__("doclayout_yolo")
        except ImportError:
            yolo_mod = types.ModuleType("doclayout_yolo")
            yolo_mod.YOLOv10 = MagicMock
            sys.modules["doclayout_yolo"] = yolo_mod


_install_optional_stubs()

import orchestrator  # noqa: E402
from orchestrator import (  # noqa: E402
    BROKER_ALIASES,
    DOC_TYPE_CODE_MAP,
    ExtractionPipelineOrchestrator,
    normalize_broker_name,
    parse_filename,
    parse_new_filename,
)
from extractor import MultimodalExtractor  # noqa: E402


class FakePage:
    def __init__(self, text: str):
        self._text = text

    def get_text(self, mode: str = "text") -> str:
        return self._text


class FakeDoc:
    def __init__(self, cover_text: str):
        self.pages = [FakePage(cover_text)] if cover_text is not None else []

    def __len__(self) -> int:
        return len(self.pages)

    def __getitem__(self, idx: int) -> FakePage:
        return self.pages[idx]


def _make_bare_orchestrator() -> ExtractionPipelineOrchestrator:
    """외부 API/DB 연결 없이 extract_document_metadata만 테스트하기 위한 경량 인스턴스."""
    return ExtractionPipelineOrchestrator.__new__(ExtractionPipelineOrchestrator)


# =====================================================================
# 1. 파일명 파싱 단위 테스트 (완료 기준 1)
# =====================================================================


def test_doc_type_code_map_contains_all_codes():
    assert DOC_TYPE_CODE_MAP == {
        "RPT": "REPORT",
        "PUB": "PUBLIC_REPORT",
        "PAP": "PAPER",
        "IR": "IR",
    }


def test_parse_rpt_report():
    res = parse_new_filename("RPT_20261109_현대백화점_대신증권.pdf")
    assert res is not None
    assert res["doc_type"] == "REPORT"
    assert res["source_org"] == "대신증권"
    assert res["target"] == "현대백화점"
    assert res["publish_date"] == date(2026, 11, 9)
    assert "company" not in res
    assert "broker" not in res


def test_parse_pub_public_report():
    res = parse_new_filename("PUB_20261020_반도체수출동향_산업연구원.pdf")
    assert res is not None
    assert res["doc_type"] == "PUBLIC_REPORT"
    assert res["source_org"] == "산업연구원"
    assert res["target"] == "반도체수출동향"
    assert res["publish_date"] == date(2026, 10, 20)


def test_parse_pap_paper_and_ir():
    pap = parse_new_filename("PAP_20260831_치과임플란트CT인공물_KSRadiology.pdf")
    assert pap is not None
    assert pap["doc_type"] == "PAPER"
    assert pap["target"] == "치과임플란트CT인공물"
    assert pap["source_org"] == "KSRadiology"
    assert pap["publish_date"] == date(2026, 8, 31)

    ir = parse_new_filename("IR_20261029_2026년3분기실적발표_삼성전자.pdf")
    assert ir is not None
    assert ir["doc_type"] == "IR"
    assert ir["target"] == "2026년3분기실적발표"
    assert ir["source_org"] == "삼성전자"
    assert ir["publish_date"] == date(2026, 10, 29)


def test_parse_duplicate_suffix():
    res = parse_new_filename("RPT_20261106_삼성전자_키움증권_2.pdf")
    assert res is not None
    assert res["doc_type"] == "REPORT"
    assert res["target"] == "삼성전자"
    assert res["source_org"] == "키움증권"
    assert res["publish_date"] == date(2026, 11, 6)


@pytest.mark.parametrize(
    "raw_broker, expected",
    [
        ("한투", "한국투자증권"),
        ("하이투자증권", "iM증권"),
        ("DB금융투자", "DB증권"),
    ],
)
def test_parse_report_broker_aliases(raw_broker: str, expected: str):
    res = parse_new_filename(f"RPT_20261106_삼성전자_{raw_broker}.pdf")
    assert res is not None
    assert res["doc_type"] == "REPORT"
    assert res["target"] == "삼성전자"
    assert res["source_org"] == expected
    assert raw_broker in BROKER_ALIASES


def test_unknown_report_broker_logs_warning_and_preserves_original(caplog):
    with caplog.at_level(logging.WARNING):
        res = parse_new_filename("RPT_20261106_삼성전자_미지정증권사.pdf")
    assert res is not None
    assert res["source_org"] == "미지정증권사"
    assert any("BROKER_ALIASES" in rec.message for rec in caplog.records)


def test_non_report_does_not_apply_broker_aliases(caplog):
    with caplog.at_level(logging.WARNING):
        res = parse_new_filename("PUB_20261020_경제전망_KDI.pdf")
    assert res is not None
    assert res["doc_type"] == "PUBLIC_REPORT"
    assert res["source_org"] == "KDI"
    assert not any("BROKER_ALIASES" in rec.message for rec in caplog.records)


def test_parse_compact_korean_format_c():
    cases = [
        (
            "보고서20251231해상풍력보급확대를위한지자체역할_에너지경제연구원.pdf",
            "PUBLIC_REPORT",
            date(2025, 12, 31),
            "해상풍력보급확대를위한지자체역할",
            "에너지경제연구원",
        ),
        (
            "리포트202605122026년세계경제전망_대외경제정책연구원.pdf",
            "PUBLIC_REPORT",
            date(2026, 5, 12),
            "2026년세계경제전망",
            "대외경제정책연구원",
        ),
        (
            "논문2025020112차베이비붐세대의소득및자산특_한국보건사회연구원.pdf",
            "PAPER",
            date(2025, 2, 1),
            "12차베이비붐세대의소득및자산특",
            "한국보건사회연구원",
        ),
    ]
    for fname, exp_type, exp_date, exp_target, exp_source in cases:
        res = parse_filename(fname)
        assert res is not None
        assert res["doc_type"] == exp_type
        assert res["date"] == exp_date
        assert res["target"] == exp_target
        assert res["source"] == exp_source


def test_legacy_filename_returns_none_in_parser_and_handled_in_metadata():
    assert parse_new_filename("BGF리테일1106.pdf") is None

    orch = _make_bare_orchestrator()
    cover = "BGF리테일 (027410)\n삼성증권 김연구 애널리스트\n2025.11.06\n편의점 실적 Review"
    meta = orch.extract_document_metadata(FakeDoc(cover), "BGF리테일1106.pdf")

    assert meta["doc_type"] == "REPORT"
    assert meta["target"] == "BGF리테일"
    assert meta["source_org"] == "삼성증권"
    assert meta["ticker"] == "027410"
    assert meta["analyst"] == "김연구"
    assert meta["company"] == "BGF리테일"
    assert meta["broker"] == "삼성증권"


def test_legacy_filename_without_cover_broker_has_no_default_securities_string():
    orch = _make_bare_orchestrator()
    meta = orch.extract_document_metadata(FakeDoc("표지에 증권사 정보 없음"), "BGF리테일1106.pdf")
    assert meta["doc_type"] == "REPORT"
    assert meta["target"] == "BGF리테일"
    assert meta["source_org"] is None


def test_malformed_prefixed_filename_sets_target_none_with_warning(caplog):
    orch = _make_bare_orchestrator()
    with caplog.at_level(logging.WARNING):
        meta = orch.extract_document_metadata(FakeDoc("아무 내용 (123456) 홍길동 애널리스트"), "RPT_잘못된형식.pdf")
    assert meta["doc_type"] == "REPORT"
    assert meta["target"] is None
    assert any("대상을 비워둡니다" in rec.message for rec in caplog.records)

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        pub_meta = orch.extract_document_metadata(FakeDoc("2026년 반도체 수출 동향 보고서"), "PUB_잘못된형식.pdf")
    assert pub_meta["doc_type"] == "PUBLIC_REPORT"
    assert pub_meta["target"] is None
    assert pub_meta["ticker"] is None
    assert pub_meta["analyst"] is None
    assert pub_meta["company"] is None
    assert pub_meta["broker"] is None


def test_non_report_metadata_leaves_report_only_fields_none():
    orch = _make_bare_orchestrator()
    cover = "2026년 반도체 수출 동향 심층 분석\n산업연구원\n(005930) 김연구 애널리스트"
    meta = orch.extract_document_metadata(FakeDoc(cover), "PUB_20261020_반도체수출동향_산업연구원.pdf")

    assert meta["doc_type"] == "PUBLIC_REPORT"
    assert meta["target"] == "반도체수출동향"
    assert meta["source_org"] == "산업연구원"
    assert meta["ticker"] is None
    assert meta["analyst"] is None
    assert meta["industry"] is None
    assert meta["company"] is None
    assert meta["broker"] is None
    assert meta["doc_title"] == "2026년 반도체 수출 동향 심층 분석"


# =====================================================================
# 2. Extractor & Migration 단위 테스트
# =====================================================================


def test_extractor_builds_generalized_schema_from_cache(tmp_path):
    img_path = tmp_path / "sample_crop.png"
    img_path.write_bytes(b"fake-png-bytes")

    ext = MultimodalExtractor.__new__(MultimodalExtractor)
    ext.cache = {}
    ext.evaluator = MagicMock()
    ext.evaluator.evaluate_signals.return_value = {
        "confidence_score": 0.91,
        "review_status": "APPROVED",
    }

    img_hash = ext.get_image_hash(img_path)
    ext.cache[img_hash] = {
        "element_type": "CHART",
        "title_or_caption": "[그림 1] 반도체 수출 추이",
        "summary": "반도체 수출이 전년 대비 증가했습니다.",
        "hashtags": ["#반도체수출동향", "#산업연구원", "#증권사"],
        "structured_data": None,
    }

    crop_info = {
        "element_id": "elem-123",
        "crop_path": str(img_path),
        "normalized_box": [0.1, 0.1, 0.5, 0.5],
        "relative_path": "/static/crops/sample_crop.png",
        "hint_type": "CHART",
    }

    # PUBLIC_REPORT 검증
    pub_meta = {
        "doc_type": "PUBLIC_REPORT",
        "target": "반도체수출동향",
        "source_org": "산업연구원",
        "publish_date": date(2026, 10, 20),
        "doc_title": "반도체 수출 동향 보고서",
        "industry": None,
        "analyst": None,
    }
    el = ext.analyze_crop(crop_info, "PUB_20261020_반도체수출동향_산업연구원.pdf", 3, pub_meta)
    assert el.doc_type == "PUBLIC_REPORT"
    assert el.source_org == "산업연구원"
    assert el.domain is None
    assert el.extra_metadata["target"] == "반도체수출동향"
    assert el.extra_metadata["company"] is None
    assert el.extra_metadata["broker"] is None
    assert el.extra_metadata["ticker"] is None
    assert el.extra_metadata["analyst"] is None
    assert "증권사" not in el.entities
    assert "반도체수출동향" in el.entities
    assert "산업연구원" in el.entities

    # REPORT 검증 (domain 기본값 & 하위 호환 필드)
    rpt_meta = {
        "doc_type": "REPORT",
        "target": "삼성전자",
        "source_org": "한국투자증권",
        "publish_date": date(2026, 11, 6),
        "doc_title": "삼성전자 리포트",
        "ticker": "005930",
        "analyst": "홍길동",
        "industry": None,
    }
    el_rpt = ext.analyze_crop(crop_info, "RPT_20261106_삼성전자_한투.pdf", 2, rpt_meta)
    assert el_rpt.doc_type == "REPORT"
    assert el_rpt.source_org == "한국투자증권"
    assert el_rpt.domain == "금융/산업"
    assert el_rpt.extra_metadata["target"] == "삼성전자"
    assert el_rpt.extra_metadata["company"] == "삼성전자"
    assert el_rpt.extra_metadata["broker"] == "한국투자증권"
    assert el_rpt.extra_metadata["ticker"] == "005930"
    assert el_rpt.extra_metadata["analyst"] == "홍길동"


def test_migration_script_dry_run_and_apply():
    import migrate_source_target  # noqa: E402

    rec_pub = types.SimpleNamespace(
        id=1,
        payload={
            "doc_name": "PUB_20261020_반도체수출동향_산업연구원.pdf",
            "doc_type": "REPORT",
            "source_org": "산업연구원",
            "hashtags": ["#반도체"],
            "extra_metadata": {"company": "반도체수출동향", "broker": "산업연구원", "ticker": None, "analyst": None},
            "entities": ["반도체수출동향", "증권사", "반도체"],
        },
    )
    rec_alias = types.SimpleNamespace(
        id=2,
        payload={
            "doc_name": "RPT_20261106_삼성전자_DB금융투자.pdf",
            "doc_type": "REPORT",
            "source_org": "DB금융투자",
            "hashtags": ["#삼성전자"],
            "extra_metadata": {"company": "삼성전자", "broker": "DB금융투자", "ticker": "005930", "analyst": "김연구"},
            "entities": ["삼성전자", "DB금융투자"],
        },
    )
    rec_legacy = types.SimpleNamespace(
        id=3,
        payload={
            "doc_name": "BGF리테일1106.pdf",
            "doc_type": "REPORT",
            "source_org": "삼성증권",
            "hashtags": [],
            "extra_metadata": {"company": "BGF리테일"},
            "entities": ["BGF리테일"],
        },
    )

    fake_client = MagicMock()
    fake_client.scroll.return_value = ([rec_pub, rec_alias, rec_legacy], None)

    dry_stats = migrate_source_target.run_migration(fake_client, "figindex_elements", dry_run=True)
    assert dry_stats["total_points"] == 3
    assert dry_stats["updated_points"] == 2
    assert dry_stats["failed_docs"] == {"BGF리테일1106.pdf": 1}
    fake_client.set_payload.assert_not_called()

    apply_stats = migrate_source_target.run_migration(fake_client, "figindex_elements", dry_run=False)
    assert apply_stats["updated_points"] == 2
    assert fake_client.set_payload.call_count == 2

    first_call_payload = fake_client.set_payload.call_args_list[0].kwargs["payload"]
    assert first_call_payload["doc_type"] == "PUBLIC_REPORT"
    assert first_call_payload["source_org"] == "산업연구원"
    assert first_call_payload["extra_metadata"]["target"] == "반도체수출동향"
    assert first_call_payload["extra_metadata"]["company"] is None
    assert "증권사" not in first_call_payload["entities"]

    second_call_payload = fake_client.set_payload.call_args_list[1].kwargs["payload"]
    assert second_call_payload["source_org"] == "DB증권"
    assert second_call_payload["extra_metadata"]["target"] == "삼성전자"
    assert second_call_payload["extra_metadata"]["broker"] == "DB증권"
    assert second_call_payload["extra_metadata"]["ticker"] == "005930"
