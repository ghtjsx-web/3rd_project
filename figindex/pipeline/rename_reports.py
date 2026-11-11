"""
증권사 리포트 PDF 파일명 정리 스크립트

하는 일
  1. data/pdfs/ 안의 PDF를 하나씩 열어 표지(1페이지)와 본문에서
     증권사, 발행일, 종목코드를 찾습니다.
  2. 새 이름을  RPT_발행일_대상_증권사.pdf  형식으로 만듭니다.
  3. 원본은 그대로 두고, 새 이름으로 복사한 파일을 data/pdfs/_renamed/ 에 저장합니다.
  4. 대조표(rename_plan.csv)와 드라이브 metadata 시트에 붙여 넣을 metadata.csv를 만듭니다.

실행 방법 (figindex 폴더에서)
  미리보기만:  docker compose run --rm pipeline python rename_reports.py
  실제 복사:   docker compose run --rm pipeline python rename_reports.py --apply

결과의 flags 칸에 값이 있는 파일은 PDF를 열어 직접 확인해 주세요.
"""

import argparse
import csv
import re
import shutil
import sys
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF

DEFAULT_YEAR = 2026

# 파일명 속 이름 → 정식 이름 (필요하면 여기에 추가)
TARGET_ALIASES = {
    "삼전": "삼성전자",
    "하이닉스": "SK하이닉스",
    "kakao": "카카오",
    "sk텔레콤": "SK텔레콤",
    "한화솔루견": "한화솔루션",
    "KT&G": "KTnG",
    "교촌F&B": "교촌에프앤비",
    "CJ ENM": "CJENM",
    "스튜디오 드래곤": "스튜디오드래곤",
}

# 증권사 이름 → 본문에서 찾을 표기들 (한글 + 영문)
BROKERS = {
    "대신증권": ["대신증권", "DAISHIN SECURITIES", "daishin.com"],
    "키움증권": ["키움증권", "Kiwoom Securities", "kiwoom.com"],
    "미래에셋증권": ["미래에셋증권", "Mirae Asset Securities", "miraeasset.com"],
    "삼성증권": ["삼성증권", "Samsung Securities", "samsungpop.com"],
    "NH투자증권": ["NH투자증권", "NH Investment", "nhqv.com"],
    "한국투자증권": ["한국투자증권", "Korea Investment & Securities", "truefriend.com"],
    "KB증권": ["KB증권", "KB Securities", "kbsec.com"],
    "신한투자증권": ["신한투자증권", "Shinhan Securities"],
    "하나증권": ["하나증권", "Hana Securities"],
    "메리츠증권": ["메리츠증권", "Meritz Securities"],
    "유안타증권": ["유안타증권", "Yuanta Securities"],
    "교보증권": ["교보증권", "Kyobo Securities"],
    "현대차증권": ["현대차증권", "Hyundai Motor Securities"],
    "한화투자증권": ["한화투자증권", "Hanwha Investment"],
    "SK증권": ["SK증권", "SK Securities"],
    "유진투자증권": ["유진투자증권", "Eugene Investment"],
    "DB증권": ["DB증권", "DB금융투자", "DB Securities", "DB Financial Investment"],
    "iM증권": ["iM증권", "iM Securities", "하이투자증권"],
    "IBK투자증권": ["IBK투자증권", "IBK Securities"],
    "다올투자증권": ["다올투자증권", "DAOL"],
    "상상인증권": ["상상인증권", "sangsanginib.com"],
    "LS증권": ["LS증권", "LS Securities", "이베스트투자증권"],
    "신영증권": ["신영증권", "Shinyoung Securities"],
    "BNK투자증권": ["BNK투자증권"],
    "한양증권": ["한양증권"],
    "부국증권": ["부국증권"],
    "DS투자증권": ["DS투자증권"],
    "흥국증권": ["흥국증권"],
    "케이프투자증권": ["케이프투자증권"],
    "리딩투자증권": ["리딩투자증권"],
    "한국IR협의회": ["한국IR협의회", "IR협의회"],
}

DATE_RE = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")
TICKER_RE = re.compile(r"\((\d{6})\)|\b(A?\d{6})\b")


def nfc(text: str) -> str:
    """맥/윈도우 한글 파일명 차이를 없애기 위해 NFC로 통일"""
    return unicodedata.normalize("NFC", text)


def parse_filename(stem: str):
    """'BGF리테일1106' → ('BGF리테일', date(2026, 11, 6))"""
    stem = nfc(stem).strip()
    m = re.match(r"^(.*?)[\s_-]*(\d{2})(\d{2})$", stem)
    if not m:
        return stem, None
    name, mm, dd = m.group(1).strip(), int(m.group(2)), int(m.group(3))
    try:
        return name, date(DEFAULT_YEAR, mm, dd)
    except ValueError:
        return name, None


