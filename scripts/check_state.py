#!/usr/bin/env python3
"""
FigIndex 상태 검사기 (scripts/check_state.py)

목적:
  코드를 수정할 때마다 일관된 기준으로 프로젝트의 정합성을 검사합니다.
  - 읽기 전용 검사기 (Qdrant 및 백엔드 API에 쓰기 요청 전송 금지)
  - 기준선(scripts/check_baseline.json)과의 비교를 통한 품질 회귀 감지
  - 호스트(Windows) 환경 표준 라이브러리만 사용

종료 코드:
  0: 모든 검사 통과 (WARN / CHANGED / SKIP 포함)
  1: FAIL 항목 존재
  2: 검사기 자체 오류 또는 설정/환경 결함
"""

import argparse
import ast
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Windows 콘솔 인코딩 대응
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "scripts" / "check_config.json"
BASELINE_PATH = REPO_ROOT / "scripts" / "check_baseline.json"
REPORTS_DIR = REPO_ROOT / ".check_reports"

# B그룹 허용 요청 엔드포인트 화이트리스트 (이 외의 요청은 코드상에서 차단)
ALLOWED_REQUEST_PATTERNS = [
    r"^http://[^/]+(?::\d+)?/api/version$",
    r"^http://[^/]+(?::\d+)?/health$",
    r"^http://[^/]+(?::\d+)?/api/filter-options$",
    r"^http://[^/]+(?::\d+)?/api/elements(?:\?.*)?$",
    r"^http://[^/]+(?::\d+)?/api/elements/[^/]+$",
    r"^http://[^/]+(?::\d+)?/static/crops/[^/]+$",
    r"^http://[^/]+(?::\d+)?/api/files/crops/[^/]+$",
    r"^http://[^/]+(?::\d+)?/collections/[^/]+$",
    r"^http://[^/]+(?::\d+)?/collections/[^/]+/points/count$",
    r"^http://[^/]+(?::\d+)?/collections/[^/]+/points/scroll$",
]


def is_allowed_request(method: str, url: str) -> bool:
    """요청 메서드와 URL이 읽기 전용 화이트리스트에 부합하는지 검증합니다."""
    m = method.upper()
    if m not in ("GET", "POST", "HEAD"):
        return False

    matched = any(re.match(pattern, url) for pattern in ALLOWED_REQUEST_PATTERNS)
    if not matched:
        return False

    # Qdrant의 경우 GET은 /collections/{c}, POST는 /count 또는 /scroll 만 허용
    if "/collections/" in url and m == "POST":
        if not (url.endswith("/points/count") or url.endswith("/points/scroll")):
            return False

    return True


def safe_http_request(
    method: str,
    url: str,
    data: Optional[Dict[str, Any]] = None,
    timeout: float = 10.0
) -> Tuple[int, Any, Optional[str]]:
    """화이트리스트 검증을 거친 안전한 HTTP 요청 헬퍼 (표준 라이브러리 사용)."""
    if not is_allowed_request(method, url):
        return -1, None, f"보안 위반: 허용되지 않은 HTTP 요청 ({method} {url})"

    req_data = None
    headers = {"User-Agent": "FigIndex-State-Checker/1.0"}
    if data is not None:
        req_data = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=req_data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            raw_bytes = resp.read()

            # 이미지 바이너리 응답인 경우 성공 처리 (디코드 생략)
            if content_type.startswith("image/"):
                return status, raw_bytes, None

            try:
                body = raw_bytes.decode("utf-8")
            except UnicodeDecodeError:
                # 텍스트가 아닌 바이너리인 경우
                return status, raw_bytes, None

            try:
                parsed = json.loads(body)
            except Exception:
                parsed = body
            return status, parsed, None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        return e.code, None, f"HTTP {e.code}: {raw[:200]}"
    except Exception as e:
        return -1, None, str(e)


class CheckResult:
    def __init__(self, code: str, title: str):
        self.code = code
        self.title = title
        self.status: str = "PASS"  # PASS, WARN, CHANGED, FAIL, SKIP
        self.message: str = ""
        self.details: List[str] = []
        self.metrics: Dict[str, Any] = {}

    def fail(self, msg: str, detail: Optional[str] = None):
        self.status = "FAIL"
        self.message = msg
        if detail:
            self.details.append(detail)

    def warn(self, msg: str, detail: Optional[str] = None):
        if self.status != "FAIL":
            self.status = "WARN"
            self.message = msg
        if detail:
            self.details.append(detail)

    def changed(self, msg: str, detail: Optional[str] = None):
        if self.status not in ("FAIL", "WARN"):
            self.status = "CHANGED"
        self.message = msg
        if detail:
            self.details.append(detail)

    def skip(self, reason: str):
        self.status = "SKIP"
        self.message = reason

    def pass_(self, msg: str = "통과"):
        if self.status not in ("FAIL", "WARN", "CHANGED"):
            self.status = "PASS"
            self.message = msg


