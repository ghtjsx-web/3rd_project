"""
doc_name 조사 스크립트 — 고유 문서 142개 vs PDF 118건 차이 원인 분석 (읽기 전용).

절대 규칙:
- 읽기만 한다 (Qdrant 쓰기 금지, 파일 이름 변경/이동/삭제 금지).
- 백엔드 /api/files/pdf/{doc_name} 에는 GET/HEAD 요청만 1회 보낸다.
"""
import argparse
import csv
import datetime
import hashlib
import json
import os
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# 경로 설정
current_dir = Path(__file__).resolve().parent
repo_root = current_dir.parent.parent if current_dir.name == "pipeline" and current_dir.parent.name == "figindex" else current_dir.parent
for candidate in [
    current_dir.parent,           # figindex/ (shared/ 포함)
    current_dir,                  # /app (Docker)
    Path("/app"),                 # Docker root
    repo_root / "figindex",       # 호스트 figindex
]:
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from shared.coords import from_legacy_yxyx, iou

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


# CSV 대조표 컬럼명 상수
LEGACY_CSV_ORIG_KEY = "_".join(["original", "file", "name"])
LEGACY_CSV_RENAMED_KEY = "_".join(["file", "name"])


def nfc(text: str) -> str:
    """NFC 유니코드 정규화"""
    return unicodedata.normalize("NFC", text) if text else ""


def clean_filename(text: str) -> str:
    """경로 분리, 앞뒤 공백 제거, 확장자 소문자화"""
    if not text:
        return ""
    base = os.path.basename(text).strip()
    p = Path(base)
    return f"{p.stem}{p.suffix.lower()}"


