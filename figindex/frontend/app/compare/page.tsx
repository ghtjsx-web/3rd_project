"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import TargetPriceView from "./TargetPriceView";
import {
  COMPARE_KRW_UNITS,
  CompanyCompareResponse,
  CompareMetricsResponse,
  ComparisonCell,
  ComparisonResult,
  FilterOptions,
  MatchedDocComparison,
  PERIOD_BASIS_LABELS,
} from "../lib/types";

// react-pdf는 브라우저에서만 동작하므로 SSR을 끈다
const PdfViewer = dynamic(() => import("../components/PdfViewer"), {
  ssr: false,
  loading: () => (
    <div className="h-full min-h-[500px] flex items-center justify-center bg-slate-900 rounded-2xl text-slate-400 text-xs">
      <div className="w-5 h-5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mr-2"></div>
      PDF 뷰어 로딩 중...
    </div>
  ),
});

/** 목표주가 칩의 지표 값. 셀 비교 엔진(/api/compare) 지표가 아니라 매칭 엔진(/api/compare/company, TARGET_PRICE)을 부른다 */
const TARGET_PRICE_METRIC = "목표주가";

/** 원문 뷰어에 띄울 위치 (셀 비교·목표주가 비교 공용) */
interface SourceLocation {
  element_id: string;
  doc_name: string;
  page_number: number;
}

/** 차이가 평균의 몇 % 이상이면 강조할지 (화면 표시용) */
const HIGHLIGHT_GAP_RATIO = 0.05;

/** "2026" → "2026", "2026Q3" → "3Q26" (증권사 리포트에서 흔히 쓰는 표기) */
function formatPeriod(periodKey: string): string {
  const m = /^(\d{4})Q([1-4])$/.exec(periodKey);
  if (!m) return periodKey;
  return `${m[2]}Q${m[1].slice(2)}`;
}

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
}

/** 한 행 = 한 문서(증권사 리포트) */
interface DocRow {
  doc_id: string;
  doc_name: string;
  source_org?: string | null;
  publish_date?: string | null;
  cellsByPeriod: Map<string, ComparisonCell>;
}

