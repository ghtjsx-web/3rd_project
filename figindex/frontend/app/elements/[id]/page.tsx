"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useParams } from "next/navigation";

// Dynamic import for react-pdf viewer to disable SSR
const PdfViewer = dynamic(() => import("../../components/PdfViewer"), {
  ssr: false,
  loading: () => (
    <div className="h-full min-h-[500px] flex items-center justify-center bg-slate-900 rounded-2xl text-slate-400 text-xs">
      <div className="w-5 h-5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mr-2"></div>
      PDF 뷰어 엔진 로딩 중...
    </div>
  ),
});

interface TableStructure {
  columns: string[];
  rows: Record<string, any>[];
  unit?: string;
  period_labels: string[];
}

interface VisualElement {
  element_id: string;
  doc_name: string;
  page_number: number;
  bbox: number[];
  element_type: "TABLE" | "CHART" | "DIAGRAM";
  image_path: string;
  title_or_caption: string;
  summary: string;
  structured_data?: TableStructure;
  hashtags: string[];
  confidence_score: number;
  review_status: string;
  doc_title: string;
  doc_type: string;
  domain?: string;
  source_org?: string;
  authors: string[];
  publish_date?: string;
  entities: string[];
  extra_metadata: Record<string, any>;
}

export default function ElementDetailPage() {
  const params = useParams();
  const elementId = params?.id as string;

  const [element, setElement] = useState<VisualElement | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

  useEffect(() => {
    if (!elementId) return;

    async function fetchElementDetail() {
      try {
        setLoading(true);
        setError(null);
        const res = await fetch(`${backendUrl}/api/elements/${elementId}`);
        if (!res.ok) {
          throw new Error("도표 상세 정보를 불러올 수 없습니다.");
        }
        const data = await res.json();
        setElement(data);
      } catch (err: any) {
        console.error("Fetch error:", err);
        setError(err.message || "데이터 조회 실패");
      } finally {
        setLoading(false);
      }
    }

    fetchElementDetail();
  }, [elementId, backendUrl]);

  if (loading) {
    return (
      <main className="max-w-7xl mx-auto px-4 py-12">
        <div className="flex flex-col items-center justify-center py-20 text-slate-500 text-sm gap-3">
          <div className="w-8 h-8 border-3 border-indigo-600 border-t-transparent rounded-full animate-spin"></div>
          <p>도표 상세 정보 및 원문 리포트를 불러오는 중입니다...</p>
        </div>
      </main>
    );
  }

  if (error || !element) {
    return (
      <main className="max-w-7xl mx-auto px-4 py-12">
        <div className="p-6 bg-rose-50 border border-rose-200 rounded-2xl text-rose-800 text-center">
          <h2 className="text-lg font-bold mb-2">오류가 발생했습니다</h2>
          <p className="text-sm mb-4">{error || "해당 도표를 찾을 수 없습니다."}</p>
          <Link
            href="/"
            className="inline-block px-4 py-2 bg-rose-600 text-white rounded-lg text-xs font-semibold hover:bg-rose-700"
          >
            ← 갤러리로 돌아가기
          </Link>
        </div>
      </main>
    );
  }

  const pdfFileUrl = `${backendUrl}/api/files/pdf/${encodeURIComponent(element.doc_name)}`;

  return (
    <main className="max-w-7xl mx-auto px-4 py-6">
      {/* Top Navigation */}
      <div className="mb-6 flex items-center justify-between">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-600 hover:text-indigo-600 transition-colors bg-white px-3 py-1.5 rounded-lg border shadow-sm"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          갤러리 목록으로 돌아가기
        </Link>

        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-400">출처:</span>
          <span className="font-semibold text-slate-700">
            {element.source_org || "증권사"} | {element.doc_title}
          </span>
          <span className="text-slate-400">({element.publish_date})</span>
        </div>
      </div>

      {/* Main 2-Column Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
        {/* Left Column: Cropped Image & AI Restored Table */}
        <div className="flex flex-col gap-6">
          {/* Section 1: Cropped Original Image */}
          <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span
                  className={`text-xs font-bold px-2.5 py-1 rounded-md ${
                    element.element_type === "TABLE"
                      ? "bg-blue-600 text-white"
                      : element.element_type === "CHART"
                      ? "bg-purple-600 text-white"
                      : "bg-emerald-600 text-white"
                  }`}
                >
                  {element.element_type}
                </span>
                <span className="text-xs font-medium text-slate-500">
                  원문 {element.page_number}페이지에서 추출
                </span>
              </div>

              <div className="flex items-center gap-2">
                <span
                  className={`text-xs font-bold px-2 py-0.5 rounded border ${
                    element.review_status === "APPROVED"
                      ? "bg-emerald-50 text-emerald-700 border-emerald-300"
                      : "bg-amber-50 text-amber-700 border-amber-300"
                  }`}
                >
                  확신도 {(element.confidence_score * 100).toFixed(0)}% ({element.review_status})
                </span>
                <a
                  href={`${backendUrl}${element.image_path}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 px-2.5 py-1 rounded transition-colors font-medium flex items-center gap-1"
                >
                  원본 이미지
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                  </svg>
                </a>
              </div>
            </div>

            {/* Cropped Image Box */}
            <div className="bg-slate-50 rounded-xl border border-slate-100 p-3 flex items-center justify-center max-h-[380px] overflow-hidden">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`${backendUrl}${element.image_path}`}
                alt={element.title_or_caption}
                className="max-h-[350px] max-w-full object-contain rounded"
              />
            </div>

            <h1 className="text-xl font-bold text-slate-900 mt-4 mb-2 leading-snug">
              {element.title_or_caption}
            </h1>
            <p className="text-xs text-slate-600 leading-relaxed bg-slate-50 p-3 rounded-lg border border-slate-100 mb-3">
              {element.summary}
            </p>

            {/* Hashtags */}
            <div className="flex flex-wrap gap-1.5">
              {element.hashtags.map((tag, idx) => (
                <span
                  key={idx}
                  className="text-xs px-2.5 py-1 bg-indigo-50 text-indigo-700 rounded-md font-medium"
                >
                  {tag}
                </span>
              ))}
            </div>
          </div>

          {/* Section 2: AI Restored Structured Table */}
          {element.structured_data && element.structured_data.columns && (
            <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm">
              <div className="flex items-center justify-between mb-3 border-b pb-3">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-emerald-500"></div>
                  <h3 className="font-bold text-sm text-slate-800">
                    Gemini AI 복원 구조화 데이터 (JSON)
                  </h3>
                </div>
                {element.structured_data.unit && (
                  <span className="text-xs font-semibold text-slate-500 bg-slate-100 px-2 py-0.5 rounded">
                    단위: {element.structured_data.unit}
                  </span>
                )}
              </div>

              <div className="overflow-x-auto rounded-lg border border-slate-200">
                <table className="w-full text-left border-collapse text-xs">
                  <thead className="bg-slate-100 text-slate-700 font-semibold border-b">
                    <tr>
                      {element.structured_data.columns.map((col, idx) => (
                        <th key={idx} className="p-2.5 whitespace-nowrap bg-slate-100">
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {element.structured_data.rows.map((row, rIdx) => (
                      <tr key={rIdx} className="hover:bg-slate-50/80 transition-colors">
                        {element.structured_data!.columns.map((col, cIdx) => (
                          <td
                            key={cIdx}
                            className={`p-2.5 text-slate-700 whitespace-nowrap ${
                              cIdx === 0 ? "font-semibold bg-slate-50/50" : "font-mono"
                            }`}
                          >
                            {row[col] ?? "-"}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        {/* Right Column: Original PDF Page Viewer (react-pdf) */}
        <div className="lg:sticky lg:top-6 h-[820px] flex flex-col">
          <PdfViewer pdfUrl={pdfFileUrl} initialPage={element.page_number} />
        </div>
      </div>
    </main>
  );
}

