"""analyze_comparability 종목명 정규화: 엔티티 사전만 기준으로 하는지 (AGENTS.md 5절)."""
from pathlib import Path

import analyze_comparability as ac

ROWS = "entity_name,entity_type,aliases,ticker\nKT&G,COMPANY,KTnG,033780\n엘앤에프,COMPANY,LNF|L&F,066970\nSK텔레콤,COMPANY,SKT,017670\n"


def _dict(tmp_path: Path):
    p = tmp_path / "entity_dictionary.csv"
    p.write_text(ROWS, encoding="utf-8")
    return ac.load_entity_dictionary(p)


def test_ticker_and_alias_map_to_entity_name(tmp_path):
    d = _dict(tmp_path)
    assert ac.normalize_target_company({"ticker": "066970"}, d)[0] == "엘앤에프"
    assert ac.normalize_target_company({"target": "LNF"}, d)[0] == "엘앤에프"
    assert ac.normalize_target_company({"target": "ktng"}, d)[0] == "KT&G"
    assert ac.normalize_target_company({"target": "sk텔레콤"}, d)[0] == "SK텔레콤"


def test_unknown_name_is_kept(tmp_path):
    d = _dict(tmp_path)
    assert ac.normalize_target_company({"target": "없는회사"}, d)[0] == "없는회사"


def test_no_hardcoded_name_maps():
    assert not hasattr(ac, "KNOWN_TICKER_MAP")
    assert not hasattr(ac, "KNOWN_NAME_ALIAS")