export default function ComparePage() {
  const backendUrl = process.env.NEXT_PUBLIC_API_URL || "";
  const isApiUrlMissing = !backendUrl.trim();

  const [targets, setTargets] = useState<string[]>([]);
  const [target, setTarget] = useState<string>("");
  const [metrics, setMetrics] = useState<Record<string, number>>({});
  const [metric, setMetric] = useState<string>("");
  const [unit, setUnit] = useState<string>("");
  const [sharedOnly, setSharedOnly] = useState<boolean>(true);

  const [result, setResult] = useState<ComparisonResult | null>(null);
  const [companyResult, setCompanyResult] = useState<CompanyCompareResponse | null>(null);
  const [sourceDoc, setSourceDoc] = useState<SourceLocation | null>(null);
  const [selectedCell, setSelectedCell] = useState<ComparisonCell | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  async function getJson<T>(path: string): Promise<T> {
    let res: Response;
    try {
      res = await fetch(`${backendUrl}${path}`);
    } catch {
      throw new Error(`백엔드에 연결할 수 없습니다 (주소: ${backendUrl})`);
    }
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const body = await res.json();
        if (body && typeof body.detail === "string") detail = body.detail;
      } catch {
        // 본문이 JSON이 아니면 상태 코드만 보여 준다
      }
      throw new Error(`${detail} (요청 경로: ${path})`);
    }
    return res.json();
  }

  // 1) 처음 열 때: 주소창의 ?target=&metric= 을 읽고, 종목 목록을 가져온다
  useEffect(() => {
    if (isApiUrlMissing) {
      setError("API 주소 미설정: NEXT_PUBLIC_API_URL 환경변수가 지정되지 않았습니다.");
      return;
    }
    const params = new URLSearchParams(window.location.search);
    const initialTarget = params.get("target") || "";
    const initialMetric = params.get("metric") || "";

    getJson<FilterOptions>("/api/filter-options")
      .then((options) => {
        const all = new Set<string>();
        Object.values(options.targets || {}).forEach((list) => list.forEach((t) => all.add(t)));
        const sorted = Array.from(all).sort((a, b) => a.localeCompare(b, "ko"));
        setTargets(sorted);
        if (initialTarget) {
          setTarget(initialTarget);
          setMetric(initialMetric);
        }
      })
      .catch((e: Error) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 2) 종목이 바뀌면 비교할 수 있는 지표 목록을 가져온다
  useEffect(() => {
    if (!target) {
      setMetrics({});
      return;
    }
    setError(null);
    getJson<CompareMetricsResponse>(`/api/compare/metrics?target=${encodeURIComponent(target)}`)
      .then((data) => {
        setMetrics(data.metrics || {});
        // 고른 지표가 이 종목에 없으면, 두 곳 이상 있는 첫 지표로 바꾼다
        setMetric((current) => {
          if (current === TARGET_PRICE_METRIC) return current;
          if (current && data.metrics[current]) return current;
          const first = Object.entries(data.metrics).find(([, n]) => n >= 2);
          return first ? first[0] : Object.keys(data.metrics)[0] || "";
        });
      })
      .catch((e: Error) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target]);

  // 3) 종목·지표·단위가 정해지면 비교 결과를 가져온다
  useEffect(() => {
    if (!target || !metric) {
      setResult(null);
      setCompanyResult(null);
      return;
    }
    window.history.replaceState(null, "", `?${new URLSearchParams({ target, metric }).toString()}`);
    setLoading(true);
    setError(null);
    setSelectedCell(null);
    setSourceDoc(null);

    if (metric === TARGET_PRICE_METRIC) {
      setResult(null);
      const companyQuery = new URLSearchParams({ company: target, metric: "TARGET_PRICE" });
      getJson<CompanyCompareResponse>(`/api/compare/company?${companyQuery.toString()}`)
        .then(setCompanyResult)
        .catch((e: Error) => {
          setCompanyResult(null);
          setError(e.message);
        })
        .finally(() => setLoading(false));
      return;
    }

    setCompanyResult(null);
    const query = new URLSearchParams({ target, metric });
    if (unit) query.set("unit", unit);
    getJson<ComparisonResult>(`/api/compare?${query.toString()}`)
      .then(setResult)
      .catch((e: Error) => {
        setResult(null);
        setError(e.message);
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, metric, unit]);

  // 문서별 행으로 묶기
  const rows: DocRow[] = useMemo(() => {
    if (!result) return [];
    const byDoc = new Map<string, DocRow>();
    for (const cell of result.cells) {
      let row = byDoc.get(cell.doc_id);
      if (!row) {
        row = {
          doc_id: cell.doc_id,
          doc_name: cell.doc_name,
          source_org: cell.source_org,
          publish_date: cell.publish_date,
          cellsByPeriod: new Map(),
        };
        byDoc.set(cell.doc_id, row);
      }
      row.cellsByPeriod.set(cell.period_key, cell);
    }
    return Array.from(byDoc.values()).sort((a, b) =>
      (a.source_org || a.doc_name).localeCompare(b.source_org || b.doc_name, "ko")
    );
  }, [result]);

  // 화면에 보일 기간: 기본은 두 문서 이상에 값이 있는 기간만
  const visiblePeriods: string[] = useMemo(() => {
    if (!result) return [];
    if (!sharedOnly) return result.period_keys;
    return result.period_keys.filter(
      (p) => rows.filter((r) => r.cellsByPeriod.has(p)).length >= 2
    );
  }, [result, rows, sharedOnly]);

  // 기간별 차이(최대 - 최소)
  const gapByPeriod = useMemo(() => {
    const gaps = new Map<string, { gap: number; ratio: number }>();
    for (const p of visiblePeriods) {
      const values = rows
        .map((r) => r.cellsByPeriod.get(p)?.value)
        .filter((v): v is number => typeof v === "number");
      if (values.length < 2) continue;
      const max = Math.max(...values);
      const min = Math.min(...values);
      const mean = values.reduce((s, v) => s + v, 0) / values.length;
      gaps.set(p, { gap: max - min, ratio: mean !== 0 ? (max - min) / Math.abs(mean) : 0 });
    }
    return gaps;
  }, [rows, visiblePeriods]);

  const metricEntries = Object.entries(metrics);
  const comparableCount = metricEntries.filter(([, n]) => n >= 2).length;

  return (
    <main className="max-w-7xl mx-auto px-4 py-8">
      {/* 머리말 */}
      <header className="flex items-center justify-between mb-6">
        <div>
          <Link href="/" className="text-xs text-indigo-600 hover:underline">
            ← 도표 검색으로
          </Link>
          <h1 className="text-2xl font-bold text-slate-900 mt-1">리포트 수치 비교</h1>
          <p className="text-sm text-slate-500 mt-1">
            같은 종목을 다룬 여러 리포트의 표에서 같은 지표·같은 기간 값을 모아 보여 줍니다. 칸을 누르면 원문 페이지가 열립니다.
          </p>
        </div>
      </header>

      {/* 선택 영역 */}
      <section className="bg-white border border-slate-200 rounded-2xl p-5 mb-6 shadow-sm">
        <div className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1 text-xs font-semibold text-slate-600">
            종목
            <select
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              className="min-w-[200px] px-3 py-2 border border-slate-300 rounded-lg text-sm font-normal text-slate-900"
            >
              <option value="">종목을 고르세요</option>
              {targets.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-xs font-semibold text-slate-600">
            금액 단위
            <select
              value={unit}
              onChange={(e) => setUnit(e.target.value)}
              className="px-3 py-2 border border-slate-300 rounded-lg text-sm font-normal text-slate-900"
            >
              <option value="">자동 (가장 많이 쓰인 단위)</option>
              {COMPARE_KRW_UNITS.map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-2 text-xs font-semibold text-slate-600 pb-2">
            <input
              type="checkbox"
              checked={sharedOnly}
              onChange={(e) => setSharedOnly(e.target.checked)}
            />
            두 리포트 이상에 있는 기간만
          </label>
        </div>

        {target && (
          <div className="mt-4">
            <div className="text-xs font-semibold text-slate-600 mb-2">
              지표 <span className="font-normal text-slate-400">(괄호 안은 그 지표가 있는 리포트 수, 2개 이상이어야 비교됩니다 · 비교 가능 {comparableCount}개)</span>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setMetric(TARGET_PRICE_METRIC)}
                title="리포트마다 목표주가 산출 표를 찾아 나란히 비교합니다 (같은 종목 비교 그룹만)"
                className={`px-3 py-1.5 rounded-full text-xs font-semibold border transition-colors ${
                  metric === TARGET_PRICE_METRIC
                    ? "bg-amber-500 text-white border-amber-500"
                    : "bg-amber-50 text-amber-700 border-amber-300 hover:bg-amber-100"
                }`}
              >
                목표주가 (표 단위)
              </button>
              {metricEntries.length === 0 && (
                <span className="text-xs text-slate-400">이 종목의 승인된 표에서 비교할 지표를 찾지 못했습니다.</span>
              )}
              {metricEntries.map(([name, count]) => (
                <button
                  key={name}
                  type="button"
                  onClick={() => setMetric(name)}
                  className={`px-3 py-1.5 rounded-full text-xs font-semibold border transition-colors ${
                    metric === name
                      ? "bg-indigo-600 text-white border-indigo-600"
                      : count >= 2
                      ? "bg-white text-slate-700 border-slate-300 hover:bg-slate-50"
                      : "bg-slate-50 text-slate-400 border-slate-200"
                  }`}
                >
                  {name} ({count})
                </button>
              ))}
            </div>
          </div>
        )}
      </section>

      {error && (
        <div className="p-4 mb-6 bg-rose-50 border border-rose-200 rounded-xl text-sm text-rose-800">{error}</div>
      )}

      {loading && (
        <div className="py-10 flex items-center justify-center gap-2 text-sm text-slate-500">
          <div className="w-5 h-5 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin"></div>
          비교 결과를 불러오는 중...
        </div>
      )}

      {/* 목표주가 비교 (매칭 엔진) */}
      {!loading && companyResult && metric === TARGET_PRICE_METRIC && (
        <TargetPriceView
          result={companyResult}
          onOpenSource={(doc: MatchedDocComparison) => {
            if (!doc.element_id || !doc.page_number) return;
            setSourceDoc({ element_id: doc.element_id, doc_name: doc.doc_name, page_number: doc.page_number });
          }}
        />
      )}

      {/* 비교 표 */}
      {!loading && result && (
        <section className="bg-white border border-slate-200 rounded-2xl shadow-sm mb-6 overflow-hidden">
          <div className="px-5 py-3 border-b border-slate-200 flex items-center justify-between">
            <div className="text-sm font-bold text-slate-900">
              {result.target} · {result.metric_name}
              {result.unit && <span className="ml-2 text-xs font-normal text-slate-500">단위: {result.unit}</span>}
            </div>
            <div className="text-xs text-slate-500">
              리포트 {rows.length}개 · 기간 {visiblePeriods.length}개
            </div>
          </div>

          {rows.length === 0 || visiblePeriods.length === 0 ? (
            <div className="p-8 text-center text-sm text-slate-500">
              {rows.length < 2
                ? "이 지표가 있는 리포트가 하나뿐이라 비교할 수 없습니다."
                : "두 리포트 이상에 같이 있는 기간이 없습니다. 위의 체크를 끄면 모든 기간을 볼 수 있습니다."}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="bg-slate-50 text-xs text-slate-600">
                  <tr>
                    <th className="sticky left-0 bg-slate-50 px-4 py-2 text-left font-semibold min-w-[180px]">리포트</th>
                    {visiblePeriods.map((p) => (
                      <th key={p} className="px-3 py-2 text-right font-semibold whitespace-nowrap">
                        {formatPeriod(p)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.doc_id} className="border-t border-slate-100">
                      <td className="sticky left-0 bg-white px-4 py-2">
                        <div className="font-semibold text-slate-900">{row.source_org || row.doc_name}</div>
                        <div className="text-[11px] text-slate-400">{row.publish_date || ""}</div>
                      </td>
                      {visiblePeriods.map((p) => {
                        const cell = row.cellsByPeriod.get(p);
                        if (!cell) {
                          return (
                            <td key={p} className="px-3 py-2 text-right text-slate-300">
                              -
                            </td>
                          );
                        }
                        const isSelected =
                          selectedCell?.element_id === cell.element_id && selectedCell?.period_key === cell.period_key;
                        return (
                          <td key={p} className="px-1 py-1 text-right">
                            <button
                              type="button"
                              onClick={() => setSelectedCell(cell)}
                              title={`원문: ${cell.raw_row_label} / ${cell.raw_column} = ${cell.raw_value ?? "-"} (${cell.raw_unit || "단위 없음"}) · ${cell.page_number}페이지`}
                              className={`w-full px-2 py-1 rounded-lg font-mono tabular-nums transition-colors ${
                                isSelected ? "bg-indigo-600 text-white" : "hover:bg-indigo-50 text-slate-900"
                              }`}
                            >
                              {formatNumber(cell.value ?? null)}
                              {cell.period_basis && (
                                <span
                                  className={`ml-1 text-[10px] font-sans ${
                                    isSelected ? "text-indigo-100" : "text-slate-400"
                                  }`}
                                >
                                  {PERIOD_BASIS_LABELS[cell.period_basis]}
                                </span>
                              )}
                            </button>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                  {/* 차이 줄 */}
                  <tr className="border-t-2 border-slate-200 bg-slate-50 text-xs">
                    <td className="sticky left-0 bg-slate-50 px-4 py-2 font-semibold text-slate-600">
                      차이 (최대 − 최소)
                    </td>
                    {visiblePeriods.map((p) => {
                      const g = gapByPeriod.get(p);
                      if (!g) {
                        return (
                          <td key={p} className="px-3 py-2 text-right text-slate-300">
                            -
                          </td>
                        );
                      }
                      const strong = g.ratio >= HIGHLIGHT_GAP_RATIO;
                      return (
                        <td
                          key={p}
                          className={`px-3 py-2 text-right font-mono tabular-nums ${
                            strong ? "text-rose-600 font-bold" : "text-slate-500"
                          }`}
                        >
                          {formatNumber(g.gap)}
                          <div className="text-[10px] font-sans font-normal">
                            {(g.ratio * 100).toFixed(1)}%
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                </tbody>
              </table>
            </div>
          )}
          <div className="px-5 py-2 border-t border-slate-100 text-[11px] text-slate-400">
            차이가 평균의 {HIGHLIGHT_GAP_RATIO * 100}% 이상이면 빨간색으로 표시합니다. 이름이 같은 지표도 계산 기준이 다를 수 있으니 원문을 함께 확인하세요.
          </div>
        </section>
      )}

      {/* 원문 확인 (목표주가 비교) */}
      {sourceDoc && metric === TARGET_PRICE_METRIC && (
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm text-sm">
            <h2 className="text-base font-bold text-slate-900 mb-3">원문</h2>
            <div className="text-[11px] text-slate-400 break-all">{sourceDoc.doc_name}</div>
            <div className="mt-2 text-slate-900">{sourceDoc.page_number}페이지</div>
            <Link
              href={`/elements/${sourceDoc.element_id}`}
              className="inline-block mt-4 px-3 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-lg"
            >
              이 표 상세 보기
            </Link>
          </div>
          <div className="lg:col-span-2 h-[720px]">
            <PdfViewer
              key={`${sourceDoc.doc_name}-${sourceDoc.page_number}`}
              pdfUrl={`${backendUrl}/api/files/pdf/${encodeURIComponent(sourceDoc.doc_name)}`}
              initialPage={sourceDoc.page_number}
            />
          </div>
        </section>
      )}

      {/* 원문 확인 */}
      {selectedCell && (
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm text-sm">
            <h2 className="text-base font-bold text-slate-900 mb-3">원문 값</h2>
            <dl className="space-y-2">
              <div>
                <dt className="text-xs text-slate-500">리포트</dt>
                <dd className="font-semibold text-slate-900">
                  {selectedCell.source_org || "-"} · {selectedCell.publish_date || "-"}
                </dd>
                <dd className="text-[11px] text-slate-400 break-all">{selectedCell.doc_name}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">원문 행 · 열</dt>
                <dd className="text-slate-900">
                  {selectedCell.raw_row_label} · {selectedCell.raw_column}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">원문 값 (원문 단위)</dt>
                <dd className="font-mono text-slate-900">
                  {String(selectedCell.raw_value ?? "-")}{" "}
                  <span className="font-sans text-xs text-slate-500">{selectedCell.raw_unit || "단위 없음"}</span>
                </dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">비교에 쓴 값</dt>
                <dd className="font-mono text-slate-900">
                  {formatNumber(selectedCell.value ?? null)}{" "}
                  <span className="font-sans text-xs text-slate-500">{selectedCell.unit || ""}</span>
                </dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">위치</dt>
                <dd className="text-slate-900">{selectedCell.page_number}페이지</dd>
              </div>
            </dl>
            <Link
              href={`/elements/${selectedCell.element_id}`}
              className="inline-block mt-4 px-3 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-lg"
            >
              이 표 상세 보기
            </Link>
          </div>
          <div className="lg:col-span-2 h-[720px]">
            <PdfViewer
              key={`${selectedCell.doc_name}-${selectedCell.page_number}`}
              pdfUrl={`${backendUrl}/api/files/pdf/${encodeURIComponent(selectedCell.doc_name)}`}
              initialPage={selectedCell.page_number}
            />
          </div>
        </section>
      )}
    </main>
  );
}