def normalize_repo_path(path_str: str) -> str:
    """경로를 저장소 루트 기준 상대 경로이자 '/' 구분자, './' 접두사 제거 형태로 정규화합니다."""
    p = str(path_str).strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def check_a1_git_scope(
    changed_files: Set[str],
    protected_files: Set[str],
    allowed_protected_files: Set[str],
    expect_files: Optional[Set[str]],
    branch: str = "HEAD",
) -> CheckResult:
    """A1. Git 변경 범위 및 수정 금지 파일 검사 (단위 테스트 가능한 순수 로직)."""
    res = CheckResult("A1", "Git 변경 범위")
    res.metrics["branch"] = branch

    norm_changed = {normalize_repo_path(f) for f in changed_files if f.strip()}
    norm_protected = {normalize_repo_path(p) for p in protected_files if p.strip()}
    norm_allowed = {normalize_repo_path(a) for a in allowed_protected_files if a.strip()}
    norm_expect = {normalize_repo_path(e) for e in expect_files if e.strip()} if expect_files is not None else None

    res.metrics["changed_files"] = sorted(list(norm_changed))
    res.metrics["protected_files"] = sorted(list(norm_protected))

    # 1. 수정 금지 파일 검사
    protected_changed = norm_changed & norm_protected
    unauthorized_protected = protected_changed - norm_allowed
    authorized_protected = protected_changed & norm_allowed

    res.metrics["authorized_protected"] = sorted(list(authorized_protected))
    res.metrics["unauthorized_protected"] = sorted(list(unauthorized_protected))

    if unauthorized_protected:
        unauth_list = sorted(list(unauthorized_protected))
        res.fail(
            f"수정 금지 파일({', '.join(unauth_list)})이 변경되었습니다.",
            detail=f"수정 금지: {', '.join(unauth_list)}"
        )
        for uf in unauth_list:
            res.details.append(f"수정 금지: {uf}")
        if authorized_protected:
            auth_list = sorted(list(authorized_protected))
            res.details.append(f"팀장 승인 예외: {', '.join(auth_list)}")
    elif authorized_protected:
        auth_list = sorted(list(authorized_protected))
        res.warn(
            f"팀장 승인으로 수정됨: {', '.join(auth_list)}",
            detail=f"팀장 승인 수정: {', '.join(auth_list)}"
        )

    # 2. --expect 범위 검사 (수정 금지 여부와 무관하게 변경 예상 범위 검사)
    if norm_expect is not None:
        unexpected = norm_changed - norm_expect
        # 임시 리포트 파일은 제외
        unexpected = {f for f in unexpected if not f.startswith(".check_reports/")}
        if unexpected:
            res.fail(
                f"--expect 목록 이외의 파일({len(unexpected)}개)이 변경되었습니다.",
                f"예상 밖 변경: {', '.join(sorted(list(unexpected))[:5])}"
            )

    if res.status not in ("FAIL", "WARN"):
        res.pass_(f"브랜치: {branch}, 변경 파일: {len(norm_changed)}개")

    return res


