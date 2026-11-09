"""
Generate a realistic sample financial research report PDF for FigIndex PoC testing.
Output: data/sample_pdfs/20250115_SK하이닉스_삼성증권.pdf
"""
from pathlib import Path
import fitz  # PyMuPDF

from app.core.config import settings

def create_sample_report():
    output_dir = settings.SAMPLE_PDFS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / "20250115_SK하이닉스_삼성증권.pdf"

    doc = fitz.open()

    # --- Page 1: Cover Page ---
    p1 = doc.new_page(width=595, height=842)  # A4 size in points
    # Header
    p1.draw_rect(fitz.Rect(40, 40, 555, 45), fill=(0.1, 0.2, 0.4))
    p1.insert_text(fitz.Point(40, 35), "SAMSUNG SECURITIES RESEARCH", fontsize=10, color=(0.3, 0.3, 0.3))
    
    # Title & Metadata
    p1.insert_text(fitz.Point(40, 90), "Company In-depth Report", fontsize=14, color=(0.1, 0.2, 0.4))
    p1.insert_text(fitz.Point(40, 130), "SK하이닉스 (000660)", fontsize=26, fontname="helv", color=(0.0, 0.0, 0.0))
    p1.insert_text(fitz.Point(40, 160), "HBM3E 독주 체제 지속과 실적 서프라이즈 전망", fontsize=16, color=(0.2, 0.2, 0.2))
    
    # Meta block
    p1.draw_rect(fitz.Rect(40, 190, 555, 250), fill=(0.95, 0.96, 0.98))
    p1.insert_text(fitz.Point(50, 215), "발행일자: 2025년 01월 15일 | 발행증권사: 삼성증권 | 섹터: 반도체", fontsize=11, color=(0.2, 0.2, 0.2))
    p1.insert_text(fitz.Point(50, 235), "담당 연구원: 김연구 수석연구위원 (반도체/IT 테크)", fontsize=11, color=(0.2, 0.2, 0.2))

    # Executive Summary text
    p1.insert_text(fitz.Point(40, 290), "Executive Summary", fontsize=15, color=(0.1, 0.2, 0.4))
    summary_text = (
        "SK하이닉스는 1b D램 기반 8단 및 12단 HBM3E 공급을 본격 확대하며 AI 메모리 시장에서의\n"
        "지배력을 확고히 하고 있습니다. 2025년 연간 영업이익은 HBM 수요 급증에 힘입어 전년 대비\n"
        "대폭 개선된 사상 최대치를 경신할 것으로 예상됩니다."
    )
    p1.insert_text(fitz.Point(40, 320), summary_text, fontsize=11, color=(0.1, 0.1, 0.1))

    # --- Page 2: Financial Table Page ---
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text(fitz.Point(40, 60), "SK하이닉스 실적 분석 및 전망", fontsize=14, color=(0.1, 0.2, 0.4))
    
    # Table Title (Caption)
    p2.insert_text(fitz.Point(40, 110), "[표 1] SK하이닉스 연간 및 분기 실적 추정치", fontsize=12, color=(0.0, 0.0, 0.0))
    p2.insert_text(fitz.Point(450, 110), "(단위: 십억원, %)", fontsize=10, color=(0.4, 0.4, 0.4))

    # Table Grid
    table_rect = fitz.Rect(40, 120, 555, 300)
    p2.draw_rect(table_rect, color=(0.7, 0.7, 0.7), width=1)
    
    # Header fill
    p2.draw_rect(fitz.Rect(40, 120, 555, 150), fill=(0.9, 0.93, 0.97))
    
    # Header columns
    cols = ["구분", "2023", "2024E", "2025E", "2026E", "YoY (25E)"]
    col_x = [45, 140, 220, 300, 380, 470]
    for x, col in zip(col_x, cols):
        p2.insert_text(fitz.Point(x, 140), col, fontsize=10, color=(0.1, 0.1, 0.1))

    # Table rows
    rows_data = [
        ("매출액", "32,765", "66,190", "85,420", "98,300", "+29.1%"),
        ("영업이익", "-7,730", "23,480", "34,250", "41,100", "+45.9%"),
        ("EBITDA", "5,420", "35,120", "48,900", "57,200", "+39.2%"),
        ("순이익", "-9,138", "19,250", "27,800", "33,500", "+44.4%"),
        ("영업이익률", "-23.6%", "35.5%", "40.1%", "41.8%", "+4.6%p"),
    ]
    
    y = 175
    for row in rows_data:
        p2.draw_line(fitz.Point(40, y - 15), fitz.Point(555, y - 15), color=(0.85, 0.85, 0.85))
        for x, val in zip(col_x, row):
            p2.insert_text(fitz.Point(x, y), val, fontsize=10, color=(0.15, 0.15, 0.15))
        y += 28

    # Table Footnote
    p2.insert_text(fitz.Point(40, 315), "자료: SK하이닉스, 삼성증권 리서치센터 추정치", fontsize=9, color=(0.5, 0.5, 0.5))

    # Body text below table
    p2.insert_text(fitz.Point(40, 360), "HBM3E 중심의 믹스 개선 효과", fontsize=13, color=(0.1, 0.2, 0.4))
    body_text = (
        "2025년 동사의 DRAM 출하 증가율은 15% 수준에 그칠 것이나, ASP(평균판매단가)는 고부가가치인\n"
        "HBM3E 비중 확대로 인해 전년 대비 20% 이상 상승할 전망입니다. 경쟁사 대비 수율 우위가\n"
        "지속되면서 프리미엄 가격 결정권이 유지될 것입니다."
    )
    p2.insert_text(fitz.Point(40, 390), body_text, fontsize=11, color=(0.2, 0.2, 0.2))

    # Save PDF
    doc.save(str(pdf_path))
    doc.close()
    print(f"Sample PDF successfully created at: {pdf_path}")
    return pdf_path

if __name__ == "__main__":
    create_sample_report()

