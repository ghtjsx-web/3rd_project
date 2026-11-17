"""검색 평가: 검색 정답셋으로 precision_at_5, search_latency_sec를 잰다 (docs/glossary.md 11·12절).

사용법 (서버가 켜져 있을 때, 저장소 루트에서):
    python scripts/eval_search.py
    python scripts/eval_search.py --exclude 1 --out result.json   # 튜닝에 쓴 검색어 번호(1부터)는 빼고 채점

정답셋은 채점 전용이다. 이 점수를 보고 정답셋을 고치지 않는다.
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP_K = 5


def evaluate(queries, base_url, exclude=()):
    rows = []
    for i, q in enumerate(queries, 1):
        if i in exclude:
            continue
        url = f"{base_url}/api/search?" + urllib.parse.urlencode({"q": q["query"], "limit": TOP_K})
        start = time.perf_counter()
        with urllib.request.urlopen(url, timeout=30) as resp:
            results = json.load(resp)
        latency = time.perf_counter() - start
        top_ids = [e["element_id"] for e in results[:TOP_K]]
        relevant = set(q["relevant_element_ids"])
        hits = sum(1 for eid in top_ids if eid in relevant)
        rows.append({"no": i, "query": q["query"], "hits": hits, "relevant_count": len(relevant),
                     "precision_at_5": hits / TOP_K, "search_latency_sec": latency, "top_ids": top_ids})
    return {
        "precision_at_5": sum(r["precision_at_5"] for r in rows) / len(rows),
        "search_latency_sec": sum(r["search_latency_sec"] for r in rows) / len(rows),
        "query_count": len(rows),
        "per_query": rows,
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", default=str(ROOT / "figindex/data/gt/search/queries.json"))
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--exclude", type=int, nargs="*", default=[], help="채점에서 뺄 검색어 번호(1부터)")
    ap.add_argument("--out", help="결과 JSON 저장 경로")
    args = ap.parse_args()

    queries = json.loads(Path(args.gt).read_text(encoding="utf-8"))
    result = evaluate(queries, args.base_url, set(args.exclude))

    for r in result["per_query"]:
        print(f"{r['no']:>2}. {r['hits']}/{TOP_K} (정답 {r['relevant_count']}개) {r['search_latency_sec']:.2f}초  {r['query']}")
    print(f"\nprecision_at_5 = {result['precision_at_5']:.3f} (목표 ≥ 0.75)")
    print(f"search_latency_sec = {result['search_latency_sec']:.3f} (목표 ≤ 1.0)")
    if args.exclude:
        print(f"채점에서 뺀 검색어: {sorted(args.exclude)}")
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
