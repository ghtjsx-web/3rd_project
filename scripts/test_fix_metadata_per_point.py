"""fix_metadata_from_filename.plan_point_update 테스트: 요소마다 비교하고 요소별 기록을 지우지 않는지."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fix_metadata_from_filename as fm  # noqa: E402
from fix_metadata_from_filename import plan_point_update  # noqa: E402

FILE = ("iM증권", "2026-11-04", "삼성전자")


def _payload(source_org, extra=None, entities=None):
    return {"source_org": source_org, "publish_date": "2026-11-04",
            "extra_metadata": extra if extra is not None else {"target": "삼성전자"},
            "entities": entities if entities is not None else ["삼성전자", "iM증권"]}


def test_matching_point_needs_no_update():
    update, logs = plan_point_update(_payload("iM증권"), *FILE)
    assert update is None and logs == []


def test_wrong_source_org_is_found_even_if_not_first_point():
    # 문서의 첫 요소가 맞고 두 번째 요소만 틀린 경우 (기존 스크립트가 놓치던 경우)
    first, _ = plan_point_update(_payload("iM증권"), *FILE)
    second, logs = plan_point_update(_payload("삼성증권"), *FILE)
    assert first is None
    assert second["source_org"] == "iM증권" and "source_org" in logs[0]


def test_point_own_extra_metadata_is_kept():
    extra = {"target": "삼성전자", "legacy": {"restore_note": "복원 기록"}, "reextract_note": "재추출"}
    update, _ = plan_point_update(_payload("삼성증권", extra=extra), *FILE)
    assert update["extra_metadata"]["legacy"]["restore_note"] == "복원 기록"
    assert update["extra_metadata"]["reextract_note"] == "재추출"
    assert update["extra_metadata"]["broker"] == "iM증권"


DICT_ROWS = "entity_name,entity_type,aliases,ticker\nCJ ENM,COMPANY,CJENM,035760\nKT&G,COMPANY,KTnG,033780\n삼성전자,COMPANY,삼전|Samsung Electronics,005930\n"


def _names(tmp_path):
    p = tmp_path / "entity_dictionary.csv"
    p.write_text(DICT_ROWS, encoding="utf-8")
    return fm.load_entity_names(p)


def test_filename_target_becomes_entity_name(tmp_path):
    names = _names(tmp_path)
    assert fm.to_entity_name("CJENM", names) == "CJ ENM"
    assert fm.to_entity_name("KTnG", names) == "KT&G"
    assert fm.to_entity_name("삼전", names) == "삼성전자"
    assert fm.to_entity_name("없는회사", names) == "없는회사"


def test_correct_entity_name_is_kept(tmp_path):
    names = _names(tmp_path)
    payload = {
        "source_org": "LS증권",
        "publish_date": "2026-11-06",
        "extra_metadata": {"target": "KT&G", "company": "KT&G", "broker": "LS증권"},
        "entities": ["KT&G", "LS증권"],
    }
    update, logs = fm.plan_point_update(payload, "LS증권", "2026-11-06", fm.to_entity_name("KTnG", names), names)
    assert update is None and logs == []


def test_alias_in_entities_is_replaced(tmp_path):
    names = _names(tmp_path)
    payload = {
        "source_org": "대신증권",
        "publish_date": "2026-11-06",
        "extra_metadata": {"target": "CJENM"},
        "entities": ["CJENM", "대신증권"],
    }
    update, _ = fm.plan_point_update(payload, "대신증권", "2026-11-06", "CJ ENM", names)
    assert update["extra_metadata"]["target"] == "CJ ENM"
    assert update["entities"] == ["CJ ENM", "대신증권"]
