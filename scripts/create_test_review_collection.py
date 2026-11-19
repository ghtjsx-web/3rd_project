"""
FigIndex 검수 탭 단축키 테스트용 시험 컬렉션 생성 스크립트

역할:
- 실제 서비스 컬렉션(figindex_elements_v2)의 데이터는 건드리지 않고(읽기만 수행),
- 검수 대기(PENDING_REVIEW) 포인트 일부를 복사하여 시험 컬렉션(figindex_test_review)을 생성합니다.
- 팀원 및 팀장이 실제 서비스 데이터를 오염시키지 않고 안전하게 검수 탭 단축키(A 승인 / R 반려)를
  테스트할 수 있도록 돕습니다.

사용법:
    python scripts/create_test_review_collection.py
    python scripts/create_test_review_collection.py --target figindex_test_review --limit 10
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "figindex"))

try:
    from shared.schemas import ReviewStatus
except ImportError as e:
    sys.exit(f"shared 모듈을 불러오지 못했습니다: {e}\n'pip install pydantic' 또는 Python 3.12 환경에서 실행해 주세요.")


def make_request(url: str, method: str = "GET", data: dict = None, timeout: float = 30.0) -> dict:
    req_data = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"} if req_data else {}
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[Error] HTTP {method} {url} 실패: {e}", file=sys.stderr)
        raise


PROTECTED_COLLECTIONS = {"figindex_elements", "figindex_elements_v2"}


def validate_target_collection(source_collection: str, target_collection: str):
    """안전 검사: 서비스 컬렉션 보호 및 시험 컬렉션 명명 규칙 검증"""
    if target_collection == source_collection:
        raise ValueError(
            f"[안전 위반] 대상 컬렉션 이름('{target_collection}')이 원본 컬렉션과 같습니다. 서비스 데이터 보호를 위해 즉시 중단합니다."
        )

    if target_collection in PROTECTED_COLLECTIONS:
        raise ValueError(
            f"[안전 위반] 보호된 서비스 컬렉션('{target_collection}')은 대상 컬렉션으로 지정할 수 없습니다."
        )

    target_norm = target_collection.lower().replace("_", "")
    if not (target_collection.startswith("figindex_test") or target_norm.startswith("figindextest")):
        raise ValueError(
            f"[안전 위반] 대상 컬렉션 이름('{target_collection}')은 반드시 'figindex_test'로 시작해야 합니다. (입력값: {target_collection})"
        )


def create_test_collection(
    qdrant_url: str = "http://localhost:6333",
    source_collection: str = "figindex_elements_v2",
    target_collection: str = "figindex_test_review",
    limit: int = 10,
):
    # 안전 검사: 잘못된 대상 컬렉션 지정으로 인한 서비스 컬렉션 삭제 방지
    validate_target_collection(source_collection, target_collection)

    print("=" * 60)
    print("FigIndex 검수 탭 시험 컬렉션 생성기")
    print(f"- 원본 컬렉션 (읽기 전용): {source_collection}")
    print(f"- 생성할 시험 컬렉션     : {target_collection}")
    print(f"- 복사할 검수 대기 항목  : {limit}건")
    print("=" * 60)

    # 1. 원본 컬렉션 설정 조회
    print(f"\n1. 원본 컬렉션({source_collection}) 정보 확인 중...")
    src_info = make_request(f"{qdrant_url}/collections/{source_collection}")
    config_params = src_info.get("result", {}).get("config", {}).get("params", {})
    vectors_config = config_params.get("vectors")
    sparse_config = config_params.get("sparse_vectors")

    if not vectors_config:
        print(f"[Error] 원본 컬렉션 {source_collection}의 벡터 설정을 읽을 수 없습니다.", file=sys.stderr)
        return

    # 2. 기존 시험 컬렉션 삭제 (재생성용)
    try:
        make_request(f"{qdrant_url}/collections/{target_collection}", method="DELETE")
        print(f"기존 시험 컬렉션({target_collection}) 삭제 완료.")
    except Exception:
        pass

    # 3. 새 시험 컬렉션 생성
    print(f"\n2. 시험 컬렉션({target_collection}) 생성 중...")
    create_body = {
        "vectors": vectors_config,
        "sparse_vectors": sparse_config,
        "on_disk_payload": True,
    }
    make_request(f"{qdrant_url}/collections/{target_collection}", method="PUT", data=create_body)
    print("시험 컬렉션 생성 완료.")

    # 4. 필수 필드 인덱스 생성
    print("3. 필드 인덱스 생성 중...")
    for field_name in ["review_status", "element_id", "doc_name", "element_type"]:
        try:
            make_request(
                f"{qdrant_url}/collections/{target_collection}/index",
                method="PUT",
                data={"field_name": field_name, "field_schema": "keyword"},
            )
        except Exception as e:
            print(f"인덱스 생성 주의 ({field_name}): {e}")

    # 5. 원본 컬렉션에서 PENDING_REVIEW 데이터 조회
    print(f"\n4. 원본 컬렉션에서 검수 대기({ReviewStatus.PENDING_REVIEW.value}) 데이터 {limit}건 조회 중...")
    scroll_body = {
        "filter": {
            "must": [
                {"key": "review_status", "match": {"value": ReviewStatus.PENDING_REVIEW.value}}
            ]
        },
        "limit": limit,
        "with_payload": True,
        "with_vector": True,
    }
    scroll_res = make_request(
        f"{qdrant_url}/collections/{source_collection}/points/scroll",
        method="POST",
        data=scroll_body,
    )
    points = scroll_res.get("result", {}).get("points", [])
    print(f"조회 성공: {len(points)}건 발견.")

    if not points:
        print("[Warn] 복사할 검수 대기 도표가 없습니다.")
        return

    # 6. 시험 컬렉션에 포인트 적재
    print(f"\n5. 시험 컬렉션({target_collection})에 데이터 복사 중...")
    upsert_body = {"points": points}
    make_request(f"{qdrant_url}/collections/{target_collection}/points", method="PUT", data=upsert_body)
    print("데이터 전송 완료! Qdrant 색인 반영 대기 중...")
    time.sleep(2.0)

    # 7. 검증
    test_info = make_request(f"{qdrant_url}/collections/{target_collection}")
    pts_count = test_info.get("result", {}).get("points_count", 0)
    print("\n" + "=" * 60)
    print(f"✅ 시험 컬렉션 '{target_collection}' 준비 완료 (총 {pts_count}건 적재)")
    print("=" * 60)
    print("\n[안내] 검수 탭 단축키 테스트 방법:")
    print(f"1. .env 또는 docker-compose에서 QDRANT_COLLECTION={target_collection} 설정")
    print("2. 브라우저(http://localhost:3000) 검수 탭에서 단축키(A 승인, R 반려) 테스트")
    print("3. ReviewLog에 검수 기록이 정상 적재되는지 확인")


def main():
    parser = argparse.ArgumentParser(description="FigIndex 검수 탭 시험 컬렉션 생성 도구")
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"), help="Qdrant 주소")
    parser.add_argument("--source", default=os.getenv("QDRANT_COLLECTION", "figindex_elements_v2"), help="읽어올 원본 컬렉션")
    parser.add_argument("--target", default="figindex_test_review", help="생성할 시험 컬렉션 이름")
    parser.add_argument("--limit", type=int, default=10, help="복사할 검수 대기 도표 건수")
    args = parser.parse_args()

    create_test_collection(
        qdrant_url=args.qdrant_url,
        source_collection=args.source,
        target_collection=args.target,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
