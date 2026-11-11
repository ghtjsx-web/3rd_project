"""
DocLayout-YOLO 도표 탐지 성능 시험 및 기존 PDFCropper 비교 스크립트

실행 방법 (figindex 폴더에서):
  docker compose build pipeline
  docker compose run --rm pipeline python yolo_trial.py
  docker compose run --rm pipeline python yolo_trial.py --limit 5
"""

import argparse
import csv
import time
from collections import defaultdict
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageDraw
from huggingface_hub import hf_hub_download
from doclayout_yolo import YOLOv10

from cropper import PDFCropper


def draw_old_candidates(pil_img: Image.Image, candidates) -> Image.Image:
    """기존 PDFCropper().detect_candidate_boxes() 결과를 이미지 위에 그려 비교용 이미지 생성."""
    img = pil_img.copy()
    draw = ImageDraw.Draw(img)
    w, h = img.size

    for idx, cand in enumerate(candidates, start=1):
        ymin, xmin, ymax, xmax = cand["bbox"]
        x0, y0, x1, y1 = int(xmin * w), int(ymin * h), int(xmax * w), int(ymax * h)
        hint_type = cand.get("hint_type", "ELEMENT")
        color = (37, 99, 235) if hint_type == "TABLE" else (147, 51, 234)  # TABLE: 파랑, CHART: 보라

        draw.rectangle([x0, y0, x1, y1], outline=color, width=3)
        label = f"#{idx} {hint_type}"
        draw.rectangle([x0, max(0, y0 - 18), min(w, x0 + len(label) * 8 + 8), y0], fill=color)
        draw.text((x0 + 4, max(0, y0 - 15)), label, fill=(255, 255, 255))

    return img


def save_yolo_plot(result_obj, out_path: Path):
    """result[0].plot() (BGR numpy array)를 RGB PNG로 저장."""
    plotted = result_obj.plot()
    # OpenCV BGR -> RGB 변환 (numpy 인덱싱으로 cv2 의존성 없이 변환)
    rgb = plotted[:, :, ::-1]
    Image.fromarray(rgb).save(out_path)


