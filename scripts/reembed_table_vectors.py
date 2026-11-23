#!/usr/bin/env python3
"""
scripts/reembed_table_vectors.py

v2에 이미 저장된 요소 중 "새 색인 글자가 예전 글자와 다른 것"(= table_data가 유효한 표)만
dense 및 sparse 벡터를 다시 계산하여 교체(update_vectors)하는 스크립트입니다.

주의 및 원칙:
1. point id 및 payload(element_id 포함)는 절대 변경하지 않습니다.
2. 기본은 dry-run 모드입니다. --apply 옵션을 명시해야만 실제 쓰기가 실행됩니다.
3. --collection이 figindex_elements_v2인 경우 --confirm-v2 옵션이 반드시 함께 있어야 실행됩니다.
4. 실제 쓰기 전 반드시 Qdrant 스냅샷을 생성하고 이름을 기록합니다.
5. 임베딩 호출 실패 시 가짜 대체 벡터를 생성하지 않고 즉시 작업을 중단합니다.
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
FIGINDEX_DIR = REPO_ROOT / "figindex"
if str(FIGINDEX_DIR) not in sys.path:
    sys.path.insert(0, str(FIGINDEX_DIR))
if Path("/app").exists() and "/app" not in sys.path:
    sys.path.insert(0, "/app")

from shared.index_text import build_index_text
from shared.sparse import build_sparse_vector

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def is_reembed_target(payload: Dict[str, Any]) -> Tuple[bool, str, str]:
    """
    해당 payload가 벡터 재계산 대상인지 판정합니다.

    - legacy_text: table_data를 제거한 payload로 생성한 기본 색인 글자
    - new_text: 원본 payload로 생성한 새 색인 글자
    - new_text != legacy_text 인 경우(표 열/행 라벨이 추가된 경우)에만 대상(True)으로 판정합니다.

    Returns:
        (is_target, legacy_text, new_text)
    """
    if not isinstance(payload, dict):
        return False, "", ""

    # table_data를 제거한 얕은 복사본으로 예전 색인 글자 계산
    p_without_table = dict(payload)
    p_without_table.pop("table_data", None)
    legacy_text = build_index_text(p_without_table)

    new_text = build_index_text(payload)
    return (legacy_text != new_text), legacy_text, new_text


def scroll_all_qdrant_points(qdrant_url: str, collection_name: str) -> List[Dict[str, Any]]:
    """Qdrant에서 payload를 포함하여 모든 포인트를 scroll로 순회 조회합니다."""
    scroll_url = f"{qdrant_url.rstrip('/')}/collections/{collection_name}/points/scroll"
    all_points: List[Dict[str, Any]] = []
    next_offset: Optional[Any] = None

    while True:
        body: Dict[str, Any] = {
            "limit": 100,
            "with_payload": True,
            "with_vector": False,
        }
        if next_offset is not None:
            body["offset"] = next_offset

        req = urllib.request.Request(
            scroll_url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            logger.error(f"Qdrant scroll 실패 ({scroll_url}): {e}")
            sys.exit(1)

        result = data.get("result", {})
        points = result.get("points", [])
        all_points.extend(points)

        next_offset = result.get("next_page_offset")
        if not next_offset:
            break

    return all_points


def get_collection_vector_names(qdrant_url: str, collection_name: str) -> Tuple[str, str]:
    """컬렉션 설정을 조회하여 dense 및 sparse 벡터 이름을 확인합니다 (추측 금지)."""
    url = f"{qdrant_url.rstrip('/')}/collections/{collection_name}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        logger.error(f"컬렉션 설정 조회 실패 ({url}): {e}")
        sys.exit(1)

    params = data.get("result", {}).get("config", {}).get("params", {})
    vectors = params.get("vectors", {})
    sparse_vectors = params.get("sparse_vectors", {})

    if not isinstance(vectors, dict) or not vectors:
        raise RuntimeError(f"컬렉션 '{collection_name}'에 명명된 dense 벡터 설정이 없습니다: {vectors}")
    if not isinstance(sparse_vectors, dict) or not sparse_vectors:
        raise RuntimeError(f"컬렉션 '{collection_name}'에 sparse 벡터 설정이 없습니다: {sparse_vectors}")

    dense_name = next(iter(vectors.keys()))
    sparse_name = next(iter(sparse_vectors.keys()))
    return dense_name, sparse_name


def create_qdrant_snapshot(qdrant_url: str, collection_name: str) -> str:
    """
    컬렉션 스냅샷을 생성하고 스냅샷 이름을 반환합니다.
    (과거 스냅샷을 재사용하지 않고 --apply 시 항상 새 스냅샷을 생성합니다)
    """
    url = f"{qdrant_url.rstrip('/')}/collections/{collection_name}/snapshots"
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=300.0) as resp:
        res = json.loads(resp.read().decode("utf-8"))

    snapshot_name = res.get("result", {}).get("name")
    if not snapshot_name:
        raise RuntimeError(f"스냅샷 생성 실패 응답: {res}")
    return snapshot_name


def update_vectors_batch(
    qdrant_url: str,
    collection_name: str,
    points_to_update: List[Dict[str, Any]]
) -> int:
    """
    PUT /collections/{collection_name}/points/vectors 엔드포인트를 호출하여
    dense 및 sparse 벡터를 배치로 교체합니다.
    """
    if not points_to_update:
        return 0
    url = f"{qdrant_url.rstrip('/')}/collections/{collection_name}/points/vectors"
    payload = {"points": points_to_update}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PUT"
    )
    with urllib.request.urlopen(req, timeout=60.0) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    if res.get("status") != "ok":
        raise RuntimeError(f"벡터 교체 업데이트 실패: {res}")
    return len(points_to_update)


def payload_hash(payload: Dict[str, Any]) -> str:
    """payload 불변 검증용 SHA-256 해시 계산"""
    s = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def run_reembed(
    collection_name: str,
    qdrant_url: str = "http://localhost:6333",
    apply: bool = False,
    confirm_v2: bool = False,
    batch_size: int = 20,
):
    # 안전 가드 검사
    if apply and collection_name == "figindex_elements_v2" and not confirm_v2:
        logger.error("[차단] figindex_elements_v2 컬렉션에 실제 적용(--apply)하려면 --confirm-v2 옵션이 필수입니다.")
        sys.exit(1)

    logger.info("=== FigIndex Table Re-embedding Tool ===")
    logger.info(f"Qdrant URL: {qdrant_url}")
    logger.info(f"컬렉션: {collection_name}")
    logger.info(f"모드: {'[실제 적용 --apply]' if apply else '[DRY-RUN (조회 전용)]'}")

    # 1. 컬렉션 설정에서 벡터 이름 조회
    dense_name, sparse_name = get_collection_vector_names(qdrant_url, collection_name)
    logger.info(f"확인된 벡터 필드: dense='{dense_name}', sparse='{sparse_name}'")

    # 2. 모든 포인트 scroll 조회
    logger.info("모든 포인트 조회 중 (with_payload=True, with_vectors=False)...")
    all_points = scroll_all_qdrant_points(qdrant_url, collection_name)
    total_points = len(all_points)
    logger.info(f"조회 완료: 총 {total_points}개 포인트")

    # 3. 대상 선별 및 통계 집계
    targets: List[Dict[str, Any]] = []
    type_counts = defaultdict(int)
    truncated_count = 0

    for pt in all_points:
        payload = pt.get("payload") or {}
        is_target, legacy_txt, new_txt = is_reembed_target(payload)
        if is_target:
            targets.append({
                "point": pt,
                "payload": payload,
                "legacy_text": legacy_txt,
                "new_text": new_txt,
            })
            elem_type = payload.get("element_type", "UNKNOWN")
            type_counts[elem_type] += 1
            if len(new_txt) > 4000:
                truncated_count += 1

    # 4. Dry-run 요약 출력
    print("\n" + "=" * 70)
    print("                재임베딩 대상 분석 요약 (Dry-run)")
    print("=" * 70)
    print(f"▶ 전체 포인트 수: {total_points}건")
    print(f"▶ 재임베딩 대상 수: {len(targets)}건 (새 색인 글자가 예전 글자와 다른 표)")
    print("▶ 대상 유형별 집계:")
    for etype, cnt in sorted(type_counts.items()):
        print(f"   - {etype}: {cnt}건")
    print(f"▶ 새 글자가 4000자 한도를 초과하는 대상 수: {truncated_count}건")

    print("\n▶ 대상 샘플 3개 미리보기:")
    for idx, t in enumerate(targets[:3], 1):
        p = t["payload"]
        eid = p.get("element_id", "N/A")
        caption = p.get("caption", "N/A")
        added_text = t["new_text"][len(t["legacy_text"]):].strip()
        print(f" [{idx}] element_id: {eid}")
        print(f"     캡션: {caption}")
        print(f"     추가되는 표 이름: {added_text[:120]}{'...' if len(added_text) > 120 else ''}")

    print("=" * 70 + "\n")

    if not apply:
        logger.info("Dry-run이 완료되었습니다. 실제 적용하려면 --apply 옵션을 사용하세요 (v2의 경우 --confirm-v2 필수).")
        return

    # 5. 실제 실행 (--apply)
    logger.info("[실제 적용 모드 시작]")

    # ① 스냅샷 생성
    logger.info("1단계: Qdrant 컬렉션 스냅샷 생성 중...")
    snapshot_name = create_qdrant_snapshot(qdrant_url, collection_name)
    logger.info(f"✔ 스냅샷 생성 완료: {snapshot_name}")
    logger.info("이 스냅샷은 컨테이너 안에만 있어 docker compose down 시 사라짐. 되돌리기 기준은 data/qdrant 폴더 백업")

    # ② OpenAI 클라이언트 초기화
    if OpenAI is None:
        logger.error("OpenAI 라이브러리가 설치되지 않았습니다. pip install openai 를 실행하세요.")
        sys.exit(1)
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        logger.error("OPENAI_API_KEY 환경변수가 설정되지 않았습니다.")
        sys.exit(1)
    client = OpenAI(api_key=openai_key)

    # 사전 검증용: 대상 앞 3개의 payload 해시 기록
    pre_hashes = {t["point"]["id"]: payload_hash(t["payload"]) for t in targets[:3]}

    # ③ 임베딩 계산 및 20개 단위 배치 교체
    logger.info(f"2단계: 대상 {len(targets)}건 임베딩 계산 및 벡터 교체 (배치 크기: {batch_size})...")
    batch_buffer: List[Dict[str, Any]] = []
    success_count = 0
    last_success_element_id = "N/A"

    for i, t in enumerate(targets, 1):
        pid = t["point"]["id"]
        eid = t["payload"].get("element_id", "N/A")
        text_to_embed = t["new_text"][:4000]

        # dense 임베딩 직접 호출 (실패 시 가짜 벡터 없이 즉시 예외 발생)
        try:
            resp = client.embeddings.create(input=text_to_embed, model="text-embedding-3-small")
            dense_vec = resp.data[0].embedding
        except Exception as e:
            logger.error(
                f"★ [치명적 오류] OpenAI 임베딩 호출 실패!\n"
                f"   진행도: {success_count}/{len(targets)} 성공\n"
                f"   마지막 성공 element_id: {last_success_element_id}\n"
                f"   실패 대상 element_id: {eid} (point_id: {pid})\n"
                f"   원인: {e}"
            )
            raise

        # sparse 벡터 계산
        sparse_tokens = build_sparse_vector(text_to_embed)

        batch_buffer.append({
            "id": pid,
            "vector": {
                dense_name: dense_vec,
                sparse_name: {
                    "indices": list(sparse_tokens.keys()),
                    "values": list(sparse_tokens.values()),
                } if sparse_tokens else None
            }
        })

        success_count += 1
        last_success_element_id = eid

        if len(batch_buffer) >= batch_size:
            update_vectors_batch(qdrant_url, collection_name, batch_buffer)
            logger.info(f"[진행] {success_count}/{len(targets)} ({success_count / len(targets) * 100:.1f}%) 벡터 교체 완료")
            batch_buffer.clear()

    # 잔여 배치 전송
    if batch_buffer:
        update_vectors_batch(qdrant_url, collection_name, batch_buffer)
        logger.info(f"[진행] {success_count}/{len(targets)} (100.0%) 벡터 교체 완료")
        batch_buffer.clear()

    # ⑥ 완료 검증: 대상 3개를 다시 읽어 payload가 실행 전과 완전히 같은지(해시 비교) 및 총 포인트 수 비교
    logger.info("3단계: 사후 검증 (payload 불변 확인 및 포인트 수 대조)...")
    post_points = scroll_all_qdrant_points(qdrant_url, collection_name)
    post_points_map = {p["id"]: p for p in post_points}

    if len(post_points) != total_points:
        logger.error(f"[검증 실패] 전체 포인트 수가 실행 전({total_points})과 실행 후({len(post_points)}) 다릅니다!")
        sys.exit(1)

    for pid, pre_h in pre_hashes.items():
        post_p = post_points_map.get(pid)
        if not post_p:
            logger.error(f"[검증 실패] 대상 포인트 {pid}가 소실되었습니다!")
            sys.exit(1)
        post_h = payload_hash(post_p.get("payload") or {})
        if pre_h != post_h:
            logger.error(f"[검증 실패] 포인트 {pid}의 payload가 수정되었습니다! (pre={pre_h}, post={post_h})")
            sys.exit(1)

    logger.info(f"✔ 사후 검증 완료: 총 포인트 수 동일({total_points}건), 샘플 3건 payload SHA-256 해시 100% 일치")
    logger.info("=== 전체 재임베딩 교체 작업이 성공적으로 완료되었습니다 ===")


def main():
    parser = argparse.ArgumentParser(description="FigIndex 표 요소 dense/sparse 벡터 재임베딩 교체 스크립트")
    parser.add_argument("--collection", required=True, help="Qdrant 컬렉션 이름 (필수, 예: figindex_elements_v2)")
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"), help="Qdrant URL")
    parser.add_argument("--apply", action="store_true", help="실제 벡터 교체 실행 플래그 (기본: dry-run)")
    parser.add_argument("--confirm-v2", action="store_true", help="figindex_elements_v2 컬렉션에 --apply 시 필수 확인 플래그")
    parser.add_argument("--batch-size", type=int, default=20, help="update_vectors 배치 크기 (기본값: 20)")
    args = parser.parse_args()

    run_reembed(
        collection_name=args.collection,
        qdrant_url=args.qdrant_url,
        apply=args.apply,
        confirm_v2=args.confirm_v2,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
