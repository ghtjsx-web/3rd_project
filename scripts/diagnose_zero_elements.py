#!/usr/bin/env python3
"""
scripts/diagnose_zero_elements.py

도표가 0개로 끝난 문서가 '원래 도표가 없는 문서'인지 '도표 찾기 규칙이 놓친 문서'인지 페이지별로 본다. 읽기 전용.

페이지마다 보는 것
- has_text_layer: 글자 층이 있는지 (없으면 스캔본이라 캡션 규칙이 동작하지 않음)
- 표 탐지(raw): PyMuPDF find_tables가 찾은 표 수 (크기·위치 거르기 전)
- 후보: cropper.detect_candidate_boxes가 최종으로 낸 후보 수 (파이프라인이 실제로 쓰는 값)
- 그림·선: 페이지에 들어 있는 이미지 수와 벡터 그림(선·도형) 수
- 캡션 같은 줄: 그림·표 캡션처럼 보이는 줄 (넓은 규칙). 후보가 0인데 이 줄이 있으면 규칙이 놓친 것

사용법 (figindex 폴더, pipeline 컨테이너에서):
    docker compose --profile index run --rm pipeline python /scripts/diagnose_zero_elements.py 드론자력탐사 OECD한국경제보고서
인자는 /data/pdfs 안 파일 이름의 일부(여러 개 가능)
"""
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (REPO_ROOT / "figindex", REPO_ROOT / "figindex" / "pipeline", Path("/app")):
    sys.path.insert(0, str(p))

import fitz  # noqa: E402
from cropper import PDFCropper  # noqa: E402
from pdf_text import has_text_layer, read_text_in_bbox  # noqa: E402

# 파이프라인 규칙(cropper.py)보다 넓게 잡는다: Fig. 1, <그림 1>, [표 2-1], Table 3 등
WIDE_CAPTION = re.compile(
    r"^\s*[<\[〈(]?\s*(그림|도표|표|Fig\.?|Figure|Table|Chart|Exhibit)\s*\d+([\-\.]\d+)?",
    re.IGNORECASE,
)


def diagnose(pdf_path: Path, cropper: PDFCropper) -> None:
    print("=" * 72)
    print(f"{pdf_path.name}")
    doc = fitz.open(pdf_path)
    total_candidates = 0
    total_captions = 0
    for page_number in range(1, doc.page_count + 1):
        page = doc[page_number - 1]
        page_has_text_layer = has_text_layer(page)
        try:
            raw_tables = len(page.find_tables().tables)
        except Exception:
            raw_tables = -1
        candidates = cropper.detect_candidate_boxes(page)
        images = len(page.get_images(full=True))
        drawings = len(page.get_drawings())
        captions = []
        if page_has_text_layer:
            for line in read_text_in_bbox(page, [0.0, 0.0, 1.0, 1.0]).splitlines():
                if WIDE_CAPTION.match(line):
                    captions.append(line.strip()[:60])
        total_candidates += len(candidates)
        total_captions += len(captions)
        print(
            f"  P.{page_number:>3} 글자층={'O' if page_has_text_layer else 'X'} 표탐지(raw)={raw_tables} "
            f"후보={len(candidates)} 이미지={images} 선·도형={drawings} 캡션같은줄={len(captions)}"
        )
        for line in captions:
            print(f"         - {line}")
    doc.close()
    print(f"  합계: 후보 {total_candidates}개, 캡션 같은 줄 {total_captions}개")
    if total_candidates == 0 and total_captions > 0:
        print("  판단: 캡션은 있는데 후보가 없음 → 도표 찾기 규칙이 놓친 문서")
    elif total_candidates == 0:
        print("  판단: 캡션 같은 줄도 없음 → 이미지·선 수를 보고 실제 도표가 있는지 원문 확인")


def main() -> None:
    keywords = sys.argv[1:]
    if not keywords:
        sys.exit("파일 이름의 일부를 하나 이상 주십시오. 예: 드론자력탐사 OECD한국경제보고서")
    pdfs_dir = Path(os.getenv("PDFS_DIR", "/data/pdfs"))
    cropper = PDFCropper(crops_dir=Path("/tmp/diagnose_crops"))  # 후보만 보고 잘라 저장하지 않음
    for keyword in keywords:
        matches = sorted(p for p in pdfs_dir.glob("*.pdf") if keyword in p.name)
        if not matches:
            print(f"[없음] '{keyword}'가 들어간 PDF가 {pdfs_dir}에 없습니다.")
        for pdf_path in matches:
            diagnose(pdf_path, cropper)


if __name__ == "__main__":
    main()