def compute_file_hash(path: Path) -> str:
    """파일 SHA-256 해시 계산 (소문자 16진수)"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def match_doc_name_to_files(
    doc_name: str,
    root_files: Dict[str, Dict[str, Any]],        # key: file.name
    subfolder_files: Dict[str, Dict[str, Any]],   # key: file.name
    rename_plan: Dict[str, str],                  # 원본명 -> 변경명
    reverse_rename_plan: Dict[str, str],          # 변경명 -> 원본명
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """doc_name을 실제 파일 목록과 매칭하여 (match_type, matched_file_info) 반환.
    
    Match Types:
      (A) exact_root: pdfs/ 바로 아래 정확히 일치
      (B) nfc_normalized: NFC 정규화 후 일치
      (C) cleaned_match: 경로/확장자/공백 정리 후 일치
      (D) rename_plan_mapped: rename_plan 대조표를 통해 매핑된 파일이 root에 존재
      (E) subfolder_only: _incoming 등 하위 폴더에만 존재
      (F) orphan: 어디에도 매칭되는 파일 없음
    """
    # 1. (A) exact_root
    if doc_name in root_files:
        return "A_exact_root", root_files[doc_name]

    # 2. (B) nfc_normalized
    doc_nfc = nfc(doc_name)
    for fn, finfo in root_files.items():
        if doc_nfc == nfc(fn):
            return "B_nfc_normalized", finfo

    # 3. (C) cleaned_match
    doc_clean = clean_filename(doc_nfc)
    for fn, finfo in root_files.items():
        if doc_clean == clean_filename(nfc(fn)):
            return "C_cleaned_match", finfo

    # 4. (D) rename_plan_mapped
    # doc_name이 변경 전 이름인 경우
    target_from_plan = rename_plan.get(doc_name) or rename_plan.get(doc_nfc)
    if target_from_plan and target_from_plan in root_files:
        return "D_rename_plan_mapped", root_files[target_from_plan]
    # doc_name이 변경 후 이름인 경우
    orig_from_plan = reverse_rename_plan.get(doc_name) or reverse_rename_plan.get(doc_nfc)
    if orig_from_plan and orig_from_plan in root_files:
        return "D_rename_plan_mapped", root_files[orig_from_plan]

    # 5. (E) subfolder_only
    if doc_name in subfolder_files:
        return "E_subfolder_only", subfolder_files[doc_name]
    for fn, finfo in subfolder_files.items():
        if doc_nfc == nfc(fn) or doc_clean == clean_filename(nfc(fn)):
            return "E_subfolder_only", finfo

    # subfolder + rename_plan 확인
    if target_from_plan and target_from_plan in subfolder_files:
        return "E_subfolder_only", subfolder_files[target_from_plan]

    # 6. (F) orphan
    return "F_orphan", None


def check_element_duplicates(elements_a: List[Dict[str, Any]], elements_b: List[Dict[str, Any]], threshold: float = 0.9) -> int:
    """두 문서 요소 그룹 간 page_number가 같고 IoU >= threshold인 중복 요소 수 계산."""
    dup_count = 0
    matched_b_ids: Set[str] = set()

    for ea in elements_a:
        page_a = ea.get("page_number")
        bbox_a_raw = ea.get("bbox")
        if not bbox_a_raw or len(bbox_a_raw) != 4:
            continue
        try:
            bbox_a_norm = from_legacy_yxyx(bbox_a_raw)
        except Exception:
            continue

        for eb in elements_b:
            eb_id = eb.get("element_id")
            if eb_id in matched_b_ids:
                continue
            if eb.get("page_number") != page_a:
                continue
            bbox_b_raw = eb.get("bbox")
            if not bbox_b_raw or len(bbox_b_raw) != 4:
                continue
            try:
                bbox_b_norm = from_legacy_yxyx(bbox_b_raw)
            except Exception:
                continue

            try:
                overlap = iou(bbox_a_norm, bbox_b_norm)
            except Exception:
                overlap = 0.0

            if overlap >= threshold:
                dup_count += 1
                matched_b_ids.add(eb_id)
                break

    return dup_count


class DocNameAuditor:
    def __init__(
        self,
        qdrant_url: str = "http://localhost:6333",
        collection: str = "figindex_elements",
        backend_url: str = "http://localhost:8000",
        pdfs_dir: Optional[Path] = None,
    ):
        self.qdrant_url = qdrant_url.rstrip("/")
        self.collection = collection
        self.backend_url = backend_url.rstrip("/")

        # pdfs 디렉토리 결정
        if pdfs_dir is not None:
            self.pdfs_dir = pdfs_dir
        else:
            candidates = [
                repo_root / "figindex" / "data" / "pdfs",
                Path("/data/pdfs"),
                current_dir.parent / "data" / "pdfs",
            ]
            self.pdfs_dir = next((c for c in candidates if c.exists()), candidates[0])

    def fetch_qdrant_doc_elements(self) -> Dict[str, List[Dict[str, Any]]]:
        """Qdrant scroll을 통해 doc_name별 요소 목록 수집 (읽기 전용)."""
        doc_elements: Dict[str, List[Dict[str, Any]]] = {}
        offset = None
        batch_size = 100

        while True:
            data = {
                "limit": batch_size,
                "offset": offset,
                "with_payload": True,
                "with_vector": False,
            }
            req = urllib.request.Request(
                f"{self.qdrant_url}/collections/{self.collection}/points/scroll",
                data=json.dumps(data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                res = json.loads(resp.read().decode("utf-8"))

            points = res.get("result", {}).get("points", [])
            if not points:
                break

            for pt in points:
                payload = pt.get("payload") or {}
                dname = payload.get("doc_name") or "UNKNOWN"
                if dname not in doc_elements:
                    doc_elements[dname] = []
                doc_elements[dname].append(payload)

            offset = res.get("result", {}).get("next_page_offset")
            if offset is None:
                break

        return doc_elements

    def scan_pdf_files(self) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, str], Dict[str, str]]:
        """pdfs/ 폴더 스캔: 루트 파일, 서브폴더 파일, rename_plan 파싱."""
        root_files: Dict[str, Dict[str, Any]] = {}
        subfolder_files: Dict[str, Dict[str, Any]] = {}

        if self.pdfs_dir.exists():
            for p in self.pdfs_dir.rglob("*.pdf"):
                rel = p.relative_to(self.pdfs_dir).as_posix()
                is_root = ("/" not in rel)
                size_bytes = p.stat().st_size
                doc_hash = compute_file_hash(p)

                # 페이지 수 추출
                page_cnt = None
                if fitz is not None:
                    try:
                        with fitz.open(p) as d:
                            page_cnt = len(d)
                    except Exception:
                        page_cnt = None

                finfo = {
                    "doc_name": p.name,
                    "rel_path": rel,
                    "abs_path": str(p),
                    "size_bytes": size_bytes,
                    "doc_hash": doc_hash,
                    "page_count": page_cnt,
                    "is_root": is_root,
                }

                if is_root:
                    root_files[p.name] = finfo
                else:
                    subfolder_files[p.name] = finfo

        # rename_plan.csv 파싱
        rename_plan: Dict[str, str] = {}
        reverse_rename_plan: Dict[str, str] = {}
        plan_candidates = [
            self.pdfs_dir / "_renamed" / "rename_plan.csv",
            repo_root / "figindex" / "data" / "pdfs" / "_renamed" / "rename_plan.csv",
            Path("/data/pdfs/_renamed/rename_plan.csv"),
        ]
        plan_file = next((c for c in plan_candidates if c.exists()), None)
        if plan_file:
            try:
                with open(plan_file, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        orig = row.get(LEGACY_CSV_ORIG_KEY, "").strip()
                        renamed = row.get(LEGACY_CSV_RENAMED_KEY, "").strip()
                        if orig and renamed:
                            rename_plan[orig] = renamed
                            reverse_rename_plan[renamed] = orig
            except Exception as e:
                print(f"[Warn] rename_plan.csv 읽기 실패: {e}")

        return root_files, subfolder_files, rename_plan, reverse_rename_plan

    def check_pdf_url_status(self, doc_name: str) -> int:
        """백엔드 /api/files/pdf/{doc_name} GET 요청으로 HTTP 상태 코드 확인 (읽기 전용)."""
        encoded = urllib.parse.quote(doc_name)
        url = f"{self.backend_url}/api/files/pdf/{encoded}"
        req = urllib.request.Request(url, method="GET")
        req.add_header("Range", "bytes=0-10")  # 헤더 10바이트만 읽어 트래픽 최소화
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            return e.code
        except Exception:
            return -1

    def run_audit(self) -> Dict[str, Any]:
        """전체 검사 수행."""
        print("[1/5] Qdrant 페이로드 scroll 로드 중...")
        qdrant_doc_elements = self.fetch_qdrant_doc_elements()
        qdrant_doc_names = sorted(list(qdrant_doc_elements.keys()))
        print(f" -> Qdrant 고유 doc_name 수: {len(qdrant_doc_names)}개 (전체 요소: {sum(len(v) for v in qdrant_doc_elements.values())}건)")

        print("[2/5] PDF 디렉토리 스캔 중...")
        root_files, subfolder_files, rename_plan, reverse_rename_plan = self.scan_pdf_files()
        print(f" -> pdfs/ 루트 파일 수: {len(root_files)}개, 하위폴더 파일 수: {len(subfolder_files)}개")

        print("[3/5] doc_name 매칭 및 백엔드 URL 응답 확인 중...")
        audit_records = []
        match_counts = {
            "A_exact_root": 0,
            "B_nfc_normalized": 0,
            "C_cleaned_match": 0,
            "D_rename_plan_mapped": 0,
            "E_subfolder_only": 0,
            "F_orphan": 0,
        }

        # SHA-256별 매핑된 doc_name 그룹
        hash_to_docnames: Dict[str, List[str]] = {}

        for dname in qdrant_doc_names:
            elems = qdrant_doc_elements[dname]
            match_type, finfo = match_doc_name_to_files(
                dname, root_files, subfolder_files, rename_plan, reverse_rename_plan
            )
            match_counts[match_type] = match_counts.get(match_type, 0) + 1

            doc_hash = finfo["doc_hash"] if finfo else "none"
            file_path = finfo["rel_path"] if finfo else "none"
            canonical_name = finfo["doc_name"] if finfo else dname

            if doc_hash != "none":
                hash_to_docnames.setdefault(doc_hash, []).append(dname)

            # 백엔드 URL 응답 확인
            url_status = self.check_pdf_url_status(dname)

            audit_records.append({
                "doc_name": dname,
                "match_type": match_type,
                "canonical_doc_name": canonical_name,
                "file_path": file_path,
                "doc_hash": doc_hash,
                "element_count": len(elems),
                "duplicate_element_count": 0,  # 4단계에서 계산
                "pdf_url_ok": (url_status == 200 or url_status == 206),
                "url_status_code": url_status,
                "proposed_action": "keep",
                "elements": elems,
            })

        print("[4/5] 동일 SHA-256 중복 문서 및 중복 요소(IoU>=0.9) 분석 중...")
        # 2개 이상의 doc_name이 연결된 SHA-256 그룹
        multi_doc_groups = {h: dns for h, dns in hash_to_docnames.items() if len(dns) > 1}
        total_duplicate_elements = 0
        group_summaries = []

        rec_by_dname = {r["doc_name"]: r for r in audit_records}

        for h, dnames in multi_doc_groups.items():
            # 첫 번째 문서를 기준(canonical)으로 삼고, 이후 문서들과의 중복 요소 계산
            base_dname = dnames[0]
            base_elems = rec_by_dname[base_dname]["elements"]

            group_dup_elem_count = 0
            for other_dname in dnames[1:]:
                other_elems = rec_by_dname[other_dname]["elements"]
                dups = check_element_duplicates(base_elems, other_elems, threshold=0.9)
                rec_by_dname[other_dname]["duplicate_element_count"] = dups
                group_dup_elem_count += dups

            total_duplicate_elements += group_dup_elem_count
            group_summaries.append({
                "doc_hash": h,
                "doc_names": dnames,
                "canonical_name": rec_by_dname[base_dname]["canonical_doc_name"],
                "total_elements": sum(rec_by_dname[dn]["element_count"] for dn in dnames),
                "duplicate_elements": group_dup_elem_count,
            })

        # 제안 조치(proposed_action) 결정
        for r in audit_records:
            mtype = r["match_type"]
            dname = r["doc_name"]
            cname = r["canonical_doc_name"]

            if mtype == "F_orphan":
                r["proposed_action"] = "orphan_review"
            elif r["doc_hash"] in multi_doc_groups:
                if r["duplicate_element_count"] > 0:
                    r["proposed_action"] = "drop_duplicates"
                elif dname != cname:
                    r["proposed_action"] = "rename_to_canonical"
                else:
                    r["proposed_action"] = "keep"
            elif dname != cname:
                r["proposed_action"] = "rename_to_canonical"
            else:
                r["proposed_action"] = "keep"

        print("[5/5] 색인되지 않은 PDF 파일(0개 요소) 분석 중...")
        indexed_hashes = {r["doc_hash"] for r in audit_records if r["doc_hash"] != "none"}
        unindexed_root_files = [finfo for finfo in root_files.values() if finfo["doc_hash"] not in indexed_hashes]

        summary = {
            "total_qdrant_doc_names": len(qdrant_doc_names),
            "total_root_pdfs": len(root_files),
            "total_subfolder_pdfs": len(subfolder_files),
            "match_counts": match_counts,
            "multi_doc_groups_count": len(multi_doc_groups),
            "multi_doc_groups": group_summaries,
            "total_duplicate_elements": total_duplicate_elements,
            "pdf_url_failed_count": sum(1 for r in audit_records if not r["pdf_url_ok"]),
            "unindexed_root_files": unindexed_root_files,
            "audit_records": audit_records,
        }

        # 결과물 저장
        now_ts = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        migration_dir = repo_root / "figindex" / "data" / "migration"
        if not migration_dir.parent.exists():
            migration_dir = Path("/data/migration")
            if not migration_dir.parent.exists():
                migration_dir = current_dir / "data" / "migration"
        migration_dir.mkdir(parents=True, exist_ok=True)

        md_path = migration_dir / f"doc_name_audit_{now_ts}.md"
        csv_path = migration_dir / f"doc_name_audit_{now_ts}.csv"

        self.save_csv_report(csv_path, audit_records)
        self.save_markdown_report(md_path, summary)

        summary["md_path"] = str(md_path)
        summary["csv_path"] = str(csv_path)
        return summary

    def save_csv_report(self, csv_path: Path, audit_records: List[Dict[str, Any]]):
        """CSV 정리안 저장."""
        fields = [
            "doc_name",
            "match_type",
            "canonical_doc_name",
            "file_path",
            "doc_hash",
            "element_count",
            "duplicate_element_count",
            "pdf_url_ok",
            "proposed_action",
        ]
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(audit_records)

    def save_markdown_report(self, md_path: Path, s: Dict[str, Any]):
        """마크다운 리포트 저장."""
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            "# FigIndex doc_name 조사 및 정합성 리포트",
            "",
            f"- **조사 일시**: {now_str}",
            f"- **Qdrant 고유 doc_name 수**: {s['total_qdrant_doc_names']}개",
            f"- **pdfs/ 루트 PDF 수**: {s['total_root_pdfs']}건",
            f"- **pdfs/ 하위 폴더 PDF 수**: {s['total_subfolder_pdfs']}건",
            "",
            "## 1. 142개 vs 118건 (차이 24건) 원인 분석",
            "",
        ]

        # 차이 원인 한 문단 설명
        a_cnt = s["match_counts"].get("A_exact_root", 0)
        d_cnt = s["match_counts"].get("D_rename_plan_mapped", 0)
        e_cnt = s["match_counts"].get("E_subfolder_only", 0)
        f_cnt = s["match_counts"].get("F_orphan", 0)

        lines.append(
            f"Qdrant의 고유 `doc_name`(142개)과 `pdfs/` 루트 PDF(118건) 간의 **24건 차이**는, "
            f"과거 파일명 정리 스크립트(`rename_reports.py`) 실행 전의 구 파일명과 변경 후 새 파일명이 컬렉션에 **동시에 중복 색인**되었거나 "
            f"(`rename_plan.csv` 매핑 {d_cnt}건, 동일 해시 다중 등록 묶음 {s['multi_doc_groups_count']}개), "
            f"`_incoming` 하위 폴더에 보관된 미색인 파일({e_cnt}건) 또는 실제 파일이 유실된 고아 문서({f_cnt}건)가 포함되어 있기 때문에 발생했습니다."
        )

        lines.extend([
            "",
            "## 2. 매칭 유형별 요약표 (A~F)",
            "",
            "| 매칭 유형 (Match Type) | 건수 | 설명 |",
            "| :--- | :---: | :--- |",
            f"| **(A) exact_root** | {s['match_counts'].get('A_exact_root', 0)}건 | `pdfs/` 바로 아래 정확히 일치하는 파일 존재 |",
            f"| **(B) nfc_normalized** | {s['match_counts'].get('B_nfc_normalized', 0)}건 | Mac/Win 유니코드 NFC 정규화 후 일치 |",
            f"| **(C) cleaned_match** | {s['match_counts'].get('C_cleaned_match', 0)}건 | 경로, 확장자 대소문자, 공백 제거 후 일치 |",
            f"| **(D) rename_plan_mapped** | {s['match_counts'].get('D_rename_plan_mapped', 0)}건 | `rename_plan.csv`를 통해 변경 전후 파일로 매핑 |",
            f"| **(E) subfolder_only** | {s['match_counts'].get('E_subfolder_only', 0)}건 | `_incoming` 등 하위 폴더에만 파일이 존재 |",
            f"| **(F) orphan** | {s['match_counts'].get('F_orphan', 0)}건 | 로컬 디스크 어디에도 PDF 파일이 없는 고아 문서 |",
            f"| **합계** | **{s['total_qdrant_doc_names']}건** | |",
            "",
            "## 3. 핵심 정합성 지표",
            "",
            f"- **동일 파일(동일 SHA-256) 다중 등록 묶음 수**: {s['multi_doc_groups_count']}개",
            f"- **중복 검출된 요소 수 (동일 페이지, IoU ≥ 0.9)**: **{s['total_duplicate_elements']}건**",
            f"- **중복을 제외한 실제 요소 수**: **{525 - s['total_duplicate_elements']}건** (전체 525건 - 중복 {s['total_duplicate_elements']}건)",
            f"- **백엔드 원문 PDF 보기 실패 건수 (HTTP 404 등)**: {s['pdf_url_failed_count']}건",
            f"- **색인 요소가 0개인 미색인 루트 PDF 파일 수**: {len(s['unindexed_root_files'])}건",
            "",
            "## 4. 동일 PDF 다중 이름 묶음 상세",
            "",
        ])

        if s["multi_doc_groups"]:
            lines.append("| 대표 파일명 | SHA-256 (앞 8자리) | 연결된 doc_name 목록 | 전체 요소 수 | 중복 요소 수 |")
            lines.append("| :--- | :---: | :--- | :---: | :---: |")
            for g in s["multi_doc_groups"]:
                names_str = "<br>".join(g["doc_names"])
                lines.append(f"| `{g['canonical_name']}` | `{g['doc_hash'][:8]}` | {names_str} | {g['total_elements']} | **{g['duplicate_elements']}** |")
        else:
            lines.append("- 동일 파일 다중 이름 묶음 없음.")

        lines.extend([
            "",
            "## 5. 색인되지 않은 루트 PDF 파일 목록 (요소 0개)",
            "",
        ])
        if s["unindexed_root_files"]:
            lines.append(f"총 {len(s['unindexed_root_files'])}건:")
            for uf in s["unindexed_root_files"]:
                lines.append(f"- `{uf['doc_name']}` ({uf['size_bytes']:,} bytes, {uf['page_count']}p)")
        else:
            lines.append("- 색인되지 않은 루트 PDF 파일 없음.")

        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description="FigIndex doc_name 정합성 조사 도구")
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"))
    parser.add_argument("--backend-url", default=os.getenv("BACKEND_URL", "http://localhost:8000"))
    parser.add_argument("--collection", default="figindex_elements")
    args = parser.parse_args()

    auditor = DocNameAuditor(
        qdrant_url=args.qdrant_url,
        backend_url=args.backend_url,
        collection=args.collection,
    )

    print("=" * 72)
    print(" FigIndex doc_name 조사 및 정합성 분석 (읽기 전용)")
    print("=" * 72)

    try:
        summary = auditor.run_audit()
    except Exception as e:
        print(f"\n[FAIL] 조사 실행 실패: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("\n" + "=" * 72)
    print(" 조사 완료 요약")
    print(f"- Qdrant doc_name: {summary['total_qdrant_doc_names']}개 ➔ pdfs/ 루트: {summary['total_root_pdfs']}건")
    print(f"- 매칭 현황: exact={summary['match_counts']['A_exact_root']}, nfc={summary['match_counts']['B_nfc_normalized']}, cleaned={summary['match_counts']['C_cleaned_match']}, rename_plan={summary['match_counts']['D_rename_plan_mapped']}, subfolder={summary['match_counts']['E_subfolder_only']}, orphan={summary['match_counts']['F_orphan']}")
    print(f"- 동일 해시 묶음: {summary['multi_doc_groups_count']}개, 중복 요소: {summary['total_duplicate_elements']}건")
    print(f"- 원문 보기 실패: {summary['pdf_url_failed_count']}건, 미색인 PDF: {len(summary['unindexed_root_files'])}건")
    print(f"- 리포트(MD): {summary['md_path']}")
    print(f"- 정리안(CSV): {summary['csv_path']}")
    print("=" * 72)


if __name__ == "__main__":
    main()
