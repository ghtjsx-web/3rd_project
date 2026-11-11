"""
/data/pdfs 바로 아래 모든 PDF 파일에 대해 parse_filename() 결과를 표로 출력하는 테스트 스크립트
(Gemini·Qdrant 호출 없이 동작)

실행 방법:
  docker compose run --rm pipeline python test_parse_filename.py
"""

import os
from pathlib import Path
from orchestrator import parse_filename


SAMPLE_FILENAMES = [
    "보고서20251231해상풍력보급확대를위한지자체역할_에너지경제연구원.pdf",
    "리포트202605122026년세계경제전망_대외경제정책연구원.pdf",
    "논문2025020112차베이비붐세대의소득및자산특_한국보건사회연구원.pdf",
]


def print_table(title: str, filenames: list[str]):
    parsed_rows = []
    unparsed_files = []

    for fname in filenames:
        res = parse_filename(fname)
        if res:
            parsed_rows.append((fname, res))
        else:
            unparsed_files.append(fname)

    print(f"\n[{title}] 총 {len(filenames)}개 (성공: {len(parsed_rows)}개 / 미매칭: {len(unparsed_files)}개)\n")
    print(f"{'파일명':<50} | {'doc_type':<13} | {'날짜':<10} | {'대상':<28} | {'출처'}")
    print("-" * 125)

    for fname, res in parsed_rows:
        print(
            f"{fname:<50} | {res['doc_type']:<13} | {res['date'].isoformat():<10} | "
            f"{res['target']:<28} | {res['source']}"
        )

    if unparsed_files:
        print("\n" + "=" * 60)
        print(f"[규칙 미매칭(기존 방식 fallback 대상) 파일 목록: {len(unparsed_files)}개]")
        print("=" * 60)
        for fname in unparsed_files:
            print(f"  - {fname}")


def main():
    print_table("형식 C 예시 검증", SAMPLE_FILENAMES)

    pdfs_dir = Path(os.getenv("PDFS_DIR", "/data/pdfs"))
    if not pdfs_dir.exists():
        print(f"\n[안내] {pdfs_dir} 폴더가 없어 실제 PDF 목록 검사는 건너뜁니다.")
        return

    pdf_files = sorted([p.name for p in pdfs_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"])
    if not pdf_files:
        print(f"\n[안내] {pdfs_dir} 바로 아래에 PDF 파일이 없습니다.")
        return

    print_table(f"{pdfs_dir} 전체 PDF 검사", pdf_files)


if __name__ == "__main__":
    main()
