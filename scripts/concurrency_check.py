"""
백엔드 동시 요청 안정성 검증 스크립트 (로컬 모드 / 서버 모드 공통).

/api/elements?limit=100 과 /api/filter-options 요청을 동시에 N쌍(기본 20쌍 = 40건) 전송하여
Qdrant 파일 잠금 충돌 또는 500 에러가 발생하지 않는지 확인합니다.

사용 예:
  python scripts/concurrency_check.py
  python scripts/concurrency_check.py --base-url http://localhost:8000 --pairs 20
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List


def fetch_once(url: str, timeout: float = 15.0) -> Dict[str, Any]:
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            elapsed = time.perf_counter() - start
            count = len(data) if isinstance(data, list) else len(data.get("doc_types", []))
            return {
                "url": url,
                "status": resp.status,
                "elapsed": elapsed,
                "items": count,
                "error": None,
            }
    except urllib.error.HTTPError as e:
        elapsed = time.perf_counter() - start
        raw = e.read().decode("utf-8", errors="replace")
        return {
            "url": url,
            "status": e.code,
            "elapsed": elapsed,
            "items": 0,
            "error": raw[:300],
        }
    except Exception as e:
        elapsed = time.perf_counter() - start
        return {
            "url": url,
            "status": -1,
            "elapsed": elapsed,
            "items": 0,
            "error": str(e),
        }


def run_check(base_url: str, pairs: int) -> int:
    base = base_url.rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=5.0) as hresp:
            health = json.loads(hresp.read().decode("utf-8"))
    except Exception as e:
        print(f"[Error] /health 조회 실패 ({base}/health): {e}")
        return 1

    print("=" * 68)
    print(" FigIndex 동시 요청 안정성 테스트")
    print(f" - 대상 API: {base}")
    print(f" - Qdrant 모드: {health.get('qdrant_mode')} ({health.get('qdrant_url')})")
    print(f" - 컬렉션 포인트 수: {health.get('total_elements')}")
    print(f" - 동시 요청 수: {pairs}쌍 (총 {pairs * 2}건)")
    print("=" * 68)

    urls: List[str] = []
    for _ in range(pairs):
        urls.append(f"{base}/api/elements?limit=100")
        urls.append(f"{base}/api/filter-options")

    t0 = time.perf_counter()
    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=len(urls)) as pool:
        futures = [pool.submit(fetch_once, u) for u in urls]
        for fut in as_completed(futures):
            results.append(fut.result())
    total_elapsed = time.perf_counter() - t0

    status_counts = Counter(r["status"] for r in results)
    latencies = [r["elapsed"] for r in results]
    errors = [r for r in results if r["status"] != 200]
    err_500 = [r for r in results if r["status"] == 500]

    print(f"상태 코드 분포: {dict(sorted(status_counts.items()))}")
    print(
        f"응답 시간: min={min(latencies):.3f}s, "
        f"avg={sum(latencies)/len(latencies):.3f}s, "
        f"max={max(latencies):.3f}s (전체 {total_elapsed:.3f}s)"
    )

    if errors:
        print(f"[FAIL] 200이 아닌 응답 {len(errors)}건 (500 에러 {len(err_500)}건):")
        for err in errors[:5]:
            print(f"  - status={err['status']} url={err['url']} detail={err['error']}")
        return 1

    print(f"[PASS] 동시 {len(results)}건 모두 HTTP 200 응답 (500 에러 0건)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="FigIndex concurrent API check")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend API base URL")
    parser.add_argument("--pairs", type=int, default=20, help="Concurrent request pairs (default: 20)")
    args = parser.parse_args()
    sys.exit(run_check(args.base_url, args.pairs))


if __name__ == "__main__":
    main()

