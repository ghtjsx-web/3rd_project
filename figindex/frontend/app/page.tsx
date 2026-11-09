"use client";

import { useEffect, useState } from "react";

interface HealthStatus {
  status: string;
  service: string;
  qdrant_url: string;
  qdrant_connected: boolean;
  collection_name: string;
  collection_exists: boolean;
  error?: string;
}

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

export default function Home() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [elements, setElements] = useState<VisualElement[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

  useEffect(() => {
    async function fetchData() {
      try {
        setLoading(true);
        // 1. Health check
        const healthRes = await fetch(`${backendUrl}/health`);
        if (!healthRes.ok) throw new Error("Backend health check failed");
        const healthData = await healthRes.json();
        setHealth(healthData);

        // 2. Mock elements
        const elementsRes = await fetch(`${backendUrl}/api/elements`);
        if (!elementsRes.ok) throw new Error("Failed to fetch mock elements");
        const elementsData = await elementsRes.json();
        setElements(elementsData);
      } catch (err: any) {
        console.error("Fetch error:", err);
        setError(err.message || "Failed to connect to backend");
      } finally {
        setLoading(false);
      }
    }

    fetchData();
  }, [backendUrl]);

  return (
    <main className="max-w-6xl mx-auto px-4 py-8">
      {/* Header */}
      <header className="mb-8 border-b pb-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-indigo-600 text-white font-bold flex items-center justify-center text-xl shadow-md">
              F
            </div>
            <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">
              FigIndex
            </h1>
          </div>
          <p className="text-slate-500 mt-1">
            PDF 문서 도표·차트 자동 분류 및 멀티모달 색인 시스템 (MVP Dev Environment)
          </p>
        </div>

        {/* Backend & Qdrant Connection Status Banner */}
        <div className="flex flex-wrap items-center gap-2 text-sm bg-white p-3 rounded-xl shadow-sm border">
          <div className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
            Frontend: OK (Port 3000)
          </div>

          <div
            className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border ${
              health?.status === "ok"
                ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                : "bg-rose-50 text-rose-700 border-rose-200"
            }`}
          >
            <span
              className={`w-2 h-2 rounded-full ${
                health?.status === "ok" ? "bg-emerald-500" : "bg-rose-500"
              }`}
            ></span>
            Backend: {health?.status === "ok" ? "Connected (Port 8000)" : "Disconnected"}
          </div>

          <div
            className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border ${
              health?.qdrant_connected
                ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                : "bg-amber-50 text-amber-700 border-amber-200"
            }`}
          >
            <span
              className={`w-2 h-2 rounded-full ${
                health?.qdrant_connected ? "bg-emerald-500" : "bg-amber-500"
              }`}
            ></span>
            Qdrant: {health?.qdrant_connected ? "Connected (Port 6333)" : "Waiting..."}
          </div>

          {health?.collection_name && (
            <div
              className={`flex items-center gap-1 px-3 py-1 rounded-full text-xs font-semibold border ${
                health.collection_exists
                  ? "bg-blue-50 text-blue-700 border-blue-200"
                  : "bg-slate-100 text-slate-600 border-slate-300"
              }`}
            >
              Collection: {health.collection_name} (
              {health.collection_exists ? "Exists" : "Not yet initialized"})
            </div>
          )}
        </div>
      </header>

      {/* Error Notice */}
      {error && (
        <div className="mb-6 p-4 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-sm">
          <p className="font-bold">백엔드 연결 대기 중:</p>
          <p>{error} (백엔드 컨테이너 실행 상태를 확인해 주세요: {backendUrl})</p>
        </div>
      )}

      {/* Mock Elements Gallery Section */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-slate-800 flex items-center gap-2">
            <span>목업 데이터 카드 갤러리</span>
            <span className="text-xs px-2.5 py-0.5 rounded-full bg-indigo-100 text-indigo-700 font-semibold">
              {elements.length}개 로드됨 (GET /api/elements)
            </span>
          </h2>
          <span className="text-xs text-slate-400">
            shared/schemas.py Pydantic 모델 기준
          </span>
        </div>

        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="h-64 bg-slate-200 rounded-2xl animate-pulse"></div>
            <div className="h-64 bg-slate-200 rounded-2xl animate-pulse"></div>
          </div>
        ) : elements.length === 0 ? (
          <div className="text-center py-12 bg-white rounded-2xl border border-dashed text-slate-400">
            데이터가 없습니다.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {elements.map((elem) => (
              <div
                key={elem.element_id}
                className="bg-white rounded-2xl border border-slate-200 overflow-hidden shadow-sm hover:shadow-md transition-shadow flex flex-col justify-between"
              >
                <div>
                  {/* Card Header */}
                  <div className="p-5 border-b border-slate-100 bg-slate-50/50 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span
                        className={`text-xs font-bold px-2.5 py-1 rounded-md tracking-wide ${
                          elem.element_type === "TABLE"
                            ? "bg-blue-100 text-blue-700 border border-blue-200"
                            : elem.element_type === "CHART"
                            ? "bg-purple-100 text-purple-700 border border-purple-200"
                            : "bg-emerald-100 text-emerald-700 border border-emerald-200"
                        }`}
                      >
                        {elem.element_type}
                      </span>
                      <span className="text-xs font-medium text-slate-500">
                        p.{elem.page_number}
                      </span>
                    </div>

                    <div className="flex items-center gap-1.5">
                      <span className="text-xs text-slate-400">확신도:</span>
                      <span className="text-xs font-bold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                        {(elem.confidence_score * 100).toFixed(0)}%
                      </span>
                    </div>
                  </div>

                  {/* Card Content */}
                  <div className="p-5">
                    <h3 className="font-bold text-lg text-slate-900 mb-2 leading-snug">
                      {elem.title_or_caption}
                    </h3>
                    <p className="text-sm text-slate-600 mb-4 leading-relaxed">
                      {elem.summary}
                    </p>

                    {/* Table Preview if Structured Data is Present */}
                    {elem.structured_data && (
                      <div className="mb-4 overflow-x-auto rounded-lg border border-slate-200 bg-slate-50 text-xs">
                        <table className="w-full text-left">
                          <thead className="bg-slate-100 text-slate-700 border-b border-slate-200 font-semibold">
                            <tr>
                              {elem.structured_data.columns.map((col, idx) => (
                                <th key={idx} className="p-2">
                                  {col}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {elem.structured_data.rows.map((row, rIdx) => (
                              <tr
                                key={rIdx}
                                className="border-b border-slate-200/60 last:border-none"
                              >
                                {elem.structured_data!.columns.map((col, cIdx) => (
                                  <td key={cIdx} className="p-2 text-slate-600">
                                    {row[col] ?? "-"}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {/* Hashtags */}
                    <div className="flex flex-wrap gap-1.5 mb-4">
                      {elem.hashtags.map((tag, tIdx) => (
                        <span
                          key={tIdx}
                          className="text-xs px-2 py-0.5 bg-slate-100 text-slate-600 rounded-md"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Card Footer */}
                <div className="p-4 bg-slate-50 border-t border-slate-100 text-xs text-slate-500 flex items-center justify-between">
                  <span className="truncate max-w-[280px]" title={elem.doc_title}>
                    출처: {elem.source_org} | {elem.doc_title}
                  </span>
                  <button className="text-indigo-600 hover:text-indigo-800 font-semibold flex items-center gap-1">
                    원문 이동 &rarr;
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
