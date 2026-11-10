import os
import re
import math
import hashlib
from datetime import date
from pathlib import Path
from typing import List, Dict, Any, Optional

import fitz  # PyMuPDF
from kiwipiepy import Kiwi
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

try:
    from shared.schemas import VisualElementSchema, ElementType, ReviewStatus
except ImportError:
    from app.schemas import VisualElementSchema, ElementType, ReviewStatus

try:
    from cropper import PDFCropper
    from extractor import MultimodalExtractor
except ImportError:
    from app.pipeline.cropper import PDFCropper
    from app.pipeline.extractor import MultimodalExtractor


class ExtractionPipelineOrchestrator:
    def __init__(self):
        self.cropper = PDFCropper()
        self.extractor = MultimodalExtractor()
        self.kiwi = Kiwi()

        self.qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
        self.collection_name = os.getenv("QDRANT_COLLECTION", "figindex_elements")
        self.qdrant_client = QdrantClient(url=self.qdrant_url, timeout=10.0)

        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        self.embedding_dim = 1536
        self.openai_client = OpenAI(api_key=self.openai_key) if self.openai_key else None

    def is_document_already_indexed(self, doc_name: str) -> bool:
        """Check if any elements from this PDF document already exist in Qdrant."""
        try:
            results, _ = self.qdrant_client.scroll(
                collection_name=self.collection_name,
                scroll_filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="doc_name",
                            match=qmodels.MatchValue(value=doc_name)
                        )
                    ]
                ),
                limit=1,
                with_payload=False,
                with_vectors=False
            )
            return len(results) > 0
        except Exception:
            return False

    def extract_document_metadata(self, doc: fitz.Document, doc_name: str) -> Dict[str, Any]:
        """
        Extract document-level metadata once (cover page text layer + file name parsing) (Item 3).
        Inherited by all elements in this report.
        """
        cover_text = doc[0].get_text("text") if len(doc) > 0 else ""

        # 1. Company name from filename (e.g., 'BGF리테일1106.pdf', 'CJ ENM 1106.pdf', '스튜디오 드래곤 1106.pdf')
        name_without_ext = re.sub(r"\.pdf$", "", doc_name, flags=re.IGNORECASE).strip()
        # Remove trailing date pattern like 1106, 1109, 1105
        company_candidate = re.sub(r"[\s_-]*\d{4}$", "", name_without_ext).strip()
        company = company_candidate if company_candidate else "금융분석"

        # 2. Broker name matching
        known_brokers = [
            "IBK투자증권", "미래에셋증권", "신한투자증권", "키움증권", "하나증권",
            "대신증권", "KB증권", "삼성증권", "NH투자증권", "유안타증권",
            "한국투자증권", "메리츠증권", "교보증권", "현대차증권", "한화투자증권",
            "SK증권", "유진투자증권", "DB금융투자", "iM증권", "다올투자증권"
        ]
        broker = "증권사"
        for b in known_brokers:
            if b in cover_text or b.replace("증권", "") in cover_text:
                broker = b
                break

        # 3. Match 6-digit stock ticker
        ticker = None
        ticker_match = re.search(r"\((\d{6})\)|\b(\d{6})\b", cover_text)
        if ticker_match:
            ticker = ticker_match.group(1) or ticker_match.group(2)

        # 4. Match Analyst name
        analyst = None
        analyst_match = re.search(r"([가-힣]{2,4})\s*(?:연구원|애널리스트|위원|RA)", cover_text)
        if analyst_match:
            analyst = analyst_match.group(1)

        # 5. Publish Date
        pub_date = date.today()
        date_match = re.search(r"(202[4-6])[\.\-\/](\d{1,2})[\.\-\/](\d{1,2})", cover_text)
        if date_match:
            try:
                y, m, d = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
                pub_date = date(y, m, d)
            except Exception:
                pub_date = date.today()
        else:
            # Fallback from filename date suffix (e.g. 1106 -> 2025-11-06)
            fn_date_match = re.search(r"(\d{2})(\d{2})$", name_without_ext)
            if fn_date_match:
                try:
                    m, d = int(fn_date_match.group(1)), int(fn_date_match.group(2))
                    pub_date = date(2025, m, d)
                except Exception:
                    pub_date = date.today()

        # 6. Document Title
        lines = [line.strip() for line in cover_text.split("\n") if len(line.strip()) > 5]
        doc_title = f"{company} 리서치 리포트"
        for line in lines[:5]:
            if company in line or "Review" in line or "전망" in line or "실적" in line:
                doc_title = line
                break

        # 7. Industry guess
        industry = "산업/기업분석"
        for ind in ["반도체", "2차전지", "편의점/유통", "미디어/엔터", "제약/바이오", "에너지", "금융", "통신", "소비재", "화학", "자동차"]:
            if ind in cover_text:
                industry = ind
                break

        return {
            "company": company,
            "ticker": ticker,
            "broker": broker,
            "analyst": analyst,
            "publish_date": pub_date,
            "doc_title": doc_title,
            "industry": industry
        }

    def tokenize_korean_bm25(self, text: str) -> Dict[int, float]:
        """Tokenize text with Kiwi and return sparse hash frequencies."""
        tokens = self.kiwi.tokenize(text)
        token_counts: Dict[int, float] = {}
        valid_tags = {"NNG", "NNP", "NR", "VV", "VA", "SL"}
        for t in tokens:
            if t.tag in valid_tags and len(t.form) > 1:
                token_hash = abs(hash(t.form)) % (2**31 - 1)
                token_counts[token_hash] = token_counts.get(token_hash, 0.0) + 1.0
        return token_counts

    def get_dense_embedding(self, text: str) -> List[float]:
        """Get 1536 dim dense embedding using OpenAI text-embedding-3-small."""
        if self.openai_client:
            try:
                resp = self.openai_client.embeddings.create(
                    input=text[:4000],
                    model=self.embedding_model
                )
                return resp.data[0].embedding
            except Exception as e:
                print(f"  [Warn] OpenAI embedding failed: {e}. Falling back to deterministic embedding.")

        # Deterministic fallback vector if OpenAI key is not provided or fails
        seed = int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16)
        vec = []
        for i in range(self.embedding_dim):
            val = math.sin(seed + i)
            vec.append(val)
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def index_element_to_qdrant(self, element: VisualElementSchema):
        """Upsert a single VisualElementSchema into Qdrant collection."""
        text_to_embed = f"{element.title_or_caption} {element.summary} {' '.join(element.hashtags)} {element.doc_title} {element.source_org} {' '.join(element.entities)}"
        dense_vec = self.get_dense_embedding(text_to_embed)
        sparse_tokens = self.tokenize_korean_bm25(text_to_embed)
        sparse_indices = list(sparse_tokens.keys())
        sparse_values = list(sparse_tokens.values())

        payload = element.model_dump(mode="json")
        point_id = abs(hash(element.element_id)) % (2**63 - 1)

        self.qdrant_client.upsert(
            collection_name=self.collection_name,
            points=[
                qmodels.PointStruct(
                    id=point_id,
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

    def process_pdf(self, pdf_path: Path, max_pages: int = 15, max_elements_per_pdf: int = 4) -> List[VisualElementSchema]:
        """
        Process a single PDF document:
        1. Extract document-level metadata
        2. Detect and crop visual elements across pages
        3. Analyze with Gemini Multimodal model
        4. Upsert to Qdrant collection
        """
        doc = fitz.open(str(pdf_path))
        doc_name = pdf_path.name
        total_pages = min(len(doc), max_pages)

        doc_metadata = self.extract_document_metadata(doc, doc_name)
        print(f"  -> Extracted Metadata: 기업={doc_metadata['company']}, 증권사={doc_metadata['broker']}, 발행일={doc_metadata['publish_date']}, 종목={doc_metadata.get('ticker')}")

        indexed_elements: List[VisualElementSchema] = []
        extracted_count = 0

        for p_idx in range(1, total_pages + 1):
            if extracted_count >= max_elements_per_pdf:
                break

            page = doc[p_idx - 1]
            candidates = self.cropper.detect_candidate_boxes(page)
            if not candidates:
                continue

            page_img = self.cropper.render_page(doc, p_idx)

            for cand in candidates:
                if extracted_count >= max_elements_per_pdf:
                    break

                try:
                    crop_info = self.cropper.crop_and_save(
                        doc=doc,
                        doc_path=pdf_path,
                        page_num=p_idx,
                        candidate=cand,
                        page_img=page_img
                    )

                    print(f"    [P.{p_idx}] Cropped {crop_info['hint_type']}: {crop_info['relative_path']}")

                    # Analyze with Gemini Multimodal
                    element = self.extractor.analyze_crop(
                        crop_info=crop_info,
                        doc_name=doc_name,
                        page_number=p_idx,
                        doc_metadata=doc_metadata,
                        detection_score=0.92
                    )

                    print(f"    [AI Analyzed] Type: {element.element_type.value} | Title: {element.title_or_caption[:35]} | Conf: {element.confidence_score*100:.1f}% ({element.review_status.value})")

                    # Upsert to Qdrant
                    self.index_element_to_qdrant(element)
                    indexed_elements.append(element)
                    extracted_count += 1

                except Exception as e:
                    print(f"    [Error] Processing visual element on p.{p_idx}: {e}")

        doc.close()
        return indexed_elements
