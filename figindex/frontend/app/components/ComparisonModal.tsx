"use client";

import { useEffect, useState } from "react";
import { formatSourceTarget, getElementSource } from "../lib/docTypeLabels";

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

interface ComparisonModalProps {
  isOpen: boolean;
  onClose: () => void;
  elements: VisualElement[];
  backendUrl: string;
}

export default function ComparisonModal({
  isOpen,
  onClose,
  elements,
  backendUrl,
}: ComparisonModalProps) {
  // Close on ESC key
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    if (isOpen) {
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen || elements.length !== 2) return null;

  const [elemA, elemB] = elements;

  // Align table rows by matching group/indicator keys across both tables
  const tableA = elemA.structured_data;
  const tableB = elemB.structured_data;

  // Identify first column key for each table (usually the indicator name, e.g., '구분', '항목', '(십억원)')
  const colKeyA = tableA?.columns?.[0] || "";
  const colKeyB = tableB?.columns?.[0] || "";

  // Helper to extract row label
  const getRowLabel = (row: Record<string, any>, colKey: string) => {
    return String(row[colKey] || "").trim();
  };

  // Build aligned row list by indicator name
  const rowsA = tableA?.rows || [];
  const rowsB = tableB?.rows || [];

  const rowMapA = new Map<string, Record<string, any>>();
  rowsA.forEach((r) => {
    const label = getRowLabel(r, colKeyA);
    if (label) rowMapA.set(label, r);
  });

  const rowMapB = new Map<string, Record<string, any>>();
  rowsB.forEach((r) => {
    const label = getRowLabel(r, colKeyB);
    if (label) rowMapB.set(label, r);
  });

  // Combine unique row labels, preserving Table A order then appending Table B unique labels
  const allLabels: string[] = [];
  rowsA.forEach((r) => {
    const label = getRowLabel(r, colKeyA);
    if (label && !allLabels.includes(label)) allLabels.push(label);
  });
  rowsB.forEach((r) => {
    const label = getRowLabel(r, colKeyB);
    if (label && !allLabels.includes(label)) allLabels.push(label);
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="bg-white rounded-3xl shadow-2xl border border-slate-200 w-full max-w-6xl max-h-[92vh] flex flex-col overflow-hidden my-auto animate-in fade-in zoom-in-95 duration-200">
        {/* Modal Header */}
        <div className="p-5 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-indigo-600 text-white font-bold flex items-center justify-center text-sm shadow">
              VS
            </div>
            <div>
              <h2 className="text-lg font-bold text-slate-900">
                도표 1:1 비교 분석실
              </h2>
              <p className="text-xs text-slate-500">
                선택하신 2개 도표의 크롭 원본 및 동일 항목(지표 행) 기준 정렬 비교
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="w-8 h-8 rounded-full bg-slate-200 hover:bg-slate-300 text-slate-600 flex items-center justify-center transition-colors text-sm font-bold"
            title="닫기 (ESC)"
          >
            ✕
          </button>
        </div>

        {/* Modal Body - Scrollable */}
        <div className="p-6 overflow-y-auto space-y-6">
          {/* Top Section: Visual Comparison (Crops, Titles, Summaries) */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Left Item (A) */}
            <div className="bg-slate-50/70 p-4 rounded-2xl border border-slate-200 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-2 gap-2">
                  <span className="text-xs font-bold text-indigo-700 bg-indigo-50 px-2.5 py-0.5 rounded border border-indigo-200 truncate">
                    [도표 1] {formatSourceTarget(elemA) || elemA.title_or_caption}
                  </span>
                  <span className="text-xs text-slate-400 shrink-0">
                    {[getElementSource(elemA), elemA.publish_date].filter(Boolean).join(" | ")}
                  </span>
                </div>

                <div className="bg-white h-44 rounded-xl border border-slate-200 overflow-hidden flex items-center justify-center p-2 mb-3 shadow-inner">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={`${backendUrl}${elemA.image_path}`}
                    alt={elemA.title_or_caption}
                    className="max-h-full max-w-full object-contain"
                  />
                </div>

                <h3 className="font-bold text-sm text-slate-900 mb-1 leading-snug">
                  {elemA.title_or_caption}
                </h3>
                <p className="text-xs text-slate-600 line-clamp-3 leading-relaxed">
                  {elemA.summary}
                </p>
              </div>
            </div>

            {/* Right Item (B) */}
            <div className="bg-slate-50/70 p-4 rounded-2xl border border-slate-200 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-2 gap-2">
                  <span className="text-xs font-bold text-purple-700 bg-purple-50 px-2.5 py-0.5 rounded border border-purple-200 truncate">
                    [도표 2] {formatSourceTarget(elemB) || elemB.title_or_caption}
                  </span>
                  <span className="text-xs text-slate-400 shrink-0">
                    {[getElementSource(elemB), elemB.publish_date].filter(Boolean).join(" | ")}
                  </span>
                </div>

                <div className="bg-white h-44 rounded-xl border border-slate-200 overflow-hidden flex items-center justify-center p-2 mb-3 shadow-inner">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={`${backendUrl}${elemB.image_path}`}
                    alt={elemB.title_or_caption}
                    className="max-h-full max-w-full object-contain"
                  />
                </div>

                <h3 className="font-bold text-sm text-slate-900 mb-1 leading-snug">
                  {elemB.title_or_caption}
                </h3>
                <p className="text-xs text-slate-600 line-clamp-3 leading-relaxed">
                  {elemB.summary}
                </p>
              </div>
            </div>
          </div>

          {/* Bottom Section: Aligned Row-by-Row Table Comparison */}
          {(tableA || tableB) && (
            <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm">
              <div className="flex items-center justify-between mb-4 pb-3 border-b border-slate-100">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
                  <h4 className="font-bold text-sm text-slate-800">
                    항목(Group) 줄 맞춤 수치 대조표
                  </h4>
                </div>
                <div className="flex gap-4 text-xs text-slate-500">
                  <span>도표 1 단위: <strong>{tableA?.unit || "기본"}</strong></span>
                  <span>도표 2 단위: <strong>{tableB?.unit || "기본"}</strong></span>
                </div>
              </div>

              {allLabels.length === 0 ? (
                <p className="text-xs text-slate-400 text-center py-6">
                  비교 가능한 구조화 표 데이터가 없습니다.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs border-collapse">
                    <thead>
                      <tr className="bg-slate-100 text-slate-700 font-semibold border-b">
                        <th className="p-2.5 text-left w-36 bg-slate-200/70 border-r border-slate-200 sticky left-0 z-10">
                          기준 지표명
                        </th>
                        {/* Table A Header Columns */}
                        <th
                          colSpan={Math.max(1, (tableA?.columns?.length || 1) - 1)}
                          className="p-2 text-center bg-indigo-50 text-indigo-800 border-r border-slate-200 font-bold"
                        >
                          [도표 1] {formatSourceTarget(elemA) || elemA.title_or_caption.slice(0, 15)}
                        </th>
                        {/* Table B Header Columns */}
                        <th
                          colSpan={Math.max(1, (tableB?.columns?.length || 1) - 1)}
                          className="p-2 text-center bg-purple-50 text-purple-800 font-bold"
                        >
                          [도표 2] {formatSourceTarget(elemB) || elemB.title_or_caption.slice(0, 15)}
                        </th>
                      </tr>
                      {/* Sub-header for column periods */}
                      <tr className="bg-slate-50 text-[11px] text-slate-600 border-b">
                        <th className="p-2 text-left bg-slate-100 border-r border-slate-200 sticky left-0 z-10">
                          -
                        </th>
                        {/* A columns (except colKeyA) */}
                        {tableA?.columns?.slice(1).map((col, idx) => (
                          <th key={`a-col-${idx}`} className="p-2 text-center whitespace-nowrap bg-indigo-50/40">
                            {col}
                          </th>
                        ))}
                        {(!tableA || tableA.columns.length <= 1) && (
                          <th className="p-2 text-center text-slate-400">-</th>
                        )}

                        {/* B columns (except colKeyB) */}
                        {tableB?.columns?.slice(1).map((col, idx) => (
                          <th key={`b-col-${idx}`} className="p-2 text-center whitespace-nowrap bg-purple-50/40 border-l border-slate-100">
                            {col}
                          </th>
                        ))}
                        {(!tableB || tableB.columns.length <= 1) && (
                          <th className="p-2 text-center text-slate-400">-</th>
                        )}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {allLabels.map((label, rIdx) => {
                        const rowA = rowMapA.get(label);
                        const rowB = rowMapB.get(label);

                        return (
                          <tr key={rIdx} className="hover:bg-slate-50 transition-colors">
                            {/* Aligned Row Indicator Name */}
                            <td className="p-2.5 font-semibold text-slate-800 bg-slate-100/70 border-r border-slate-200 sticky left-0 z-10 whitespace-nowrap">
                              {label}
                            </td>

                            {/* Table A Row Values */}
                            {tableA?.columns?.slice(1).map((col, cIdx) => (
                              <td
                                key={`val-a-${cIdx}`}
                                className="p-2 text-center font-mono text-slate-700 whitespace-nowrap"
                              >
                                {rowA ? rowA[col] ?? "-" : <span className="text-slate-300">-</span>}
                              </td>
                            ))}
                            {(!tableA || tableA.columns.length <= 1) && (
                              <td className="p-2 text-center text-slate-300">-</td>
                            )}

                            {/* Table B Row Values */}
                            {tableB?.columns?.slice(1).map((col, cIdx) => (
                              <td
                                key={`val-b-${cIdx}`}
                                className={`p-2 text-center font-mono text-slate-700 whitespace-nowrap ${
                                  cIdx === 0 ? "border-l border-slate-100" : ""
                                }`}
                              >
                                {rowB ? rowB[col] ?? "-" : <span className="text-slate-300">-</span>}
                              </td>
                            ))}
                            {(!tableB || tableB.columns.length <= 1) && (
                              <td className="p-2 text-center text-slate-300">-</td>
                            )}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="p-4 bg-slate-50 border-t border-slate-200 flex items-center justify-between text-xs text-slate-500">
          <span>* 동일 지표 행은 자동으로 한 줄에 정렬되며, 한쪽 도표에만 존재하는 항목은 빈 칸(-)으로 표시됩니다.</span>
          <button
            onClick={onClose}
            className="px-5 py-2 bg-slate-800 hover:bg-slate-900 text-white font-medium rounded-xl transition-colors shadow-sm"
          >
            확인 완료
          </button>
        </div>
      </div>
    </div>
  );
}

