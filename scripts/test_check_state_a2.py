"""
상태 검사기 A2 (금지 이름 검사) 및 A7 (문법 검사) 보완 단위 테스트.
표준 라이브러리 unittest 기반으로 실행됩니다.
"""
import re
import sys
from pathlib import Path
import unittest

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
for p in [str(SCRIPTS_DIR), str(REPO_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from check_state import StateChecker, normalize_repo_path


class TestCheckStateA2A7(unittest.TestCase):
    def setUp(self):
        self.checker = StateChecker(mode="quick")

    def test_legacy_allowed_files_excluded_from_a2(self):
        """1. legacy_allowed_files에 등록된 파일은 A2(금지 이름 검사)에서 제외(0건)되어야 함."""
        legacy_files = {
            normalize_repo_path(p)
            for p in self.checker.config.get("legacy_allowed_files", [])
        }
        self.assertTrue(len(legacy_files) > 0, "legacy_allowed_files 설정이 비어있지 않아야 함")

        # include_legacy=False인 대상 파일 목록에 legacy_files가 없어야 함
        target_files = {
            normalize_repo_path(p.relative_to(REPO_ROOT).as_posix())
            for p in self.checker.get_target_files(include_legacy=False)
        }
        overlap = target_files & legacy_files
        self.assertEqual(overlap, set(), f"A2 대상 파일에 legacy_allowed_files가 포함됨: {overlap}")

        # A2 실행 결과 메트릭에도 legacy_files가 없어야 함
        res_a2 = self.checker.run_check_a2_forbidden_names()
        strict_reported_files = set(res_a2.metrics.get("strict_counts", {}).keys())
        general_reported_files = set(res_a2.metrics.get("general_counts", {}).keys())

        self.assertEqual(strict_reported_files & legacy_files, set())
        self.assertEqual(general_reported_files & legacy_files, set())

    def test_legacy_allowed_files_included_in_a7(self):
        """2. legacy_allowed_files에 등록된 Python 파일이 A7(문법 검사)에는 반드시 포함되어야 함."""
        legacy_files = {
            normalize_repo_path(p)
            for p in self.checker.config.get("legacy_allowed_files", [])
        }
        legacy_py_files = {p for p in legacy_files if p.endswith(".py")}
        self.assertTrue(len(legacy_py_files) > 0, "legacy Python 파일이 존재해야 함")

        # include_legacy=True인 대상 파일 목록에 legacy_py_files가 모두 포함되어야 함
        target_py_files = {
            normalize_repo_path(p.relative_to(REPO_ROOT).as_posix())
            for p in self.checker.get_target_files(include_legacy=True)
            if p.suffix == ".py"
        }
        missing = legacy_py_files - target_py_files
        self.assertEqual(missing, set(), f"A7 대상 파일에서 legacy Python 파일이 누락됨: {missing}")

        # A7 실행 결과 checked_files_list에도 모두 포함되어야 함
        res_a7 = self.checker.run_check_a7_syntax()
        checked_list = set(res_a7.metrics.get("checked_files_list", []))
        self.assertTrue(legacy_py_files.issubset(checked_list))
        self.assertEqual(res_a7.status, "PASS")

    def test_a2_console_message_format_with_baseline(self):
        """3. A2 메시지에 현재 수치와 기준선 수치('엄격 X건 (기준선 Y건, ...)')가 함께 표시되어야 함."""
        res_a2 = self.checker.run_check_a2_forbidden_names()
        # 메시지 예시: "통과 (엄격 131건 (기준선 131건, 유지), 일반 64건)"
        pattern = r"엄격\s+\d+건\s*\(기준선\s+\d+건,\s*(?:유지|\d+건\s*(?:감소|증가))\)"
        self.assertRegex(
            res_a2.message,
            pattern,
            f"A2 메시지가 요구 포맷을 만족하지 않음: '{res_a2.message}'"
        )

    def test_a2_metrics_and_sorting(self):
        """4. A2 메트릭에 상위 파일 목록(정렬된 strict, general) 및 제외 파일 목록이 포함되어야 함."""
        res_a2 = self.checker.run_check_a2_forbidden_names()
        sorted_strict = res_a2.metrics.get("sorted_strict_files", [])
        sorted_gen = res_a2.metrics.get("sorted_general_files", [])

        self.assertIsInstance(sorted_strict, list)
        self.assertIsInstance(sorted_gen, list)

        # 내림차순 정렬 확인
        strict_totals = [item["total"] for item in sorted_strict]
        self.assertEqual(strict_totals, sorted(strict_totals, reverse=True))

        gen_totals = [item["total"] for item in sorted_gen]
        self.assertEqual(gen_totals, sorted(gen_totals, reverse=True))

        # 세부 건수 dict 존재 확인
        if sorted_strict:
            first = sorted_strict[0]
            self.assertIn("file", first)
            self.assertIn("total", first)
            self.assertIn("counts", first)
            self.assertEqual(first["total"], sum(first["counts"].values()))


if __name__ == "__main__":
    unittest.main()

