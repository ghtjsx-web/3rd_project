"""검수 요청의 변경 판단(review_compare) 테스트."""

import json
import unittest

from shared.schemas import TableData
from app.review_compare import caption_changed, table_data_changed


STORED = {"columns": ["구분", "2024"], "rows": [{"구분": "매출", "2024": 1202.2}], "unit": "억원"}


def as_request(value):
    # 화면이 JSON으로 보내고 백엔드가 TableData로 받는 과정과 같게 만든다.
    return TableData.model_validate(json.loads(json.dumps(value)))


class TableDataChangedTests(unittest.TestCase):
    def test_same_content_missing_defaults_is_not_changed(self) -> None:
        # 저장된 값에 unit_by_row 등이 없어도 내용이 같으면 바뀐 것이 아니다.
        self.assertFalse(table_data_changed(STORED, as_request(STORED)))

    def test_edited_cell_is_changed(self) -> None:
        edited = json.loads(json.dumps(STORED))
        edited["rows"][0]["2024"] = 1300
        self.assertTrue(table_data_changed(STORED, as_request(edited)))

    def test_new_table_on_empty_is_changed(self) -> None:
        self.assertTrue(table_data_changed(None, as_request(STORED)))

    def test_invalid_stored_value_compared_as_is(self) -> None:
        broken = {"columns": ["구분"], "rows": "깨진 값"}
        self.assertTrue(table_data_changed(broken, as_request(STORED)))


class CaptionChangedTests(unittest.TestCase):
    def test_none_and_empty_are_same(self) -> None:
        self.assertFalse(caption_changed(None, ""))
        self.assertFalse(caption_changed(None, "  "))

    def test_same_text_is_not_changed(self) -> None:
        self.assertFalse(caption_changed("표 1. 매출", "표 1. 매출"))

    def test_different_text_is_changed(self) -> None:
        self.assertTrue(caption_changed("표 1. 매출", "표 1. 영업이익"))
        self.assertTrue(caption_changed(None, "새 캡션"))


if __name__ == "__main__":
    unittest.main()
