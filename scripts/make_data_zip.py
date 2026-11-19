#!/usr/bin/env python3
"""
scripts/make_data_zip.py

팀 배포용 데이터 zip을 만든다 (docs/onboarding.md 1-3절: 풀면 data/ 아래에 pdfs/, crops/, qdrant/).

- 넣는 것: figindex/data/pdfs, figindex/data/crops, figindex/data/qdrant
- 빼는 것: 시험 컬렉션(qdrant/collections/figindex_test_*), 그 밖의 data/ 파일
  (entity_dictionary.csv·gt는 Git 관리, metadata.sqlite3는 PC마다 register_existing_pdfs로 만듦, model_cache는 각자 받음)
- 파일명은 UTF-8로 기록한다 (한글 PDF 이름이 Windows 기본 압축에서 깨지는 문제 방지).
- Qdrant가 켜져 있으면 저장 중인 파일이 들어갈 수 있어 멈추고 안내한다. 먼저 `docker compose stop qdrant`.

사용법 (저장소 루트):
    python scripts/make_data_zip.py --out C:\\workAi\\figindex_work\\figindex_data_20261119.zip
"""
import argparse
import os
import sys
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "figindex/data"
INCLUDE_DIRS = ["pdfs", "crops", "qdrant"]
TEST_COLLECTION_PREFIX = "figindex_test_"


def qdrant_is_running(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2):
            return True
    except Exception:
        return False


def is_excluded(rel: Path) -> bool:
    parts = rel.parts
    # qdrant/collections/<이름>/...
    return (len(parts) >= 3 and parts[0] == "qdrant" and parts[1] == "collections"
            and parts[2].startswith(TEST_COLLECTION_PREFIX))


def collect_files(data_dir: Path):
    files, excluded = [], Counter()
    for top in INCLUDE_DIRS:
        base = data_dir / top
        if not base.is_dir():
            sys.exit(f"{base} 폴더가 없습니다.")
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(data_dir)
            if is_excluded(rel):
                excluded[rel.parts[2]] += 1
                continue
            files.append((path, rel))
    return files, excluded


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="팀 배포용 데이터 zip 만들기")
    ap.add_argument("--out", required=True, help="만들 zip 경로 (저장소 밖 권장)")
    ap.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"))
    ap.add_argument("--force", action="store_true", help="Qdrant가 켜져 있어도 진행 (권장하지 않음)")
    args = ap.parse_args()

    if qdrant_is_running(args.qdrant_url) and not args.force:
        sys.exit("Qdrant가 켜져 있습니다. figindex 폴더에서 'docker compose stop qdrant' 후 다시 실행해 주세요.")

    out = Path(args.out)
    if out.resolve().is_relative_to(REPO_ROOT.resolve()):
        sys.exit("zip은 저장소 밖에 만들어 주세요 (git pull 충돌 방지, 현황서 함정 8).")

    files, excluded = collect_files(DATA_DIR)
    counts = Counter(rel.parts[0] for _, rel in files)
    collections = sorted({rel.parts[2] for _, rel in files
                          if len(rel.parts) >= 3 and rel.parts[:2] == ("qdrant", "collections")})
    pdf_count = sum(1 for _, rel in files if rel.parts[0] == "pdfs" and rel.suffix.lower() == ".pdf")

    out.parent.mkdir(parents=True, exist_ok=True)
    total = len(files)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as zf:
        for i, (path, rel) in enumerate(files, 1):
            zf.write(path, rel.as_posix())
            if i % 2000 == 0 or i == total:
                print(f"  {i}/{total}개 압축", flush=True)

    with zipfile.ZipFile(out) as zf:
        bad = zf.testzip()
    size_mb = out.stat().st_size / 1024 / 1024
    print(f"\n완료: {out} ({size_mb:,.0f}MB)")
    print(f"  파일 수: pdfs {counts['pdfs']}, crops {counts['crops']}, qdrant {counts['qdrant']} (PDF {pdf_count}개)")
    print(f"  Qdrant 컬렉션: {', '.join(collections)}")
    if excluded:
        print(f"  뺀 시험 컬렉션: {', '.join(f'{k}({v}개 파일)' for k, v in sorted(excluded.items()))}")
    print(f"  무결성 검사: {'통과' if bad is None else '실패 ' + bad}")


if __name__ == "__main__":
    main()
