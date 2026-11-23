export interface TableData {
  columns: string[];
  rows: Record<string, any>[];
  unit?: string;
  unit_by_row?: Record<string, string>;
  unit_by_column?: Record<string, string>;
  period_labels?: string[];
}

export interface ConfidenceSignals {
  layout?: number;
  ocr?: number;
  clip?: number;
  text_match?: number;
}

export interface VisualElement {
  element_id: string;
  doc_id?: string;
  doc_name: string;
  page_number: number;
  bbox: number[];
  element_type: "TABLE" | "CHART" | "DIAGRAM";
  image_path: string;
  caption: string;
  summary?: string;
  table_data?: TableData;
  hashtags?: string[];
  confidence_score: number;
  signals?: ConfidenceSignals;
  review_status: string;
  doc_title?: string;
  doc_type: string;
  domain?: string;
  source_org?: string;
  authors?: string[];
  publish_date?: string;
  collection_id?: string;
  pipeline_version?: string;
  model_name?: string;
}

export interface HealthStatus {
  status: string;
  service: string;
  qdrant_url: string;
  qdrant_connected: boolean;
  collection_name: string;
  collection_exists: boolean;
  total_elements?: number;
  error?: string;
}

export interface FilterOptions {
  doc_types: string[];
  source_orgs: Record<string, string[]>;
  targets: Record<string, string[]>;
  publish_dates: string[];
  element_types: string[];
}

export const DOC_STATUS = {
  UPLOADED: "UPLOADED",
  PROCESSING: "PROCESSING",
  COMPLETED: "COMPLETED",
  FAILED: "FAILED",
  DUPLICATE: "DUPLICATE",
} as const;

export type DocStatus = (typeof DOC_STATUS)[keyof typeof DOC_STATUS];

export interface Document {
  doc_id: string;
  batch_id?: string | null;
  doc_hash: string;
  doc_name: string;
  doc_title?: string | null;
  doc_type?: string | null;
  domain?: string | null;
  source_org?: string | null;
  authors: string[];
  publish_date?: string | null;
  page_count?: number | null;
  collection_id?: string | null;
  doc_status: DocStatus;
  doc_error?: string | null;
  created_at: string;
  extra_metadata: Record<string, unknown>;
}


// ── 문서 간 비교 (/api/compare) ─────────────────────────────
// 백엔드 shared/schemas.py의 PeriodBasis·ComparisonCell·ComparisonResult와 같은 모양이다.

export const PERIOD_BASIS = {
  ACTUAL: "ACTUAL",
  ESTIMATE: "ESTIMATE",
  PRELIM: "PRELIM",
} as const;
export type PeriodBasis = (typeof PERIOD_BASIS)[keyof typeof PERIOD_BASIS];

/** 기간 성격 화면 표기 (원문 접미사 A·E·P, docs/glossary.md 14절) */
export const PERIOD_BASIS_LABELS: Record<PeriodBasis, string> = {
  ACTUAL: "실적",
  ESTIMATE: "추정",
  PRELIM: "잠정",
};

export interface ComparisonCell {
  element_id: string;
  doc_id: string;
  doc_name: string;
  source_org?: string | null;
  publish_date?: string | null;
  page_number: number;
  metric_name: string;
  period_key: string;
  period_basis?: PeriodBasis | null;
  raw_row_label: string;
  raw_column: string;
  raw_value: string | number | null;
  raw_unit?: string | null;
  value?: number | null;
  unit?: string | null;
}

export interface ComparisonResult {
  target: string;
  metric_name: string;
  unit?: string | null;
  period_keys: string[];
  cells: ComparisonCell[];
}

/** GET /api/compare/metrics 응답: 지표명 → 그 지표를 가진 문서 수 */
export interface CompareMetricsResponse {
  target: string;
  metrics: Record<string, number>;
}

/** /api/compare의 unit 쿼리에 넣을 수 있는 원화 단위 (shared/normalize.py KRW_SCALE) */
export const COMPARE_KRW_UNITS = ["원", "천원", "백만원", "억원", "십억원", "조원"] as const;

/** GET /api/compare/company 응답의 문서 1건 (backend main.py MatchedDocComparison, 종목·지표 매칭 엔진) */
export interface MatchedDocComparison {
  doc_name: string;
  source_org?: string | null;
  publish_date?: string | null;
  matched: boolean;
  element_id?: string | null;
  page_number?: number | null;
  caption?: string | null;
  match_score: number;
  second_candidate_element_id?: string | null;
  table_data?: TableData | null;
  match_status: string;
  match_rule?: string | null;
}

/** 문서들의 같은 행을 맞춘 1줄 (AlignedComparisonRow). values: doc_name → {열 이름: 값} */
export interface AlignedComparisonRow {
  row_label: string;
  raw_labels: Record<string, string>;
  values: Record<string, Record<string, unknown>>;
}

/** GET /api/compare/company 응답 (CompareApiResponse) */
export interface CompanyCompareResponse {
  company: string;
  metric: string;
  documents: MatchedDocComparison[];
  aligned_rows: AlignedComparisonRow[];
}
