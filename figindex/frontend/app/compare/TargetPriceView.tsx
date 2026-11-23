"use client";

import { useState } from "react";
import Link from "next/link";
import { CompanyCompareResponse, MatchedDocComparison, TableData } from "../lib/types";

/** 목표주가 행·열 이름 */
const TARGET_PRICE_RE = /목표\s*주가|적정\s*주가|target\s*price/i;
/** 목표주가 자체가 아닌 줄 (상승여력·괴리율·변동률 등) */
const NOT_PRICE_RE = /상승|여력|괴리|변동|대비|%|upside/i;

function isTargetPriceLabel(text: string): boolean {
  return TARGET_PRICE_RE.test(text) && !NOT_PRICE_RE.test(text);
}

interface TargetPriceValue {
  value: number;
  label: string; // 원문 행·열 이름
  unit?: string;
}

function toNumber(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string") {
    const n = Number(v.replace(/,/g, "").replace(/원$/, "").trim());
    return v.trim() !== "" && Number.isFinite(n) ? n : null;
  }
  return null;
}

/** 매칭된 표에서 목표주가 값 찾기: ① 행 라벨이 목표주가인 행의 첫 숫자 ② 열 이름이 목표주가인 열의 첫 숫자 */
export function findTargetPrice(table: TableData | null | undefined): TargetPriceValue | null {
  if (!table || table.columns.length === 0) return null;
  const labelColumn = table.columns[0];
  for (const row of table.rows) {
    const label = String(row[labelColumn] ?? "");
    if (!isTargetPriceLabel(label)) continue;
    for (const column of table.columns.slice(1)) {
      const n = toNumber(row[column]);
      if (n !== null) {
        return { value: n, label: `${label} · ${column}`, unit: table.unit_by_row?.[label] || table.unit || undefined };
      }
    }
  }
  for (const column of table.columns.slice(1)) {
    if (!isTargetPriceLabel(column)) continue;
    for (const row of table.rows) {
      const n = toNumber(row[column]);
      if (n !== null) {
        return { value: n, label: column, unit: table.unit_by_column?.[column] || table.unit || undefined };
      }
    }
  }
  return null;
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined || v === "") return "-";
  if (typeof v === "number") return v.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
  return String(v);
}

interface Props {
  result: CompanyCompareResponse;
  onOpenSource: (doc: MatchedDocComparison) => void;
}