def clean_target(name: str) -> str:
    """정식 이름으로 바꾸고, 파일명에 못 쓰는 문자를 정리"""
    for alias, official in TARGET_ALIASES.items():
        if name.lower() == alias.lower():
            name = official
            break
    name = name.replace("&", "n")
    name = re.sub(r"[\s/\\:*?\"<>|()\[\]]+", "", name)
    return name


def find_broker(full_text: str):
    """본문 전체에서 가장 많이 나온 증권사를 고르고, 애매하면 표시"""
    scores = Counter()
    for broker, patterns in BROKERS.items():
        for p in patterns:
            scores[broker] += full_text.count(p) if not p.isascii() else full_text.lower().count(p.lower())
    scores = +scores  # 0인 항목 제거
    if not scores:
        return None, "증권사없음"
    ranked = scores.most_common()
    top, top_n = ranked[0]
    flag = ""
    if len(ranked) > 1 and ranked[1][1] >= top_n * 0.5:
        flag = f"증권사애매({ranked[0][0]}{ranked[0][1]}/{ranked[1][0]}{ranked[1][1]})"
    return top, flag


def find_publish_date(first_page: str, file_date):
    """표지의 날짜 중, 파일명 날짜 기준 -3일 ~ +10일 안에 있는 가장 늦은 날짜"""
    found = []
    # 공백이나 줄바꿈이 섞인 경우 (예: "2026. 11.\n07" 또는 "2026 . 11 . 07") 대응
    for y, m, d in re.findall(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})", first_page):
        try:
            found.append(date(int(y), int(m), int(d)))
        except ValueError:
            continue
    if file_date:
        near = [d for d in found if -3 <= (d - file_date).days <= 10]
        if near:
            return max(near), ""
        return file_date, "날짜확인(파일명 날짜 사용)"
    if found:
        return max(found), "날짜확인(파일명 날짜 없음)"
    return None, "날짜없음"


def analyze_via_vision(pdf_path: Path):
    """텍스트가 전혀 없는 스캔/이미지 PDF일 경우 1페이지를 렌더링해 Gemini Vision으로 증권사/발행일/종목코드 추출"""
    import os
    import io
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
        from PIL import Image
        import json

        doc = fitz.open(str(pdf_path))
        pix = doc[0].get_pixmap(dpi=150)
        doc.close()
        img = Image.open(io.BytesIO(pix.tobytes("png")))

        client = genai.Client(api_key=api_key)
        prompt = (
            "이 이미지는 한국 증권사 기업분석 리포트의 1페이지입니다.\n"
            "아래 3가지 정보를 JSON 형식으로만 정확히 추출하세요:\n"
            '{"broker": "증권사명(예: iM증권, 삼성증권 등)", "publish_date": "YYYY-MM-DD", "ticker": "6자리 종목코드"}\n'
            "정보가 없으면 빈 문자열로 두세요."
        )
        # .env 설정 모델 및 최신 무료 티어 호환 모델 사용
        primary_model = os.getenv("VISION_MODEL", "gemini-3.8-flash")
        models = [primary_model, "gemini-3.8-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash"]
        for model_name in dict.fromkeys(models):
            try:
                resp = client.models.generate_content(model=model_name, contents=[prompt, img])
                text = resp.text.strip()
                m = re.search(r"\{.*\}", text, re.DOTALL)
                if m:
                    return json.loads(m.group(0))
            except Exception:
                continue
    except Exception as e:
        print(f"  [Warn] Vision OCR fallback failed for {pdf_path.name}: {e}")
    return None


def find_ticker(first_page: str):
    m = TICKER_RE.search(first_page)
    if not m:
        return ""
    return (m.group(1) or m.group(2)).lstrip("A")


