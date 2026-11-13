"""
상태 검사기 A1 (Git 변경 범위 및 수정 금지 파일 감시) 단위 테스트.
표준 라이브러리 unittest 기반으로 호스트 Python 환경에서 실행됩니다.
"""
import sys
from pathlib import Path
import unittest

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
for p in [str(SCRIPTS_DIR), str(REPO_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from check_state import check_a1_git_scope, normalize_repo_path


class TestCheckStateA1(unittest.TestCase):
    def setUp(self):
        self.protected_files = {
            "AGENTS.md",
            "PROJECT_RULES.md",
            "docs/glossary.md",
            "figindex/shared/schemas.py",
            "scripts/check_config.json",
            "scripts/check_baseline.json",
            "scripts/check_state.py",
        }

    def test_normalize_repo_path(self):
        """경로 정규화: 역슬래시 및 './' 접두사 제거 확인"""
        self.assertEqual(normalize_repo_path(r"docs\glossary.md"), "docs/glossary.md")
        self.assertEqual(normalize_repo_path("./AGENTS.md"), "AGENTS.md")
        self.assertEqual(normalize_repo_path(r".\scripts\check_state.py"), "scripts/check_state.py")
        self.assertEqual(normalize_repo_path("  figindex/pipeline/test.py  "), "figindex/pipeline/test.py")

    def test_protected_file_changed_fails(self):
        """1. 수정 금지 파일이 바뀜 -> FAIL"""
        changed = {"AGENTS.md", "figindex/pipeline/pdf_text.py"}
        res = check_a1_git_scope(
            changed_files=changed,
            protected_files=self.protected_files,
            allowed_protected_files=set(),
            expect_files=None,
        )
        self.assertEqual(res.status, "FAIL")
        self.assertIn("AGENTS.md", res.message)
        self.assertIn("수정 금지 파일(AGENTS.md)이 변경되었습니다.", res.message)

    def test_windows_path_separator_fails(self):
        """2. Windows 경로(docs\\glossary.md)로 들어와도 FAIL"""
        changed = {r"docs\glossary.md", "figindex/pipeline/pdf_text.py"}
        res = check_a1_git_scope(
            changed_files=changed,
            protected_files=self.protected_files,
            allowed_protected_files=set(),
            expect_files=None,
        )
        self.assertEqual(res.status, "FAIL")
        self.assertIn("docs/glossary.md", res.message)

    def test_allow_protected_warns_or_fails(self):
        """3. --allow-protected에 있으면 WARN, 없으면 FAIL"""
        # (3-1) 허용 목록에 있는 경우 -> WARN
        changed = {"AGENTS.md", "docs/glossary.md"}
        res_warn = check_a1_git_scope(
            changed_files=changed,
            protected_files=self.protected_files,
            allowed_protected_files={"AGENTS.md", "docs/glossary.md"},
            expect_files=None,
        )
        self.assertEqual(res_warn.status, "WARN")
        self.assertIn("팀장 승인으로 수정됨", res_warn.message)
        self.assertIn("AGENTS.md", res_warn.message)
        self.assertIn("docs/glossary.md", res_warn.message)

        # (3-2) 허용 목록에 일부만 있는 경우 -> 미허용 파일 때문에 FAIL
        res_fail = check_a1_git_scope(
            changed_files=changed,
            protected_files=self.protected_files,
            allowed_protected_files={"AGENTS.md"},  # docs/glossary.md는 미허용
            expect_files=None,
        )
        self.assertEqual(res_fail.status, "FAIL")
        self.assertIn("docs/glossary.md", res_fail.message)

    def test_normal_files_only_passes(self):
        """4. 일반 파일만 바뀜 -> PASS"""
        changed = {"figindex/pipeline/pdf_text.py", "figindex/pipeline/test_pdf_text.py"}
        res = check_a1_git_scope(
            changed_files=changed,
            protected_files=self.protected_files,
            allowed_protected_files=set(),
            expect_files=None,
        )
        self.assertEqual(res.status, "PASS")
        self.assertIn("변경 파일: 2개", res.message)

    def test_untracked_protected_file_fails(self):
        """5. untracked 파일로 새 수정 금지 파일이 생겨도 FAIL"""
        # 예를 들어 untracked로 scripts/check_baseline.json이 들어온 경우
        changed = {"scripts/check_baseline.json", "some_new_file.py"}
        res = check_a1_git_scope(
            changed_files=changed,
            protected_files=self.protected_files,
            allowed_protected_files=set(),
            expect_files=None,
        )
        self.assertEqual(res.status, "FAIL")
        self.assertIn("scripts/check_baseline.json", res.message)

    def test_expect_does_not_bypass_protected(self):
        """6. --expect에 명시되어 있어도 --allow-protected가 없으면 FAIL (우회 방지)"""
        changed = {"AGENTS.md", "figindex/pipeline/pdf_text.py"}
        res = check_a1_git_scope(
            changed_files=changed,
            protected_files=self.protected_files,
            allowed_protected_files=set(),  # 허용 없음
            expect_files={"AGENTS.md", "figindex/pipeline/pdf_text.py"},  # expect에는 포함
        )
        self.assertEqual(res.status, "FAIL")
        self.assertIn("AGENTS.md", res.message)


if __name__ == "__main__":
    unittest.main()
