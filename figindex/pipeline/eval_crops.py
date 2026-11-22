"""
탐지 정답셋으로 지금 방식(cropper.py 규칙)과 YOLO의 crop_recall을 계산한다 (팀원4 5단계, 결정 30).

- 정답: figindex/data/gt/detection/*.json 중 "reviewed": true 인 파일만 (사람이 확인을 끝낸 것)
- 예측: 두 방식 모두 cropper.crop_and_save와 같은 패딩을 붙인 실제 크롭 영역으로 비교한다
- crop_recall = 정답 요소 중 IoU ≥ 0.5인 예측이 있는 수 ÷ 정답 요소 수 (용어집 12절)
- 결정 30의 ① '10페이지 크롭 15초 이내'를 보도록 페이지당 탐지 시간도 함께 낸다 (Gemini 시간 제외)

실행 (figindex 폴더)
    docker compose --profile index run --rm pipeline python eval_crops.py
    docker compose --profile index run --rm pipeline python eval_crops.py --include-unreviewed   # 초안 상태로 미리 보기
결과: 화면 요약 + /data/gt/detection/_eval/crop_eval.json (페이지별 놓친 정답 포함)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import fitz  # PyMuPDF

from cropper import PDFCropper
from detection_gt import load_gt_files, matched_gt_count, padded_like_cropper
from make_detection_drafts import find_pdf, load_yolo, rule_elements, yolo_elements


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="지금 방식 vs YOLO crop_recall")
    parser.add_argument("--gt-dir", default="/data/gt/detection")
    parser.add_argument("--pdfs-dir", default="/data/pdfs")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--include-unreviewed", action="store_true", help="reviewed=false 초안도 포함 (참고용)")
    args = parser.parse_args()

    gt_dir, pdfs_dir = Path(args.gt_dir), Path(args.pdfs_dir)
    gt_files = load_gt_files(gt_dir, include_unreviewed=args.include_unreviewed)
    if not gt_files:
        raise SystemExit(f"확인을 끝낸(reviewed=true) 정답 파일이 없습니다: {gt_dir}")

    cropper = PDFCropper()
    model = load_yolo()
    methods = ("rule", "yolo")
    hits = {m: 0 for m in methods}
    seconds = {m: 0.0 for m in methods}
    total_gt = 0
    pages: List[Dict[str, Any]] = []

    for gt in gt_files:
        gt_boxes = [e["bbox"] for e in gt.get("elements", [])]
        with fitz.open(str(find_pdf(pdfs_dir, gt["doc_name"]))) as doc:
            page = doc[gt["page_number"] - 1]
            width_pt, height_pt = page.rect.width, page.rect.height

            t0 = time.perf_counter()
            rule = rule_elements(cropper, page)
            seconds["rule"] += time.perf_counter() - t0

            t0 = time.perf_counter()
            page_img = cropper.render_page(doc, gt["page_number"])
            yolo = yolo_elements(model, page_img, args.conf)
            seconds["yolo"] += time.perf_counter() - t0

        preds = {
            "rule": [padded_like_cropper(e["bbox"], width_pt, height_pt) for e in rule],
            "yolo": [padded_like_cropper(e["bbox"], width_pt, height_pt) for e in yolo],
        }
        row: Dict[str, Any] = {"doc_name": gt["doc_name"], "page_number": gt["page_number"], "gt_count": len(gt_boxes)}
        for m in methods:
            hit = matched_gt_count(gt_boxes, preds[m])
            hits[m] += hit
            row[f"{m}_hit"] = hit
            row[f"{m}_pred_count"] = len(preds[m])
        total_gt += len(gt_boxes)
        pages.append(row)

    n_pages = len(gt_files)
    summary = {
        "pages": n_pages,
        "gt_elements": total_gt,
        "reviewed_only": not args.include_unreviewed,
        **{m: {"crop_recall": round(hits[m] / total_gt, 4) if total_gt else None,
               "matched": hits[m],
               "sec_per_page": round(seconds[m] / n_pages, 3),
               "sec_per_10_pages": round(seconds[m] / n_pages * 10, 1)} for m in methods},
    }
    out_dir = gt_dir / "_eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "crop_eval.json").write_text(
        json.dumps({"summary": summary, "pages": pages}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"정답 {n_pages}페이지, 요소 {total_gt}개" + ("" if not args.include_unreviewed else " (초안 포함, 참고용)"))
    for m, label in (("rule", "지금 방식"), ("yolo", "YOLO")):
        s = summary[m]
        print(f"  {label:6} crop_recall {s['crop_recall']}  ({s['matched']}/{total_gt}),  "
              f"탐지 시간 페이지당 {s['sec_per_page']}초 → 10페이지 {s['sec_per_10_pages']}초")
    missed = [r for r in pages if r["rule_hit"] < r["gt_count"] or r["yolo_hit"] < r["gt_count"]]
    if missed:
        print("놓친 정답이 있는 페이지 (정답 수 / 지금 방식 / YOLO):")
        for r in missed:
            print(f"  {r['doc_name']} p.{r['page_number']}: {r['gt_count']} / {r['rule_hit']} / {r['yolo_hit']}")
    print(f"자세한 결과: {out_dir / 'crop_eval.json'}")


if __name__ == "__main__":
    main()
