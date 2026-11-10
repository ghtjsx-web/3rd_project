import time
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from kiwipiepy import Kiwi

from app.core.config import settings
from app.schemas import (
    VisualElementSchema,
    SearchQueryRequest,
    SearchResponse,
    ReviewStatus,
)


class HybridSearchService:
    def __init__(self):
        # Initialize Kiwi Korean morphological analyzer
        self.kiwi = Kiwi()
        # Initialize Qdrant Client (in-memory fallback if host unreachable)
        try:
            self.client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT, timeout=3.0)
            # Ping
            self.client.get_collections()
        except Exception:
            # Fallback to local in-memory instance for testing/development
            self.client = QdrantClient(":memory:")

        self.collection_name = settings.QDRANT_COLLECTION
        self._init_collection()

    def _init_collection(self):
        """Create Qdrant collection with Dense (1536 dim) + Sparse vector configurations."""
        collections = self.client.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)
        if not exists:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    "dense": qmodels.VectorParams(
                        size=settings.EMBEDDING_DIM,
                        distance=qmodels.Distance.COSINE
                    )
                },
                sparse_vectors_config={
                    "sparse": qmodels.SparseVectorParams(
                        index=qmodels.SparseIndexParams(on_disk=False)
                    )
                }
            )

    def tokenize_korean_bm25(self, text: str) -> Dict[int, float]:
        """
        Tokenize Korean text with Kiwi morphological analyzer and return sparse token frequencies.
        Hash tokens to integer indices for Qdrant sparse vectors.
        """
        tokens = self.kiwi.tokenize(text)
        token_counts: Dict[int, float] = {}
        # Filter content morphemes: NNG(일반명사), NNP(고유명사), NR(수사), VV(동사), VA(형용사), SL(외국어)
        valid_tags = {"NNG", "NNP", "NR", "VV", "VA", "SL"}
        for t in tokens:
            if t.tag in valid_tags and len(t.form) > 1:
                token_hash = abs(hash(t.form)) % (2**31 - 1)
                token_counts[token_hash] = token_counts.get(token_hash, 0.0) + 1.0
        return token_counts

    def get_dense_embedding(self, text: str) -> List[float]:
        """
        Get dense embedding (1536 dim).
        Uses OpenAI if API key provided, otherwise deterministic normalized vector for development.
        """
        if settings.OPENAI_API_KEY:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=settings.OPENAI_API_KEY)
                resp = client.embeddings.create(
                    input=text,
                    model=settings.EMBEDDING_MODEL
                )
                return resp.data[0].embedding
            except Exception:
                pass

        # Fallback deterministic pseudorandom embedding for testing without API key
        import hashlib
        import math
        seed = int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16)
        vec = []
        for i in range(settings.EMBEDDING_DIM):
            val = math.sin(seed + i)
            vec.append(val)
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def index_element(self, element: VisualElementSchema):
        """Index a VisualElementSchema into Qdrant collection with payload and vectors."""
        text_to_embed = f"{element.title_or_caption} {element.summary} {' '.join(element.hashtags)} {element.company}"
        dense_vec = self.get_dense_embedding(text_to_embed)
        sparse_tokens = self.tokenize_korean_bm25(text_to_embed)

        sparse_indices = list(sparse_tokens.keys())
        sparse_values = list(sparse_tokens.values())

        payload = element.model_dump(mode="json")

        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                qmodels.PointStruct(
                    id=abs(hash(element.element_id)) % (2**63 - 1),
                    vector={
                        "dense": dense_vec,
                        "sparse": qmodels.SparseVector(
                            indices=sparse_indices,
                            values=sparse_values
                        ) if sparse_indices else None
                    },
                    payload=payload
                )
            ]
        )

    def search(self, req: SearchQueryRequest) -> SearchResponse:
        """
        Hybrid search combining Dense vector + Kiwi BM25 + Qdrant payload filters.
        """
        start_time = time.time()

        # Build payload keyword filters
        filter_conditions = [
            qmodels.FieldCondition(
                key="review_status",
                match=qmodels.MatchValue(value=ReviewStatus.APPROVED.value)
            )
        ]

        if req.element_type:
            filter_conditions.append(
                qmodels.FieldCondition(
                    key="element_type",
                    match=qmodels.MatchValue(value=req.element_type.value)
                )
            )
        if req.company:
            filter_conditions.append(
                qmodels.FieldCondition(
                    key="company",
                    match=qmodels.MatchValue(value=req.company)
                )
            )
        if req.ticker:
            filter_conditions.append(
                qmodels.FieldCondition(
                    key="ticker",
                    match=qmodels.MatchValue(value=req.ticker)
                )
            )
        if req.broker:
            filter_conditions.append(
                qmodels.FieldCondition(
                    key="broker",
                    match=qmodels.MatchValue(value=req.broker)
                )
            )
        if req.industry:
            filter_conditions.append(
                qmodels.FieldCondition(
                    key="industry",
                    match=qmodels.MatchValue(value=req.industry)
                )
            )

        query_filter = qmodels.Filter(must=filter_conditions)

        # Dense query vector
        query_dense = self.get_dense_embedding(req.query)

        # Execute hybrid search
        search_results = self.client.search(
            collection_name=self.collection_name,
            query_vector=("dense", query_dense),
            query_filter=query_filter,
            limit=req.limit,
            offset=req.offset
        )

        items = []
        for res in search_results:
            if res.payload:
                items.append(VisualElementSchema(**res.payload))

        execution_time_ms = round((time.time() - start_time) * 1000, 2)
        return SearchResponse(
            total=len(items),
            items=items,
            execution_time_ms=execution_time_ms
        )