def main():
    parser = argparse.ArgumentParser(description="DocLayout-YOLO 도표 탐지 시험 스크립트")
    parser.add_argument("--pdfs-dir", default="/data/pdfs", help="원본 PDF 폴더 경로")
    parser.add_argument("--out-dir", default="/data/yolo_trial", help="결과 저장 폴더 경로")
    parser.add_argument("--limit", type=int, default=10, help="앞에서부터 시험할 PDF 개수 (기본: 10)")
    parser.add_argument("--max-pages", type=int, default=4, help="PDF당 확인할 앞 페이지 수 (기본: 4)")
    parser.add_argument("--conf", type=float, default=0.25, help="YOLO 최소 확신도 (기본: 0.25)")
    args = parser.parse_args()

    pdfs_dir = Path(args.pdfs_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(pdfs_dir.glob("*.pdf"))[: args.limit]
    if not pdf_files:
        print(f"[오류] {pdfs_dir} 에 PDF 파일이 없습니다.")
        return

    print(f"[1/3] 시험 대상 PDF {len(pdf_files)}개 선정 완료 (각 최대 {args.max_pages}페이지)")
    print("[2/3] DocLayout-YOLO 모델 불러오는 중 (/root/.cache)...")
    model_path = hf_hub_download(
        repo_id="juliozhao/DocLayout-YOLO-DocStructBench",
        filename="doclayout_yolo_docstructbench_imgsz1024.pt",
    )
    model = YOLOv10(model_path)
    names = model.names  # {0: 'title', 3: 'figure', 5: 'table', ...}
    print(f"      모델 로드 완료! 클래스: {names}")

    cropper = PDFCropper()

    csv_rows = []
    pdf_stats = {}
    total_pages = 0
    total_yolo_sec = 0.0

    print("[3/3] 페이지별 탐지 및 비교 이미지 생성 시작...\n")
    for pdf_idx, pdf_path in enumerate(pdf_files, start=1):
        stem = pdf_path.stem
        doc = fitz.open(str(pdf_path))
        num_pages = min(args.max_pages, len(doc))

        table_total = 0
        figure_total = 0
        pdf_elapsed = 0.0

        print(f"({pdf_idx}/{len(pdf_files)}) {pdf_path.name} ({num_pages}p)")

        for page_num in range(1, num_pages + 1):
            page = doc[page_num - 1]
            page_img = cropper.render_page(doc, page_num)

            # 1) DocLayout-YOLO 예측
            t0 = time.perf_counter()
            results = model.predict(page_img, imgsz=1024, conf=args.conf, device="cpu", verbose=False)
            elapsed = time.perf_counter() - t0

            total_pages += 1
            total_yolo_sec += elapsed
            pdf_elapsed += elapsed

            # 2) YOLO 결과 이미지 저장
            yolo_out = out_dir / f"{stem}_p{page_num}_yolo.png"
            save_yolo_plot(results[0], yolo_out)

            # 3) 기존 PDFCropper 결과 이미지 저장
            old_candidates = cropper.detect_candidate_boxes(page)
            old_img = draw_old_candidates(page_img, old_candidates)
            old_out = out_dir / f"{stem}_p{page_num}_old.png"
            old_img.save(old_out)

            # 4) 탐지 종류별 통계 집계
            confs_by_cls = defaultdict(list)
            boxes = results[0].boxes
            if boxes is not None and len(boxes) > 0:
                for cls_id, conf in zip(boxes.cls.tolist(), boxes.conf.tolist()):
                    cls_name = str(names.get(int(cls_id), f"cls_{int(cls_id)}"))
                    confs_by_cls[cls_name].append(float(conf))

            table_cnt = len(confs_by_cls.get("table", []))
            figure_cnt = len(confs_by_cls.get("figure", []))
            table_total += table_cnt
            figure_total += figure_cnt

            if confs_by_cls:
                for cls_name, cls_confs in sorted(confs_by_cls.items()):
                    avg_conf = sum(cls_confs) / len(cls_confs)
                    csv_rows.append({
                        "file_name": pdf_path.name,
                        "page": page_num,
                        "detect_type": cls_name,
                        "count": len(cls_confs),
                        "confidence": round(avg_conf, 4),
                        "elapsed_sec": round(elapsed, 3),
                    })
            else:
                csv_rows.append({
                    "file_name": pdf_path.name,
                    "page": page_num,
                    "detect_type": "none",
                    "count": 0,
                    "confidence": 0.0,
                    "elapsed_sec": round(elapsed, 3),
                })

            print(
                f"   - p.{page_num}: YOLO table={table_cnt}, figure={figure_cnt} ({elapsed:.2f}s) "
                f"| OLD 후보={len(old_candidates)}"
            )

        doc.close()
        pdf_stats[pdf_path.name] = {
            "pages": num_pages,
            "tables": table_total,
            "figures": figure_total,
            "avg_sec": pdf_elapsed / num_pages if num_pages else 0.0,
        }

    # summary.csv 저장
    summary_path = out_dir / "summary.csv"
    with open(summary_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["file_name", "page", "detect_type", "count", "confidence", "elapsed_sec"],
        )
        writer.writeheader()
        writer.writerows(csv_rows)

    # 최종 요약 출력
    avg_per_page = total_yolo_sec / total_pages if total_pages else 0.0
    print("\n" + "=" * 68)
    print(f"DocLayout-YOLO 시험 완료 (총 {len(pdf_files)}개 PDF / {total_pages}페이지)")
    print("=" * 68)
    print(f"{'파일명':<32} {'페이지':>4} {'table':>6} {'figure':>7} {'평균시간':>8}")
    print("-" * 68)
    for fname, st in pdf_stats.items():
        print(
            f"{fname:<32} {st['pages']:>4}p {st['tables']:>6} {st['figures']:>7} {st['avg_sec']:>7.2f}s"
        )
    print("-" * 68)
    print(f"페이지당 평균 처리 시간: {avg_per_page:.2f}초 (총 {total_yolo_sec:.2f}초)")
    print(f"결과 저장 폴더 : {out_dir}")
    print(f"요약 CSV 파일  : {summary_path}")


if __name__ == "__main__":
    main()