/** 목표주가 비교 (종목·지표 매칭 엔진 /api/compare/company, metric=TARGET_PRICE) */
export default function TargetPriceView({ result, onOpenSource }: Props) {
  const [showTables, setShowTables] = useState<boolean>(false);
  const matched = result.documents.filter((d) => d.matched && d.table_data);
  const prices = matched
    .map((d) => findTargetPrice(d.table_data))
    .filter((p): p is TargetPriceValue => p !== null)
    .map((p) => p.value);
  const gap = prices.length >= 2 ? Math.max(...prices) - Math.min(...prices) : null;

  if (result.documents.length === 0) {
    return (
      <section className="bg-white border border-slate-200 rounded-2xl shadow-sm mb-6 p-8 text-center text-sm text-slate-500">
        이 종목은 같은 종목 비교 그룹(compare_pairs.json)에 없어 목표주가 표를 맞출 수 없습니다.
      </section>
    );
  }

  return (
    <section className="bg-white border border-slate-200 rounded-2xl shadow-sm mb-6 overflow-hidden">
      <div className="px-5 py-3 border-b border-slate-200 flex items-center justify-between">
        <div className="text-sm font-bold text-slate-900">
          {result.company} · 목표주가
          <span className="ml-2 text-xs font-normal text-slate-500">리포트마다 목표주가 산출 표를 찾아 맞춘 결과</span>
        </div>
        <div className="text-xs text-slate-500">
          리포트 {result.documents.length}개 · 표 찾음 {matched.length}개
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-xs text-slate-600">
            <tr>
              <th className="px-4 py-2 text-left font-semibold">리포트</th>
              <th className="px-3 py-2 text-right font-semibold">목표주가</th>
              <th className="px-3 py-2 text-left font-semibold">근거 표</th>
              <th className="px-3 py-2 text-right font-semibold">원문</th>
            </tr>
          </thead>
          <tbody>
            {result.documents.map((doc) => {
              const price = doc.matched ? findTargetPrice(doc.table_data) : null;
              return (
                <tr key={doc.doc_name} className="border-t border-slate-100">
                  <td className="px-4 py-2">
                    <div className="font-semibold text-slate-900">{doc.source_org || doc.doc_name}</div>
                    <div className="text-[11px] text-slate-400">{doc.publish_date || ""}</div>
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-slate-900">
                    {price ? (
                      <span title={`원문: ${price.label}`}>
                        {price.value.toLocaleString("ko-KR")}
                        {price.unit && <span className="ml-1 text-[10px] font-sans text-slate-400">{price.unit}</span>}
                      </span>
                    ) : (
                      <span className="text-slate-300">-</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-600">
                    {doc.matched ? (
                      <>
                        {doc.caption || "(제목 없음)"}
                        <span className="ml-1 text-slate-400">· {doc.page_number}페이지</span>
                      </>
                    ) : (
                      <span className="text-slate-400">목표주가 표를 찾지 못함</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {doc.matched && doc.page_number ? (
                      <button
                        type="button"
                        onClick={() => onOpenSource(doc)}
                        className="px-2 py-1 text-xs font-semibold text-indigo-600 hover:bg-indigo-50 rounded-lg"
                      >
                        원문 보기
                      </button>
                    ) : null}
                  </td>
                </tr>
              );
            })}
            {gap !== null && (
              <tr className="border-t-2 border-slate-200 bg-slate-50 text-xs">
                <td className="px-4 py-2 font-semibold text-slate-600">차이 (최대 − 최소)</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums font-bold text-rose-600">
                  {gap.toLocaleString("ko-KR")}
                </td>
                <td colSpan={2}></td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="px-5 py-3 border-t border-slate-100 flex items-center justify-between">
        <span className="text-[11px] text-slate-400">
          목표주가 값은 근거 표에서 &apos;목표주가·적정주가&apos; 행(또는 열)의 첫 숫자입니다. 원문과 함께 확인하세요.
        </span>
        {matched.length >= 1 && (
          <button
            type="button"
            onClick={() => setShowTables((v) => !v)}
            className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-lg"
          >
            {showTables ? "원본 표 접기" : "원본 표 나란히 보기"}
          </button>
        )}
      </div>

      {showTables && (
        <div className="px-5 pb-5 grid gap-4" style={{ gridTemplateColumns: `repeat(${Math.min(matched.length, 3)}, minmax(0, 1fr))` }}>
          {matched.map((doc) => {
            const table = doc.table_data as TableData;
            return (
              <div key={doc.doc_name} className="border border-slate-200 rounded-xl overflow-hidden">
                <div className="px-3 py-2 bg-slate-50 border-b border-slate-200">
                  <div className="text-xs font-bold text-slate-900">{doc.source_org || doc.doc_name}</div>
                  <div className="text-[11px] text-slate-500 truncate" title={doc.caption || ""}>
                    {doc.caption || "(제목 없음)"} · {doc.page_number}페이지
                  </div>
                </div>
                <div className="max-h-[360px] overflow-auto">
                  <table className="min-w-full text-[11px]">
                    <thead className="bg-white sticky top-0">
                      <tr>
                        {table.columns.map((c) => (
                          <th key={c} className="px-2 py-1 text-left font-semibold text-slate-600 whitespace-nowrap border-b border-slate-100">
                            {c}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {table.rows.map((row, i) => {
                        const label = String(row[table.columns[0]] ?? "");
                        const strong = isTargetPriceLabel(label);
                        return (
                          <tr key={i} className={strong ? "bg-amber-50" : ""}>
                            {table.columns.map((c, j) => (
                              <td
                                key={c}
                                className={`px-2 py-1 whitespace-nowrap border-b border-slate-50 ${
                                  j === 0 ? "text-slate-700" : "text-right font-mono tabular-nums text-slate-900"
                                } ${strong ? "font-bold" : ""}`}
                              >
                                {formatCell(row[c])}
                              </td>
                            ))}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <div className="px-3 py-2 border-t border-slate-100 flex gap-2">
                  <button
                    type="button"
                    onClick={() => onOpenSource(doc)}
                    className="text-[11px] font-semibold text-indigo-600 hover:underline"
                  >
                    원문 보기
                  </button>
                  {doc.element_id && (
                    <Link href={`/elements/${doc.element_id}`} className="text-[11px] font-semibold text-slate-500 hover:underline">
                      표 상세
                    </Link>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
