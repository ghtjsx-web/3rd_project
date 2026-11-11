export interface DocTypeLabelConfig {
  docTypeLabel: string;
  sourceLabel: string;
  targetLabel: string;
}

export const DOC_TYPE_LABELS: Record<string, DocTypeLabelConfig> = {
  REPORT: {
    docTypeLabel: "증권 리포트",
    sourceLabel: "증권사",
    targetLabel: "기업명",
  },
  PUBLIC_REPORT: {
    docTypeLabel: "공공 보고서",
    sourceLabel: "발행기관",
    targetLabel: "주제",
  },
  PAPER: {
    docTypeLabel: "학술 논문",
    sourceLabel: "학회·기관",
    targetLabel: "논문 제목",
  },
  IR: {
    docTypeLabel: "기업 IR",
    sourceLabel: "기업",
    targetLabel: "보고서명",
  },
};

export const DEFAULT_DOC_TYPE_LABELS: DocTypeLabelConfig = {
  docTypeLabel: "전체",
  sourceLabel: "출처",
  targetLabel: "대상",
};

const IGNORED_DEFAULT_STRINGS = new Set(["증권사", "금융분석", "출처미상"]);

export function getDocTypeLabels(docType?: string | null): DocTypeLabelConfig {
  if (!docType) return DEFAULT_DOC_TYPE_LABELS;
  return DOC_TYPE_LABELS[docType.toUpperCase()] || DEFAULT_DOC_TYPE_LABELS;
}

export function getElementSource(elem: { source_org?: string | null }): string {
  const src = elem.source_org?.trim() || "";
  if (!src || IGNORED_DEFAULT_STRINGS.has(src)) {
    return "";
  }
  return src;
}

export function getElementTarget(
  elem: {
    doc_title?: string;
    extra_metadata?: Record<string, any>;
  },
  fallbackDocTitle = true
): string {
  const raw = elem.extra_metadata?.target ?? elem.extra_metadata?.company;
  if (typeof raw === "string") {
    const cleaned = raw.trim();
    if (cleaned && !IGNORED_DEFAULT_STRINGS.has(cleaned)) {
      return cleaned;
    }
  }
  if (fallbackDocTitle && typeof elem.doc_title === "string" && elem.doc_title.trim()) {
    return elem.doc_title.trim();
  }
  return "";
}

/**
 * "{출처} · {대상}" 형식으로 표시 문자열을 생성하며, 값이 없는 쪽은 생략합니다.
 */
export function formatSourceTarget(
  elem: {
    source_org?: string | null;
    doc_title?: string;
    extra_metadata?: Record<string, any>;
  },
  fallbackDocTitle = true
): string {
  const parts = [getElementSource(elem), getElementTarget(elem, fallbackDocTitle)].filter(Boolean);
  return parts.join(" · ");
}