def analyze(pdf_path: Path):
    doc = fitz.open(str(pdf_path))
    first_page = doc[0].get_text("text") if len(doc) else ""
    full_text = "\n".join(page.get_text("text") for page in doc)
    doc.close()

    raw_name, file_date = parse_filename(pdf_path.stem)
    target = clean_target(raw_name)
    broker, broker_flag = find_broker(full_text)
    pub_date, date_flag = find_publish_date(first_page, file_date)
    ticker = find_ticker(first_page)

    # 텍스트 추출이 비어 있는 이미지/스캔 PDF(예: KB금융1105, 우리금융지주1105 등) Vision 폴백
    if not full_text.strip():
        vdata = analyze_via_vision(pdf_path)
        if vdata:
            if not broker and vdata.get("broker"):
                broker = vdata["broker"].strip()
                broker_flag = ""
            if vdata.get("publish_date"):
                try:
                    pub_date = date.fromisoformat(vdata["publish_date"].strip())
                    date_flag = ""
                except ValueError:
                    pass
            if not ticker and vdata.get("ticker"):
                ticker = re.sub(r"\D", "", str(vdata["ticker"]))[:6]

    # 이미지/스캔 PDF에서 실제 추출된 텍스트를 보강하기 위해 1페이지 텍스트에서 날짜/제목 확인
    # 상상인증권 LG화학1107.pdf처럼 PyMuPDF 텍스트 추출 시 상단 이미지 영역 텍스트('2026.11.07')가 누락된 경우,
    # 1페이지 상단 이미지 OCR 또는 Gemini Vision으로 날짜 보강
    if "날짜확인" in date_flag:
        vdata = analyze_via_vision(pdf_path)
        if vdata and vdata.get("publish_date"):
            try:
                vdate = date.fromisoformat(vdata["publish_date"].strip())
                if not file_date or -3 <= (vdate - file_date).days <= 10:
                    pub_date = vdate
                    date_flag = ""
            except ValueError:
                pass

    flags = ";".join(f for f in [broker_flag, date_flag] if f)
    date_str = pub_date.strftime("%Y%m%d") if pub_date else "00000000"
    new_name = f"RPT_{date_str}_{target}_{broker or '미확인'}.pdf"
    return {
        "original_file_name": nfc(pdf_path.name),
        "file_name": nfc(new_name),
        "target": target,
        "source_org": broker or "",
        "publish_date": pub_date.isoformat() if pub_date else "",
        "ticker": ticker,
        "flags": flags,
    }


def main():
    parser = argparse.ArgumentParser(description="증권사 리포트 PDF 파일명 정리")
    parser.add_argument("--src", default="/data/pdfs", help="원본 PDF 폴더")
    parser.add_argument("--out", default="/data/pdfs/_renamed", help="새 이름으로 복사할 폴더")
    parser.add_argument("--apply", action="store_true", help="실제로 복사 (없으면 미리보기만)")
    args = parser.parse_args()

    src, out = Path(args.src), Path(args.out)
    pdfs = sorted(src.glob("*.pdf"))
    if not pdfs:
        sys.exit(f"[오류] {src} 에 PDF가 없습니다.")

    rows, used = [], Counter()
    for p in pdfs:
        try:
            row = analyze(p)
        except Exception as e:  # 깨진 PDF 등
            row = {"original_file_name": nfc(p.name), "file_name": "", "target": "", "source_org": "",
                   "publish_date": "", "ticker": "", "flags": f"열기실패({e})"}
            row["_src"] = p
            rows.append(row)
            continue
        # 같은 이름이 또 나오면 _2, _3 붙이기
        used[row["file_name"]] += 1
        if used[row["file_name"]] > 1:
            row["file_name"] = row["file_name"].replace(".pdf", f"_{used[row['file_name']]}.pdf")
        row["_src"] = p
        rows.append(row)

    # 화면 출력
    for r in rows:
        mark = "  [확인]" if r["flags"] else ""
        print(f"{r['original_file_name']:<28} → {r['file_name']}{mark}")
        if r["flags"]:
            print(f"{'':<31}{r['flags']}")

    flagged = sum(1 for r in rows if r["flags"])
    print(f"\n총 {len(rows)}개, 확인 필요 {flagged}개")

    # 대조표 + 메타데이터 CSV (엑셀에서 한글이 안 깨지도록 utf-8-sig)
    out.mkdir(parents=True, exist_ok=True)
    plan_path = out / "rename_plan.csv"
    with open(plan_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["original_file_name", "file_name", "target", "source_org",
                                          "publish_date", "ticker", "flags"])
        w.writeheader()
        w.writerows({k: v for k, v in r.items() if k != "_src"} for r in rows)

    meta_path = out / "metadata.csv"
    with open(meta_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["file_name", "doc_type", "target", "source_org", "publish_date",
                    "source_url", "license_note", "original_file_name"])
        for r in rows:
            if r["file_name"]:
                w.writerow([r["file_name"], "REPORT", r["target"], r["source_org"], r["publish_date"],
                            "", "", r["original_file_name"]])
    print(f"대조표: {plan_path}\n메타데이터: {meta_path}")

    if not args.apply:
        print("\n미리보기만 했습니다. 결과가 괜찮으면 --apply 를 붙여 다시 실행하세요.")
        return

    for r in rows:
        if r["file_name"]:
            shutil.copy2(r["_src"], out / r["file_name"])
    print(f"\n복사 완료 → {out} (원본은 그대로 있습니다)")


if __name__ == "__main__":
    main()
