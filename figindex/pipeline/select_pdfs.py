"""
색인 대상 PDF 고르기 스크립트

data/pdfs 바로 아래 = 색인 대상, data/pdfs/_incoming = 보관(색인 안 함) 으로 나눕니다.
  - RPT_ 로 시작하는 증권사 리포트는 항상 색인 대상
  - 아래 KEEP_KEYWORDS 중 하나가 파일명에 들어 있으면 색인 대상
  - 나머지는 _incoming 으로 옮겨 보관 (지우지 않음)

실행 방법 (figindex 폴더에서)
  1) 팀원이 올린 폴더(예: 26.11.11)를 통째로 data/pdfs/_incoming/ 안에 넣기
  2) 미리보기:  docker compose run --rm pipeline python select_pdfs.py
  3) 실제 이동: docker compose run --rm pipeline python select_pdfs.py --apply

고를 자료를 바꾸고 싶으면 KEEP_KEYWORDS 에 파일명 일부를 추가/삭제하면 됩니다.
"""

import argparse
import shutil
import unicodedata
from pathlib import Path

# 파일명에 이 글자가 들어 있으면 색인 대상 (공백 무시)
KEEP_KEYWORDS = [
    # ── 1차 묶음: 공공자료·IR (전부)
    "수출입물가지수", "수출입동향", "고용동향", "여름철전력수급", "OECD한국경제보고서",
    "주요업무추진계획", "경제전망_KDI", "삼성SDS",
    # ── 1차 묶음: 리포트와 주제가 겹치는 논문
    "해상풍속재현성", "수상태양광발전", "금속단일원자전기화학촉매", "실효지급준비율",
    "탄소섬유복합재", "온실가스관측망", "BERT보안로그",
    # ── 2차 묶음: 에너지 (CS윈드·한화솔루션·고려아연·에코프로비엠 등과 짝)
    "해상풍력보급확대", "영농형태양광", "재생에너지보급비용최소화", "핵심광물자원의공급망",
    "핵심광물재자원화", "최적수소공급믹스", "천연수소의잠재성", "세계석유가스교역변화",
    # ── 2차 묶음: 반도체·AI·R&D (삼성전자·SK하이닉스 등과 짝)
    "AI반도체의미래", "트럼프2기반도체수출통제", "세계RD투자상위기업", "휴머노이드로봇RD",
    # ── 2차 묶음: 거시경제
    "202605122026년세계경제전망", "최근환율추세", "유가충격", "IMD세계경쟁력",
    # ── 2차 묶음: 바이오 (SK바이오팜·파마리서치 등과 짝)
    "신약개발정부RD",
]

SKIP_DIRS = {"_renamed", "_original"}


def norm(text: str) -> str:
    return unicodedata.normalize("NFC", text).replace(" ", "")


def is_keep(name: str) -> str:
    n = norm(name)
    if n.startswith("RPT_"):
        return "RPT"
    for kw in KEEP_KEYWORDS:
        if norm(kw) in n:
            return kw
    return ""


def main():
    parser = argparse.ArgumentParser(description="색인 대상 PDF 고르기")
    parser.add_argument("--root", default="/data/pdfs")
    parser.add_argument("--apply", action="store_true", help="실제로 이동 (없으면 미리보기만)")
    args = parser.parse_args()

    root = Path(args.root)
    incoming = root / "_incoming"

    top_files = sorted(root.glob("*.pdf"))
    inc_files = sorted(p for p in incoming.rglob("*.pdf")
                       if not (SKIP_DIRS & set(p.relative_to(incoming).parts[:-1]))) if incoming.exists() else []

    moves, matched = [], {}
    # 1) 위에 있는데 대상이 아닌 것 → _incoming 으로
    for p in top_files:
        kw = is_keep(p.name)
        if kw:
            matched.setdefault(kw, []).append(p.name)
        else:
            moves.append((p, incoming / p.name, "보관으로"))
    # 2) _incoming 에 있는데 대상인 것 → 위로
    for p in inc_files:
        kw = is_keep(p.name)
        if kw and kw != "RPT":
            matched.setdefault(kw, []).append(p.name)
            moves.append((p, root / p.name, "색인 대상으로"))

    for src, dst, why in moves:
        print(f"[{why}] {norm(src.name)}")

    kept_total = sum(len(v) for v in matched.values())
    print(f"\n색인 대상: {kept_total}개 (증권사 리포트 {len(matched.get('RPT', []))}개 포함)")
    print(f"이동 예정: {len(moves)}개")

    missing = [kw for kw in KEEP_KEYWORDS if kw not in matched]
    if missing:
        print("\n[확인] 파일을 못 찾은 키워드:", ", ".join(missing))
    dup = {k: v for k, v in matched.items() if k != "RPT" and len(v) > 1}
    for k, v in dup.items():
        print(f"[확인] '{k}' 에 여러 파일이 걸림: {', '.join(map(norm, v))}")

    if not args.apply:
        print("\n미리보기만 했습니다. 괜찮으면 --apply 를 붙여 다시 실행하세요.")
        return

    incoming.mkdir(parents=True, exist_ok=True)
    done = 0
    for src, dst, _ in moves:
        if dst.exists():
            print(f"[건너뜀] 이미 같은 이름이 있음: {dst}")
            continue
        shutil.move(str(src), str(dst))
        done += 1
    print(f"\n이동 완료: {done}개")


if __name__ == "__main__":
    main()