class StateChecker:
    def __init__(
        self,
        mode: str = "quick",
        expect: Optional[str] = None,
        base: str = "HEAD",
        no_docker: bool = False,
        collection_override: Optional[str] = None,
        allow_protected: Optional[str] = None,
    ):
        self.mode = mode
        self.expect_raw = expect
        self.expect_files: Optional[Set[str]] = (
            {normalize_repo_path(f) for f in expect.split(",") if f.strip()}
            if expect
            else None
        )
        self.allow_protected_raw = allow_protected
        self.allow_protected_files: Set[str] = (
            {normalize_repo_path(f) for f in allow_protected.split(",") if f.strip()}
            if allow_protected
            else set()
        )
        self.base = base
        self.no_docker = no_docker

        # 설정 파일 로드
        if not CONFIG_PATH.exists():
            print(f"[Error] 설정 파일이 없습니다: {CONFIG_PATH}")
            sys.exit(2)

        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except Exception as e:
            print(f"[Error] 설정 파일 파싱 실패: {e}")
            sys.exit(2)

        self.collection = collection_override or self.config.get("collection", "figindex_elements")
        self.api_base = self.config.get("api_base", "http://localhost:8000").rstrip("/")
        self.qdrant_url = self.config.get("qdrant_url", "http://localhost:6333").rstrip("/")

        # 기준선 로드
        self.baseline: Optional[Dict[str, Any]] = None
        if BASELINE_PATH.exists():
            try:
                with open(BASELINE_PATH, "r", encoding="utf-8") as f:
                    self.baseline = json.load(f)
            except Exception as e:
                print(f"[Warn] 기준선 파일 로드 실패 (기준선 없음으로 처리): {e}")
                self.baseline = None

        self.results: List[CheckResult] = []
        self.current_metrics: Dict[str, Any] = {}

    def is_path_excluded(self, rel_posix: str, excludes: List[str]) -> bool:
        """경로가 제외 목록에 해당하는지 판별합니다.
        루트의 'app' 디렉토리는 하위의 'backend/app'과 혼동되지 않도록 루트 매칭만 수행합니다.
        """
        parts = rel_posix.split("/")
        for ex in excludes:
            if ex == "app":
                if rel_posix == "app" or rel_posix.startswith("app/"):
                    return True
            elif ex in parts or rel_posix == ex or rel_posix.startswith(f"{ex}/"):
                return True
        return False

    def get_target_files(self) -> List[Path]:
        """scan_dirs 대상 파일 중 exclude 및 legacy_allowed_files 필터링 목록을 구합니다."""
        scan_dirs = [REPO_ROOT / d for d in self.config.get("scan_dirs", [])]
        excludes = self.config.get("exclude", [])
        legacy_allowed = {
            Path(p).as_posix() for p in self.config.get("legacy_allowed_files", [])
        }

        collected: List[Path] = []
        for sdir in scan_dirs:
            if not sdir.exists():
                continue
            for root, dirs, files in os.walk(sdir):
                # Exclude 디렉토리 가지치기
                dirs[:] = [
                    d for d in dirs
                    if not self.is_path_excluded(Path(root, d).relative_to(REPO_ROOT).as_posix(), excludes)
                ]
                for file in files:
                    p = Path(root, file)
                    rel = p.relative_to(REPO_ROOT).as_posix()
                    if self.is_path_excluded(rel, excludes):
                        continue
                    if rel in legacy_allowed:
                        continue
                    if p.suffix in (".py", ".ts", ".tsx"):
                        collected.append(p)
        return collected

    # =========================================================================
    # A그룹: 빠른 검사
    # =========================================================================

    def run_check_a1_git_scope(self) -> CheckResult:
        """A1. Git 변경 범위 검사"""
        branch_proc = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        branch = branch_proc.stdout.strip() or "HEAD(detached)"

        # 변경 파일 목록 추출 (base 대비 diff + untracked)
        diff_proc = subprocess.run(
            ["git", "diff", "--name-only", self.base],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        untracked_proc = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8"
        )

        changed = set()
        for line in (diff_proc.stdout + "\n" + untracked_proc.stdout).splitlines():
            line = line.strip()
            if line:
                changed.add(normalize_repo_path(line))

        protected = {normalize_repo_path(p) for p in self.config.get("protected_files", [])}

        return check_a1_git_scope(
            changed_files=changed,
            protected_files=protected,
            allowed_protected_files=self.allow_protected_files,
            expect_files=self.expect_files,
            branch=branch,
        )

    def run_check_a2_forbidden_names(self) -> CheckResult:
        """A2. 금지 이름 검사 (AGENTS.md 2절 직접 추출)"""
        res = CheckResult("A2", "금지 이름 검사")
        agents_path = REPO_ROOT / "AGENTS.md"
        if not agents_path.exists():
            print("[Error] AGENTS.md 파일이 없습니다.")
            sys.exit(2)

        try:
            with open(agents_path, "r", encoding="utf-8") as f:
                agents_content = f.read()
        except Exception as e:
            print(f"[Error] AGENTS.md 읽기 실패: {e}")
            sys.exit(2)

        # 2절 쓰지 않는 이름 표 파싱
        section2_match = re.search(r"## 2\.\s*쓰지 않는 이름\s*\n(.*?)(?=\n##\s|\Z)", agents_content, re.DOTALL)
        if not section2_match:
            print("[Error] AGENTS.md에서 '## 2. 쓰지 않는 이름' 절을 찾을 수 없습니다.")
            sys.exit(2)

        forbidden_names: Set[str] = set()
        for line in section2_match.group(1).splitlines():
            line = line.strip()
            if not line.startswith("|") or "---" in line or "쓰지 말 것" in line:
                continue
            cols = [c.strip() for c in line.split("|")]
            if len(cols) >= 2:
                col1 = cols[1]
                matches = re.findall(r"`([^`]+)`", col1)
                for m in matches:
                    forbidden_names.add(m.strip())

        if not forbidden_names:
            print("[Error] AGENTS.md 표에서 금지 이름을 추출하지 못했습니다.")
            sys.exit(2)

        # 등급 분류
        strict_extra = set(self.config.get("strict_extra", []))
        strict_names: Set[str] = set()
        general_names: Set[str] = set()

        for name in forbidden_names | strict_extra:
            if "_" in name or any(c.isupper() for c in name) or name in strict_extra:
                strict_names.add(name)
            else:
                general_names.add(name)

        target_files = self.get_target_files()

        strict_counts: Dict[str, Dict[str, int]] = {}
        general_counts: Dict[str, Dict[str, int]] = {}
        total_strict = 0
        total_general = 0

        strict_regexes = {name: re.compile(rf"\b{re.escape(name)}\b") for name in strict_names}
        general_key_regexes = {name: re.compile(rf"""(?:["']{re.escape(name)}["']|\b{re.escape(name)}\s*=)""") for name in general_names}

        for p in target_files:
            rel = p.relative_to(REPO_ROOT).as_posix()
            try:
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                continue

            # Strict 검사 (.py, .ts, .tsx)
            file_strict: Dict[str, int] = {}
            for name, regex in strict_regexes.items():
                cnt = len(regex.findall(content))
                if cnt > 0:
                    file_strict[name] = cnt
                    total_strict += cnt
            if file_strict:
                strict_counts[rel] = file_strict

            # General 검사 (.py 파일만 키/인자)
            if p.suffix == ".py":
                file_gen: Dict[str, int] = {}
                for name, regex in general_key_regexes.items():
                    cnt = len(regex.findall(content))
                    if cnt > 0:
                        file_gen[name] = cnt
                        total_general += cnt
                if file_gen:
                    general_counts[rel] = file_gen

        res.metrics["total_strict"] = total_strict
        res.metrics["total_general"] = total_general
        res.metrics["strict_counts"] = strict_counts
        res.metrics["general_counts"] = general_counts

        # 기준선 비교
        baseline_a2 = (self.baseline or {}).get("A2", {})
        base_strict = baseline_a2.get("total_strict")
        base_strict_counts = baseline_a2.get("strict_counts", {})

        if base_strict is not None:
            if total_strict > base_strict:
                res.fail(
                    f"엄격 금지 이름이 기준선 대비 증가했습니다 ({base_strict} ➔ {total_strict})",
                    f"증가 건수: +{total_strict - base_strict}"
                )
            else:
                # 파일별 신규 출현 확인
                new_files = set(strict_counts.keys()) - set(base_strict_counts.keys())
                if new_files:
                    res.fail(
                        f"기준선에 없던 파일({len(new_files)}개)에서 엄격 금지 이름이 발견되었습니다.",
                        f"신규 파일: {', '.join(sorted(list(new_files))[:3])}"
                    )
                elif total_strict < base_strict:
                    res.pass_(f"개선: 엄격 금지 이름 {base_strict - total_strict}건 감소 (현재 {total_strict}건)")
                else:
                    res.pass_(f"통과 (엄격 {total_strict}건 유지, 일반 {total_general}건)")
        else:
            res.pass_(f"기준선 없음: 현재 엄격 {total_strict}건, 일반 {total_general}건 측정됨")

        return res

    def run_check_a3_status_literals(self) -> CheckResult:
        """A3. 직접 쓴 상태 문자열 리터럴 검사"""
        res = CheckResult("A3", "직접 쓴 상태 문자열")
        schemas_path = REPO_ROOT / "figindex" / "shared" / "schemas.py"
        if not schemas_path.exists():
            res.fail("schemas.py 파일이 존재하지 않습니다.")
            return res

        # schemas.py에서 상태 Enum 값 파싱 (LayoutClass 제외)
        try:
            with open(schemas_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename="schemas.py")
        except Exception as e:
            res.fail(f"schemas.py AST 파싱 실패: {e}")
            return res

        target_enums = {"ElementType", "DocStatus", "ReviewStatus", "ReviewAction", "EntityType"}
        status_literals: Set[str] = set()

        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name in target_enums:
                for stmt in node.body:
                    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                        if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                            status_literals.add(stmt.value.value)

        # .py 파일 AST 검사
        target_py_files = [p for p in self.get_target_files() if p.suffix == ".py"]
        found_literals: Dict[str, Dict[str, int]] = {}
        total_count = 0

        for p in target_py_files:
            rel = p.relative_to(REPO_ROOT).as_posix()
            try:
                with open(p, "r", encoding="utf-8") as f:
                    file_tree = ast.parse(f.read(), filename=rel)
            except Exception:
                continue

            file_counts: Dict[str, int] = {}
            for node in ast.walk(file_tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if node.value in status_literals:
                        file_counts[node.value] = file_counts.get(node.value, 0) + 1
                        total_count += 1
            if file_counts:
                found_literals[rel] = file_counts

        res.metrics["total_status_literals"] = total_count
        res.metrics["found_literals"] = found_literals

        base_count = (self.baseline or {}).get("A3", {}).get("total_status_literals")
        if base_count is not None:
            if total_count > base_count:
                res.fail(
                    f"직접 쓴 상태 문자열이 기준선 대비 증가했습니다 ({base_count} ➔ {total_count})",
                    f"증가 건수: +{total_count - base_count}"
                )
            elif total_count < base_count:
                res.pass_(f"개선: 상태 문자열 {base_count - total_count}건 감소 (현재 {total_count}건)")
            else:
                res.pass_(f"통과 (상태 문자열 {total_count}건 유지)")
        else:
            res.pass_(f"기준선 없음: 현재 상태 문자열 {total_count}건 측정됨")

        return res

    def run_check_a4_threshold_literals(self) -> CheckResult:
        """A4. 직접 쓴 확신도 임계값 리터럴(0.8 / 0.80) 검사"""
        res = CheckResult("A4", "직접 쓴 확신도 임계값")
        target_py_files = [p for p in self.get_target_files() if p.suffix == ".py"]
        found_thresholds: Dict[str, int] = {}
        total_count = 0

        for p in target_py_files:
            rel = p.relative_to(REPO_ROOT).as_posix()
            try:
                with open(p, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=rel)
            except Exception:
                continue

            cnt = 0
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                    if abs(float(node.value) - 0.80) < 1e-6:
                        cnt += 1
            if cnt > 0:
                found_thresholds[rel] = cnt
                total_count += cnt

        res.metrics["total_threshold_literals"] = total_count
        res.metrics["found_thresholds"] = found_thresholds

        base_count = (self.baseline or {}).get("A4", {}).get("total_threshold_literals")
        if base_count is not None:
            if total_count > base_count:
                res.fail(
                    f"직접 쓴 0.8 임계값이 기준선 대비 증가했습니다 ({base_count} ➔ {total_count})",
                    f"증가 건수: +{total_count - base_count}"
                )
            elif total_count < base_count:
                res.pass_(f"개선: 임계값 리터럴 {base_count - total_count}건 감소 (현재 {total_count}건)")
            else:
                res.pass_(f"통과 (임계값 리터럴 {total_count}건 유지)")
        else:
            res.pass_(f"기준선 없음: 현재 0.8 임계값 {total_count}건 측정됨")

        return res

    def run_check_a5_import_rules(self) -> CheckResult:
        """A5. Import 규칙 검사 (app.schemas 금지 및 schemas_legacy 신규 파일 제한)"""
        res = CheckResult("A5", "Import 규칙")
        scan_dirs = [REPO_ROOT / "figindex", REPO_ROOT / "scripts"]
        app_schemas_regex = re.compile(r"""(?:from\s+app\.schemas\b|import\s+app\.schemas\b|from\s+app/schemas|['"]app/schemas)""")
        legacy_import_regex = re.compile(r"""(?:from\s+shared\.schemas_legacy\b|schemas_legacy)""")

        app_schemas_violations = []
        legacy_importers = set()

        for sdir in scan_dirs:
            for root, dirs, files in os.walk(sdir):
                if any(ex in root for ex in ("node_modules", ".next", "__pycache__")):
                    continue
                for file in files:
                    if file.endswith((".py", ".ts", ".tsx")):
                        p = Path(root, file)
                        rel = p.relative_to(REPO_ROOT).as_posix()
                        if rel in ("figindex/shared/schemas_legacy.py", "scripts/check_state.py"):
                            continue
                        try:
                            with open(p, "r", encoding="utf-8") as f:
                                content = f.read()
                        except Exception:
                            continue

                        if app_schemas_regex.search(content):
                            app_schemas_violations.append(rel)
                        if legacy_import_regex.search(content):
                            legacy_importers.add(rel)

        res.metrics["app_schemas_violations"] = app_schemas_violations
        res.metrics["legacy_importers"] = sorted(list(legacy_importers))

        # 1. app.schemas 참조는 항상 FAIL
        if app_schemas_violations:
            res.fail(
                f"금지된 app.schemas 참조가 발견되었습니다 ({len(app_schemas_violations)}개 파일).",
                f"위반 파일: {', '.join(app_schemas_violations)}"
            )

        # 2. schemas_legacy를 import하는 파일이 기준선 목록에 없던 파일이면 FAIL
        base_importers = set((self.baseline or {}).get("A5", {}).get("legacy_importers", []))
        if self.baseline is not None:
            new_importers = legacy_importers - base_importers
            if new_importers:
                res.fail(
                    f"schemas_legacy를 참조하는 새 파일이 발견되었습니다 ({len(new_importers)}개).",
                    f"새 참조 파일: {', '.join(sorted(list(new_importers)))}"
                )

        if res.status != "FAIL":
            res.pass_(f"통과 (app.schemas 0건, legacy 참조 {len(legacy_importers)}개 파일)")

        return res

    def run_check_a6_model_duplicates(self) -> CheckResult:
        """A6. Pydantic BaseModel 중복 정의 검사"""
        res = CheckResult("A6", "모델 중복 정의")
        schemas_path = REPO_ROOT / "figindex" / "shared" / "schemas.py"
        if not schemas_path.exists():
            res.fail("schemas.py 파일이 없습니다.")
            return res

        schemas_models: Set[str] = set()
        try:
            with open(schemas_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    schemas_models.add(node.name)
        except Exception as e:
            res.fail(f"schemas.py 파싱 실패: {e}")
            return res

        target_py_files = [
            p for p in self.get_target_files()
            if p.suffix == ".py" and p != schemas_path
        ]

        duplicate_models = []
        new_classes = []

        base_classes = set((self.baseline or {}).get("A6", {}).get("all_models", []))

        all_models = set(schemas_models)

        for p in target_py_files:
            rel = p.relative_to(REPO_ROOT).as_posix()
            try:
                with open(p, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=rel)
            except Exception:
                continue

            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    # BaseModel 상속 여부 확인
                    is_pydantic = any(
                        (isinstance(base, ast.Name) and "Model" in base.id) or
                        (isinstance(base, ast.Attribute) and "Model" in base.attr)
                        for base in node.bases
                    )
                    if is_pydantic:
                        all_models.add(node.name)
                        if node.name in schemas_models:
                            duplicate_models.append(f"{node.name} ({rel})")
                        elif self.baseline is not None and node.name not in base_classes:
                            new_classes.append(f"{node.name} ({rel})")

        res.metrics["all_models"] = sorted(list(all_models))
        res.metrics["duplicate_models"] = duplicate_models

        if duplicate_models:
            res.fail(
                f"schemas.py와 동일한 이름의 모델이 재정의되었습니다: {', '.join(duplicate_models[:3])}",
                f"중복 목록: {', '.join(duplicate_models)}"
            )
        elif new_classes:
            res.warn(
                f"새로운 Pydantic 모델이 정의되었습니다 ({len(new_classes)}개).",
                f"새 모델: {', '.join(new_classes)}"
            )
        else:
            res.pass_("통과 (중복 정의 0건)")

        return res

    def run_check_a7_syntax(self) -> CheckResult:
        """A7. 대상 Python 파일 전체 문법 컴파일 검사"""
        res = CheckResult("A7", "Python 문법 검사")
        target_py_files = [p for p in self.get_target_files() if p.suffix == ".py"]
        syntax_errors = []
        checked_list = [p.relative_to(REPO_ROOT).as_posix() for p in target_py_files]

        for p in target_py_files:
            rel = p.relative_to(REPO_ROOT).as_posix()
            try:
                with open(p, "r", encoding="utf-8") as f:
                    source = f.read()
                compile(source, rel, "exec")
            except Exception as e:
                syntax_errors.append(f"{rel}: {e}")

        res.metrics["checked_files"] = len(target_py_files)
        res.metrics["checked_files_list"] = sorted(checked_list)
        res.metrics["syntax_errors"] = syntax_errors

        for fpath in sorted(checked_list):
            res.details.append(f"검사 대상 파일: {fpath}")

        if syntax_errors:
            res.fail(f"문법 오류 파일 발견 ({len(syntax_errors)}건)", "; ".join(syntax_errors[:3]))
        else:
            res.pass_(f"통과 ({len(target_py_files)}개 파일 문법 정상)")

        return res

    def run_check_a8_unit_tests(self) -> CheckResult:
        """A8. 파이프라인 단위 테스트 검사"""
        res = CheckResult("A8", "단위 테스트 검사")
        if self.no_docker:
            res.skip("Docker 실행 생략 옵션 (--no-docker)")
            return res

        # Docker compose run으로 pytest 실행 시도
        compose_file = REPO_ROOT / "figindex" / "docker-compose.yml"
        cmd = [
            "docker", "compose", "-f", str(compose_file),
            "run", "--rm", "pipeline", "python", "-m", "pytest", "-q"
        ]

        try:
            proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=60, encoding="utf-8")
            output = proc.stdout + "\n" + proc.stderr
        except subprocess.TimeoutExpired:
            res.fail("단위 테스트 실행 시간 초과 (60초)")
            return res
        except Exception as e:
            res.skip(f"Docker 실행 불가: {e}")
            return res

        if "failed to connect to the docker API" in output or "The system cannot find the file specified" in output:
            res.skip("Docker 데몬이 실행 중이지 않음 (테스트 SKIP)")
            return res

        if proc.returncode != 0 and "passed" not in output and "failed" not in output:
            if "No module named pytest" in output:
                res.fail("단위 테스트 실행 실패: pytest 미설치 → pipeline 이미지 재빌드 필요 (`docker compose build pipeline`)", output.strip()[:300])
                return res
            if any(err in output for err in ("failed to connect", "docker API", "Access is denied", "unknown shorthand flag", "cannot find", "Error loading config")):
                res.skip(f"Docker 실행 환경 접근 불가 (SKIP): {output.strip()[:100]}")
                return res
            res.fail(f"단위 테스트 실행 실패 (코드 {proc.returncode})", output[:300])
            return res

        # pytest 결과 파싱: e.g. "26 passed in 2.39s" or "1 failed, 25 passed"
        passed_match = re.search(r"(\d+)\s+passed", output)
        failed_match = re.search(r"(\d+)\s+failed", output)

        passed_count = int(passed_match.group(1)) if passed_match else 0
        failed_count = int(failed_match.group(1)) if failed_match else 0

        res.metrics["passed_count"] = passed_count
        res.metrics["failed_count"] = failed_count

        base_passed = (self.baseline or {}).get("A8", {}).get("passed_count")
        if failed_count > 0:
            res.fail(f"단위 테스트 실패 ({failed_count}건 실패, {passed_count}건 통과)", output[:300])
        elif base_passed is not None and passed_count < base_passed:
            res.fail(f"통과한 단위 테스트 수가 감소했습니다 ({base_passed} ➔ {passed_count})")
        else:
            res.pass_(f"통과 ({passed_count}건 성공)")

        return res

    # =========================================================================
    # B그룹: 전체 검사 (--full)
    # =========================================================================

    def run_check_b1_api_health(self) -> CheckResult:
        """B1. 백엔드 API 상태 검사"""
        res = CheckResult("B1", "API 상태 검사")
        # 1. /api/version
        v_status, v_body, v_err = safe_http_request("GET", f"{self.api_base}/api/version")
        if v_status != 200:
            res.fail(f"/api/version 응답 실패 (HTTP {v_status})", v_err)
            return res

        # 2. /health 및 Qdrant 개수 비교
        h_status, h_body, h_err = safe_http_request("GET", f"{self.api_base}/health")
        if h_status != 200 or not isinstance(h_body, dict):
            res.fail(f"/health 조회 실패 (HTTP {h_status})", h_err)
            return res

        backend_count = h_body.get("total_elements", 0)

        # Qdrant 컬렉션 직접 개수 조회
        q_status, q_body, q_err = safe_http_request(
            "POST",
            f"{self.qdrant_url}/collections/{self.collection}/points/count",
            data={"exact": True}
        )
        if q_status == 200 and isinstance(q_body, dict):
            qdrant_count = q_body.get("result", {}).get("count", 0)
            if backend_count != qdrant_count:
                res.fail(f"백엔드 /health 개수({backend_count})와 Qdrant 실측치({qdrant_count}) 불일치")
                return res
        res.metrics["point_count"] = backend_count

        # 3. /api/filter-options
        f_status, _, f_err = safe_http_request("GET", f"{self.api_base}/api/filter-options")
        if f_status != 200:
            res.fail(f"/api/filter-options 응답 실패 (HTTP {f_status})", f_err)
            return res

        # 4. 요소 3개 샘플링 상세 및 크롭 이미지 검사
        el_status, el_body, el_err = safe_http_request("GET", f"{self.api_base}/api/elements?limit=3")
        sample_failures = 0
        failure_details: List[str] = []

        if el_status == 200 and isinstance(el_body, list) and el_body:
            for item in el_body[:3]:
                eid = item.get("element_id")
                img_path = item.get("image_path")
                if eid:
                    elem_url = f"{self.api_base}/api/elements/{eid}"
                    d_st, _, d_err = safe_http_request("GET", elem_url)
                    if d_st != 200:
                        sample_failures += 1
                        failure_details.append(f"요소 상세 조회 실패: {elem_url} (HTTP {d_st}, {d_err or '오류'})")
                if img_path:
                    img_url = f"{self.api_base}{img_path}" if img_path.startswith("/") else f"{self.api_base}/{img_path}"
                    im_st, _, im_err = safe_http_request("GET", img_url)
                    if im_st != 200:
                        sample_failures += 1
                        failure_details.append(f"크롭 이미지 조회 실패: {img_url} (HTTP {im_st}, {im_err or '오류'})")

        res.metrics["sample_failures"] = sample_failures
        res.metrics["sample_failure_details"] = failure_details

        base_failures = (self.baseline or {}).get("B1", {}).get("sample_failures")
        if base_failures is None:
            # 기준선이 없을 때: 0이 아니면 실패
            if sample_failures > 0:
                res.fail(
                    f"샘플 요소/이미지 조회 실패 ({sample_failures}건)",
                    "; ".join(failure_details)
                )
            else:
                res.pass_(f"통과 (포인트 수: {backend_count}건, 필터/상세/이미지 정상)")
        else:
            if sample_failures > base_failures:
                res.fail(
                    f"샘플 요소/이미지 조회 실패 증가 ({base_failures} ➔ {sample_failures})",
                    "; ".join(failure_details)
                )
            elif sample_failures > 0:
                res.warn(
                    f"샘플 요소/이미지 조회 실패 ({sample_failures}건, 기준선 {base_failures}건)",
                    "; ".join(failure_details)
                )
            else:
                res.pass_(f"통과 (포인트 수: {backend_count}건, 필터/상세/이미지 정상)")

        return res

    def run_check_b2_qdrant_data(self) -> CheckResult:
        """B2. Qdrant 데이터 스키마 및 BBox 정합성 검사"""
        res = CheckResult("B2", "Qdrant 데이터 검사")
        # Scroll로 전체 포인트 로드
        scroll_url = f"{self.qdrant_url}/collections/{self.collection}/points/scroll"
        data = {"limit": 1000, "with_payload": True, "with_vector": False}
        status, body, err = safe_http_request("POST", scroll_url, data=data, timeout=20.0)

        if status != 200 or not isinstance(body, dict):
            res.fail(f"Qdrant scroll 실패 (HTTP {status})", err)
            return res

        points = body.get("result", {}).get("points", [])
        total_points = len(points)
        doc_type_counts: Dict[str, int] = {}
        review_status_counts: Dict[str, int] = {}
        payload_key_counts: Dict[str, int] = {}
        extra_meta_keys: Set[str] = set()

        bbox_violations = []

        for p in points:
            payload = p.get("payload") or {}
            dt = payload.get("doc_type", "UNKNOWN")
            rs = payload.get("review_status", "UNKNOWN")
            doc_type_counts[dt] = doc_type_counts.get(dt, 0) + 1
            review_status_counts[rs] = review_status_counts.get(rs, 0) + 1

            for k, v in payload.items():
                if v is not None:
                    payload_key_counts[k] = payload_key_counts.get(k, 0) + 1

            extra = payload.get("extra_metadata")
            if isinstance(extra, dict):
                for ek in extra.keys():
                    extra_meta_keys.add(ek)

            # bbox 검사
            bbox = payload.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                bbox_violations.append(str(p.get("id")))
            else:
                try:
                    c = [float(x) for x in bbox]
                    if not (all(0.0 <= x <= 1.0 for x in c) and c[0] < c[2] and c[1] < c[3]):
                        bbox_violations.append(str(p.get("id")))
                except Exception:
                    bbox_violations.append(str(p.get("id")))

        res.metrics["total_points"] = total_points
        res.metrics["doc_type_counts"] = doc_type_counts
        res.metrics["review_status_counts"] = review_status_counts
        res.metrics["payload_key_counts"] = payload_key_counts
        res.metrics["extra_meta_keys"] = sorted(list(extra_meta_keys))
        res.metrics["bbox_violation_count"] = len(bbox_violations)
        res.metrics["bbox_violation_ids"] = bbox_violations[:10]

        # 기준선 비교
        base_b2 = (self.baseline or {}).get("B2", {})
        base_violations = base_b2.get("bbox_violation_count", 0)

        if len(bbox_violations) > base_violations:
            res.fail(
                f"BBox 유효성 위반 포인트가 증가했습니다 ({base_violations} ➔ {len(bbox_violations)})",
                f"위반 ID 샘플: {', '.join(bbox_violations[:5])}"
            )
        elif self.baseline is not None:
            # 주요 메트릭 변경 여부 확인
            changes = []
            if total_points != base_b2.get("total_points"):
                changes.append(f"총 포인트 ({base_b2.get('total_points')} ➔ {total_points})")
            if doc_type_counts != base_b2.get("doc_type_counts"):
                changes.append(f"문서 유형 분포 변경")
            if review_status_counts != base_b2.get("review_status_counts"):
                changes.append(f"검수 상태 분포 변경")

            if changes:
                res.changed("Qdrant 데이터 변동 감지", ", ".join(changes))
            else:
                res.pass_(f"통과 (포인트: {total_points}건, BBox 위반 0건)")
        else:
            res.pass_(f"기준선 없음: 포인트 {total_points}건 수집됨 (BBox 위반 {len(bbox_violations)}건)")

        return res

    def run_check_b3_frontend_types(self) -> CheckResult:
        """B3. 프론트엔드 TypeScript 정적 타입 검사"""
        res = CheckResult("B3", "프론트엔드 타입 검사")
        if self.no_docker:
            res.skip("Docker 실행 생략 옵션 (--no-docker)")
            return res

        compose_file = REPO_ROOT / "figindex" / "docker-compose.yml"
        cmd = [
            "docker", "compose", "-f", str(compose_file),
            "exec", "-T", "frontend", "npx", "tsc", "--noEmit"
        ]

        try:
            proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=60, encoding="utf-8")
            output = proc.stdout + "\n" + proc.stderr
        except subprocess.TimeoutExpired:
            res.fail("TypeScript 타입 검사 시간 초과 (60초)")
            return res
        except Exception as e:
            res.skip(f"타입 검사 실행 불가: {e}")
            return res

        if "no such container" in output or "is not running" in output or "failed to connect" in output:
            res.skip("프론트엔드 컨테이너가 가동 중이지 않음")
            return res

        # tsc 에러 개수 파싱 (error TSXXXX:)
        error_lines = [l for l in output.splitlines() if "error TS" in l]
        error_count = len(error_lines)
        res.metrics["ts_error_count"] = error_count

        base_errors = (self.baseline or {}).get("B3", {}).get("ts_error_count", 0)
        if error_count > base_errors:
            res.fail(f"TypeScript 타입 에러 증가 ({base_errors} ➔ {error_count})", "\n".join(error_lines[:5]))
        else:
            res.pass_(f"통과 (타입 에러: {error_count}건)")

        return res

    # =========================================================================
    # 오케스트레이션 및 리포팅
    # =========================================================================

    def run_all(self):
        """설정된 모드에 따라 검사를 수행합니다."""
        print("=" * 72)
        print(f" FigIndex 상태 검사기 (모드: {self.mode.upper()})")
        print("=" * 72)

        # A그룹 빠른 검사
        self.results.append(self.run_check_a1_git_scope())
        self.results.append(self.run_check_a2_forbidden_names())
        self.results.append(self.run_check_a3_status_literals())
        self.results.append(self.run_check_a4_threshold_literals())
        self.results.append(self.run_check_a5_import_rules())
        self.results.append(self.run_check_a6_model_duplicates())
        self.results.append(self.run_check_a7_syntax())
        self.results.append(self.run_check_a8_unit_tests())

        # B그룹 전체 검사
        if self.mode == "full":
            self.results.append(self.run_check_b1_api_health())
            self.results.append(self.run_check_b2_qdrant_data())
            self.results.append(self.run_check_b3_frontend_types())

        # 결과 요약 콘솔 출력
        has_fail = False
        for r in self.results:
            self.current_metrics[r.code] = r.metrics
            badge = f"[{r.status}]"
            print(f"{badge:<10} {r.code}. {r.title:<24} : {r.message}")
            if r.status == "FAIL":
                has_fail = True
                for d in r.details:
                    print(f"           - {d}")

        print("-" * 72)
        summary_counts = {
            "PASS": sum(1 for r in self.results if r.status == "PASS"),
            "WARN": sum(1 for r in self.results if r.status == "WARN"),
            "CHANGED": sum(1 for r in self.results if r.status == "CHANGED"),
            "FAIL": sum(1 for r in self.results if r.status == "FAIL"),
            "SKIP": sum(1 for r in self.results if r.status == "SKIP"),
        }
        print(
            f"검사 요약: PASS={summary_counts['PASS']}  WARN={summary_counts['WARN']}  "
            f"CHANGED={summary_counts['CHANGED']}  FAIL={summary_counts['FAIL']}  SKIP={summary_counts['SKIP']}"
        )
        print("=" * 72)

        # 리포트 파일 작성
        self.generate_report(has_fail)

        return 1 if has_fail else 0

    def generate_report(self, has_fail: bool):
        """결과 리포트(.check_reports/...) 마크다운 파일을 생성합니다."""
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.datetime.now()
        ts_str = now.strftime("%Y%m%d-%H%M")
        report_file = REPORTS_DIR / f"{ts_str}-{self.mode}.md"

        head_proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        head_commit = head_proc.stdout.strip() or "unknown"
        base_commit = (self.baseline or {}).get("meta", {}).get("commit", "none")

        lines = [
            f"# FigIndex 상태 검사 리포트 ({self.mode.upper()})",
            "",
            f"- **일시**: {now.strftime('%Y-%m-%d %H:%M:%S')}",
            f"- **실행 명령**: `python scripts/check_state.py --{self.mode}`",
            f"- **브랜치**: `{self.current_metrics.get('A1', {}).get('branch', 'unknown')}`",
            f"- **HEAD 커밋**: `{head_commit}`",
            f"- **기준선 커밋**: `{base_commit}`",
            f"- **검사 결과**: {'❌ FAIL 있음' if has_fail else '✅ 정상 통과'}",
        ]

        if self.allow_protected_files:
            lines.extend([
                "",
                "> [!WARNING]",
                "> **팀장 승인 수정 금지 파일 예외 허용 (`--allow-protected`):**",
                f"> `{', '.join(sorted(list(self.allow_protected_files)))}`",
            ])

        lines.extend([
            "",
            "## 1. 검사 항목 요약",
            "",
            "| 코드 | 항목 | 상태 | 요약 메시지 |",
            "| :--- | :--- | :---: | :--- |",
        ])

        for r in self.results:
            lines.append(f"| {r.code} | {r.title} | `{r.status}` | {r.message} |")

        lines.extend(["", "## 2. 상세 결과"])
        for r in self.results:
            lines.append(f"\n### {r.code}. {r.title} (`{r.status}`)")
            lines.append(f"- **메시지**: {r.message}")
            if r.details:
                lines.append("- **세부 내용**:")
                for d in r.details:
                    lines.append(f"  - `{d}`")

        with open(report_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def save_baseline(self):
        """--save-baseline 처리: 실패 검증 후 콘솔 yes 확인 시 저장"""
        if self.mode != "full":
            print("\n[FAIL] 기준선은 --full 검사에서만 저장할 수 있습니다. (현재 모드: quick)")
            print("힌트: python scripts/check_state.py --full --save-baseline 형식으로 실행하세요.")
            sys.exit(1)

        failed_items = [r for r in self.results if r.status == "FAIL"]
        if failed_items:
            print("\n[FAIL] 실패 항목이 있어 기준선을 저장할 수 없습니다. 문제를 먼저 해결하세요.")
            for r in failed_items:
                print(f"  - {r.code}. {r.title}: {r.message}")
            sys.exit(1)

        skipped_items = [r for r in self.results if r.status == "SKIP"]
        if skipped_items:
            print("\n[FAIL] 건너뛴(SKIP) 항목이 있어 기준선을 저장할 수 없습니다.")
            print("기준선을 저장하려면 Docker 및 모든 서비스가 정상 작동하여 모든 검사(A1~B4)가 통과되어야 합니다.")
            for r in skipped_items:
                print(f"  - {r.code}. {r.title}: {r.message}")
            sys.exit(1)

        print("\n" + "=" * 72)
        print(" 기준선(Baseline) 저장 확인")
        print("=" * 72)

        if self.baseline:
            print("기존 기준선과 현재 측정치 비교:")
            # 주요 차이 비교 출력
            b_strict = self.baseline.get("A2", {}).get("total_strict", 0)
            c_strict = self.current_metrics.get("A2", {}).get("total_strict", 0)
            print(f"- 엄격 금지 이름: {b_strict} ➔ {c_strict}")

            b_pts = self.baseline.get("B2", {}).get("total_points")
            c_pts = self.current_metrics.get("B2", {}).get("total_points")
            if c_pts is not None:
                print(f"- Qdrant 포인트 수: {b_pts} ➔ {c_pts}")
        else:
            print("현재 상태를 최초 기준선으로 새로 저장합니다.")

        head_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        head_commit = head_proc.stdout.strip() or "unknown"

        baseline_data = {
            "meta": {
                "created_at": datetime.datetime.now().isoformat(),
                "commit": head_commit,
                "mode": self.mode,
            }
        }
        baseline_data.update(self.current_metrics)

        try:
            val = input("\n기준선을 저장하시겠습니까? (yes 입력 시 저장): ").strip()
        except EOFError:
            print("[Info] 대화형 입력 불가(EOF). 저장이 취소되었습니다.")
            return

        if val.lower() == "yes":
            with open(BASELINE_PATH, "w", encoding="utf-8") as f:
                json.dump(baseline_data, f, ensure_ascii=False, indent=2)
            print(f"[Success] 기준선이 저장되었습니다: {BASELINE_PATH}")
        else:
            print("[Info] 저장이 취소되었습니다.")


def main():
    parser = argparse.ArgumentParser(description="FigIndex 상태 검사기")
    parser.add_argument("--quick", action="store_true", default=True, help="A그룹 빠른 검사 (기본값)")
    parser.add_argument("--full", action="store_true", help="A그룹 + B그룹 전체 검사")
    parser.add_argument("--expect", type=str, default=None, help="변경 허용 파일 목록 (콤마 구분)")
    parser.add_argument("--allow-protected", type=str, default=None, help="팀장 승인된 수정 금지 파일 목록 (콤마 구분, FAIL 대신 WARN 처리)")
    parser.add_argument("--base", type=str, default="HEAD", help="Git 비교 기준 (기본값 HEAD)")
    parser.add_argument("--no-docker", action="store_true", help="Docker 필요 검사 생략")
    parser.add_argument("--collection", type=str, default=None, help="Qdrant 컬렉션 이름 오버라이드")
    parser.add_argument("--save-baseline", action="store_true", help="현재 상태를 기준선으로 저장 (팀장 전용)")

    args = parser.parse_args()
    mode = "full" if args.full else "quick"

    # 안전장치: --allow-protected가 지정된 상태에서는 기준선 저장 절대 금지
    if args.save_baseline and args.allow_protected:
        print("\n[FAIL] --allow-protected 옵션이 지정된 상태에서는 기준선(--save-baseline)을 저장할 수 없습니다.")
        print("수정 금지 파일이 승인 수정된 상태에서는 먼저 변경 사항을 커밋하거나 되돌린 후 기준선을 저장해야 합니다.")
        sys.exit(1)

    checker = StateChecker(
        mode=mode,
        expect=args.expect,
        base=args.base,
        no_docker=args.no_docker,
        collection_override=args.collection,
        allow_protected=args.allow_protected,
    )

    exit_code = checker.run_all()

    if args.save_baseline:
        checker.save_baseline()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
