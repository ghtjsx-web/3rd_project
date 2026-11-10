"use client";

import { useEffect, useState, useTransition } from "react";
import Link from "next/link";
import ComparisonModal from "./components/ComparisonModal";
import ReviewTab from "./components/ReviewTab";

interface HealthStatus {
  status: string;
  service: string;
  qdrant_url: string;
  qdrant_connected: boolean;
  collection_name: string;
  collection_exists: boolean;
  total_elements?: number;
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

interface FilterOptions {
  brokers: string[];
  companies: string[];
  publish_dates: string[];
  element_types: string[];
}

export default function Home() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [elements, setElements] = useState<VisualElement[]>([]);
  const [filterOptions, setFilterOptions] = useState<FilterOptions>({
    brokers: [],
    companies: [],
    publish_dates: [],
    element_types: ["TABLE", "CHART", "DIAGRAM"],
  });
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Search & Filter States
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [selectedType, setSelectedType] = useState<string>("");
  const [selectedBroker, setSelectedBroker] = useState<string>("");
  const [selectedCompany, setSelectedCompany] = useState<string>("");
  const [selectedDate, setSelectedDate] = useState<string>("");
  const [searchLatency, setSearchLatency] = useState<number | null>(null);

  // Active Tab State (Gallery vs Admin Review)
  const [activeTab, setActiveTab] = useState<"gallery" | "review">("gallery");

  // Comparison State (Max 2 items)
  const [selectedForCompare, setSelectedForCompare] = useState<VisualElement[]>([]);
  const [isCompareModalOpen, setIsCompareModalOpen] = useState<boolean>(false);

  // NEXT_PUBLIC_API_URL로 백엔드 주소 단일화 (미설정 시 조용히 넘기지 않고 경고)
  const backendUrl = process.env.NEXT_PUBLIC_API_URL || "";
  const isApiUrlMissing = !backendUrl.trim();

  async function fetchHealth() {
    if (isApiUrlMissing) return;
    try {
      const healthRes = await fetch(`${backendUrl}/health`);
      if (healthRes.ok) {
        const healthData = await healthRes.json();
        setHealth(healthData);
      }
    } catch (err: any) {
      console.error("Health check error:", err);
    }
  }

  async function fetchFilterOptions() {
    if (isApiUrlMissing) return;
    try {
      const res = await fetch(`${backendUrl}/api/filter-options`);
      if (res.ok) {
        const data = await res.json();
        setFilterOptions(data);
      }
    } catch (err) {
      console.error("Filter options error:", err);
    }
  }

  async function fetchElements(
    query = searchQuery,
    type = selectedType,
    broker = selectedBroker,
    company = selectedCompany,
    date = selectedDate
  ) {
    if (isApiUrlMissing) {
      setError("API 주소 미설정: NEXT_PUBLIC_API_URL 환경변수가 설정되지 않았습니다.");
      setLoading(false);
      return;
    }
    const startTime = performance.now();
    try {
      setLoading(true);
      setError(null);
      const params = new URLSearchParams();
      if (query.trim()) params.append("query", query.trim());
      if (type) params.append("element_type", type);
      if (broker) params.append("broker", broker);
      if (company) params.append("company", company);
      if (date) params.append("publish_date", date);
      params.append("limit", "100");

      const res = await fetch(`${backendUrl}/api/elements?${params.toString()}`);
      if (!res.ok) throw new Error("도표 데이터를 불러오는데 실패했습니다.");
      const data = await res.json();
      setElements(data);

      const elapsedSec = (performance.now() - startTime) / 1000;
      setSearchLatency(Number(elapsedSec.toFixed(3)));
    } catch (err: any) {
      console.error("Fetch error:", err);
      setError(err.message || "백엔드 연결 실패");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchHealth();
    fetchFilterOptions();
    fetchElements("", "", "", "", "");
  }, []);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    fetchElements(searchQuery, selectedType, selectedBroker, selectedCompany, selectedDate);
  };

  const handleTypeFilter = (type: string) => {
    const nextType = selectedType === type ? "" : type;
    setSelectedType(nextType);
    fetchElements(searchQuery, nextType, selectedBroker, selectedCompany, selectedDate);
  };

  const handleResetFilters = () => {
    setSearchQuery("");
    setSelectedType("");
    setSelectedBroker("");
    setSelectedCompany("");
    setSelectedDate("");
    fetchElements("", "", "", "", "");
  };

  const handleToggleCompare = (elem: VisualElement, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const isSelected = selectedForCompare.some((x) => x.element_id === elem.element_id);
    if (isSelected) {
      setSelectedForCompare(selectedForCompare.filter((x) => x.element_id !== elem.element_id));
    } else {
      if (selectedForCompare.length >= 2) {
        alert("도표 비교는 최대 2개까지만 선택할 수 있습니다. 기존 선택을 해제 후 추가해 주세요.");
        return;
      }
      setSelectedForCompare([...selectedForCompare, elem]);
    }
  };

  return (
    <main className="max-w-7xl mx-auto px-4 py-8">
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
            증권사 리서치 리포트 시각 자료(표·차트·다이어그램) 멀티모달 자동 색인 및 검색
          </p>
        </div>

        {/* Backend & Qdrant Connection Status Banner */}
        <div className="flex flex-wrap items-center gap-2 text-sm bg-white p-3 rounded-xl shadow-sm border">
          <div className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
            Frontend: OK
          </div>

          <div
            className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border ${
              isApiUrlMissing
                ? "bg-rose-100 text-rose-800 border-rose-300 font-bold"
                : health?.status === "ok"
                ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                : "bg-rose-50 text-rose-700 border-rose-200"
            }`}
          >
            <span
              className={`w-2 h-2 rounded-full ${
                isApiUrlMissing
                  ? "bg-rose-600 animate-ping"
                  : health?.status === "ok"
                  ? "bg-emerald-500"
                  : "bg-rose-500"
              }`}
            ></span>
            Backend: {isApiUrlMissing ? "API 주소 미설정" : health?.status === "ok" ? "Connected" : "Disconnected"}
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
            Qdrant: {health?.qdrant_connected ? "Connected" : "Waiting..."}
          </div>

          {health?.collection_name && (
            <div
              className={`flex items-center gap-1 px-3 py-1 rounded-full text-xs font-semibold border ${
                health.collection_exists
                  ? "bg-blue-50 text-blue-700 border-blue-200"
                  : "bg-slate-100 text-slate-600 border-slate-300"
              }`}
            >
              Qdrant 색인: {health.total_elements ?? 0}건
            </div>
          )}
        </div>
      </header>

      {/* Main Mode Tabs: Gallery Search vs Human-in-the-Loop Admin Review */}
      <div className="flex items-center gap-2 mb-8 border-b border-slate-200 pb-3">
        <button
          type="button"
          onClick={() => setActiveTab("gallery")}
          className={`px-5 py-2.5 text-xs font-bold rounded-xl transition-all flex items-center gap-2 ${
            activeTab === "gallery"
              ? "bg-indigo-600 text-white shadow-md shadow-indigo-200"
              : "bg-white text-slate-600 hover:bg-slate-50 border border-slate-200"
          }`}
        >
          <span>🖼️ 도표 검색 갤러리</span>
          <span
            className={`px-2 py-0.5 rounded-full text-[11px] font-mono ${
              activeTab === "gallery" ? "bg-white/20 text-white" : "bg-slate-100 text-slate-600"
            }`}
          >
            {elements.length}건 승인 노출
          </span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("review")}
          className={`px-5 py-2.5 text-xs font-bold rounded-xl transition-all flex items-center gap-2 ${
            activeTab === "review"
              ? "bg-amber-500 text-white shadow-md shadow-amber-200"
              : "bg-white text-slate-600 hover:bg-slate-50 border border-slate-200"
          }`}
        >
          <span>🛡️ 관리자 검수 탭</span>
          <span
            className={`px-2 py-0.5 rounded-full text-[11px] font-bold ${
              activeTab === "review" ? "bg-white/20 text-white" : "bg-amber-100 text-amber-800"
            }`}
          >
            확신도 &lt; 0.80
          </span>
        </button>
      </div>

      {activeTab === "review" ? (
        /* Admin Review Tab View */
        <ReviewTab
          backendUrl={backendUrl}
          onItemApproved={() => {
            fetchElements();
            fetchHealth();
          }}
        />
      ) : (
        /* Standard Gallery Search View */
        <>
          {/* Search & Multi-Filter Bar */}
          <section className="mb-8 bg-white p-5 rounded-2xl border border-slate-200 shadow-sm">
        {/* Row 1: Natural Language Semantic Search */}
        <form onSubmit={handleSearchSubmit} className="flex flex-col sm:flex-row gap-2.5 items-center mb-4">
          <div className="relative flex-1 w-full">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="자연어 문장 검색 (예: 2026년 영업이익 전망, 편의점 매출 추이, HBM3E 수혜주 등)"
              className="w-full px-4 py-3 pl-11 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-slate-50/50 shadow-inner text-sm"
            />
            <svg
              className="absolute left-3.5 top-3.5 w-5 h-5 text-slate-400"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
              />
            </svg>
          </div>

          <button
            type="submit"
            className="w-full sm:w-auto px-7 py-3 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold rounded-xl text-sm transition-colors shadow-sm flex items-center justify-center gap-1.5"
          >
            <span>검색</span>
            {loading && <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin"></div>}
          </button>
        </form>

        {/* Row 2: Metadata Payload Filters (Type, Broker, Company, Publish Date) */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-slate-100">
          <div className="flex flex-wrap items-center gap-2">
            {/* Element Type Filter Pills */}
            <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-xl">
              <button
                type="button"
                onClick={() => handleTypeFilter("")}
                className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all ${
                  selectedType === ""
                    ? "bg-white text-indigo-700 shadow-sm"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                전체
              </button>
              {filterOptions.element_types.map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => handleTypeFilter(t)}
                  className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all ${
                    selectedType === t
                      ? "bg-indigo-600 text-white shadow-sm"
                      : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>

            {/* Broker Dropdown Filter */}
            <select
              value={selectedBroker}
              onChange={(e) => {
                const b = e.target.value;
                setSelectedBroker(b);
                fetchElements(searchQuery, selectedType, b, selectedCompany, selectedDate);
              }}
              className="px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-medium text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">증권사 (전체)</option>
              {filterOptions.brokers.map((broker) => (
                <option key={broker} value={broker}>
                  {broker}
                </option>
              ))}
            </select>

            {/* Company Dropdown Filter */}
            <select
              value={selectedCompany}
              onChange={(e) => {
                const c = e.target.value;
                setSelectedCompany(c);
                fetchElements(searchQuery, selectedType, selectedBroker, c, selectedDate);
              }}
              className="px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-medium text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 max-w-[150px]"
            >
              <option value="">기업명 (전체)</option>
              {filterOptions.companies.map((company) => (
                <option key={company} value={company}>
                  {company}
                </option>
              ))}
            </select>

            {/* Publish Date Dropdown Filter */}
            <select
              value={selectedDate}
              onChange={(e) => {
                const d = e.target.value;
                setSelectedDate(d);
                fetchElements(searchQuery, selectedType, selectedBroker, selectedCompany, d);
              }}
              className="px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-medium text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">발행일 (전체)</option>
              {filterOptions.publish_dates.map((date) => (
                <option key={date} value={date}>
                  {date}
                </option>
              ))}
            </select>
          </div>

          {/* Reset Filters Button */}
          {(selectedType || selectedBroker || selectedCompany || selectedDate || searchQuery) && (
            <button
              type="button"
              onClick={handleResetFilters}
              className="text-xs text-rose-600 hover:text-rose-700 hover:underline font-semibold flex items-center gap-1"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              필터 초기화
            </button>
          )}
        </div>
      </section>

      {/* Error Notice */}
      {isApiUrlMissing ? (
        <div className="mb-6 p-5 rounded-2xl bg-rose-50 border-2 border-rose-300 text-rose-900 shadow-sm flex items-start gap-3">
          <div className="w-6 h-6 rounded-full bg-rose-600 text-white flex items-center justify-center font-bold text-sm flex-shrink-0 mt-0.5">!</div>
          <div>
            <h3 className="font-bold text-base mb-1">API 주소 미설정 오류</h3>
            <p className="text-xs text-rose-700 leading-relaxed mb-2">
              프론트엔드 빌드 환경변수 <code className="bg-rose-100 px-1.5 py-0.5 rounded font-mono font-bold">NEXT_PUBLIC_API_URL</code> 이 지정되지 않아 백엔드 서버와 통신할 수 없습니다.
            </p>
            <p className="text-xs text-rose-600">
              배포 시 <code className="bg-rose-100 px-1.5 py-0.5 rounded font-mono">--env NEXT_PUBLIC_API_URL=https://figindex-api.onpod.ai</code> 를 주입해 주세요.
            </p>
          </div>
        </div>
      ) : error ? (
        <div className="mb-6 p-4 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-sm">
          <p className="font-bold">안내:</p>
          <p>{error}</p>
        </div>
      ) : null}

      {/* Results Header with Search Latency Badge */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4">
        <h2 className="text-xl font-bold text-slate-800 flex items-center gap-2">
          <span>색인된 시각 자료 갤러리</span>
          <span className="text-xs px-2.5 py-0.5 rounded-full bg-indigo-100 text-indigo-700 font-semibold">
            {elements.length}개 표시 중
          </span>
        </h2>

        <div className="flex items-center gap-2">
          {searchLatency !== null && (
            <span
              className={`text-xs px-2.5 py-1 rounded-full font-mono font-semibold flex items-center gap-1 border ${
                searchLatency <= 1.0
                  ? "bg-emerald-50 text-emerald-700 border-emerald-300"
                  : "bg-amber-50 text-amber-700 border-amber-300"
              }`}
            >
              <span>⚡ 검색 응답: {searchLatency}초</span>
              {searchLatency <= 1.0 && <span className="text-[10px] text-emerald-600 font-sans font-bold">(1초 이내 달성)</span>}
            </span>
          )}
          <span className="text-xs text-slate-400">
            Qdrant Dense Vector + Payload Must Filter
          </span>
        </div>
      </div>

      {/* Grid of Visual Elements */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1, 2, 3].map((n) => (
            <div key={n} className="h-80 bg-slate-100 rounded-2xl animate-pulse"></div>
          ))}
        </div>
      ) : elements.length === 0 ? (
        <div className="text-center py-16 bg-white rounded-2xl border border-dashed text-slate-500">
          <p className="text-base font-semibold mb-1">검색 결과가 없습니다.</p>
          <p className="text-xs text-slate-400">색인 파이프라인(`run_index.py`)이 완료되었는지 확인해 주세요.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {elements.map((elem) => (
            <Link
              key={elem.element_id}
              href={`/elements/${elem.element_id}`}
              className="group bg-white rounded-2xl border border-slate-200 overflow-hidden shadow-sm hover:shadow-lg hover:border-indigo-300 transition-all flex flex-col justify-between cursor-pointer"
            >
              <div>
                {/* Image Preview & Thumbnail */}
                <div className="relative bg-slate-100 h-48 border-b overflow-hidden flex items-center justify-center">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={`${backendUrl}${elem.image_path}`}
                    alt={elem.title_or_caption}
                    className="max-h-full max-w-full object-contain p-2 transition-transform duration-200 group-hover:scale-105"
                    onError={(e) => {
                      const target = e.target as HTMLElement;
                      target.style.display = "none";
                      const fallback = target.parentElement?.querySelector(".img-fallback");
                      if (fallback) (fallback as HTMLElement).style.display = "flex";
                    }}
                  />

                  {/* Fallback placeholder when image is missing */}
                  <div className="img-fallback hidden flex-col items-center justify-center text-slate-400 text-xs gap-1">
                    <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                    <span>크롭 이미지 없음</span>
                  </div>

                  {/* Badges on top of thumbnail */}
                  <div className="absolute top-2 left-2 flex gap-1 z-10">
                    <span
                      className={`text-[10px] font-bold px-2 py-0.5 rounded shadow-sm ${
                        elem.element_type === "TABLE"
                          ? "bg-blue-600 text-white"
                          : elem.element_type === "CHART"
                          ? "bg-purple-600 text-white"
                          : "bg-emerald-600 text-white"
                      }`}
                    >
                      {elem.element_type}
                    </span>
                    <span className="text-[10px] font-medium bg-black/60 text-white px-1.5 py-0.5 rounded backdrop-blur-sm">
                      p.{elem.page_number}
                    </span>
                  </div>

                  <div className="absolute top-2 right-2 flex items-center gap-1 z-10">
                    <span
                      className={`text-[10px] font-bold px-2 py-0.5 rounded shadow-sm border ${
                        elem.review_status === "APPROVED"
                          ? "bg-emerald-50 text-emerald-700 border-emerald-300"
                          : "bg-amber-50 text-amber-700 border-amber-300"
                      }`}
                    >
                      확신도 {(elem.confidence_score * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>

                {/* Card Body: Title, 2-Line Summary, Hashtags */}
                <div className="p-4">
                  <h3 className="font-bold text-base text-slate-900 mb-2 line-clamp-2 leading-snug group-hover:text-indigo-600 transition-colors">
                    {elem.title_or_caption}
                  </h3>
                  <p className="text-xs text-slate-600 mb-3 line-clamp-2 leading-relaxed">
                    {elem.summary}
                  </p>

                  {/* Hashtags */}
                  <div className="flex flex-wrap gap-1">
                    {elem.hashtags.slice(0, 4).map((tag, tIdx) => (
                      <span
                        key={tIdx}
                        className="text-[11px] px-2 py-0.5 bg-slate-100 text-slate-600 rounded"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              </div>

              {/* Card Footer with Compare Checkbox */}
              <div className="p-3 bg-slate-50 border-t border-slate-100 text-[11px] text-slate-500 flex items-center justify-between gap-2">
                <div className="truncate max-w-[160px]" title={`${elem.source_org} | ${elem.doc_title}`}>
                  <span className="font-medium text-slate-700">{elem.source_org}</span>
                  <span className="text-slate-400 block text-[10px]">{elem.publish_date}</span>
                </div>

                {/* Compare Checkbox Button */}
                <button
                  type="button"
                  onClick={(e) => handleToggleCompare(elem, e)}
                  className={`text-[11px] font-semibold px-2.5 py-1 rounded-lg border transition-all flex items-center gap-1.5 shadow-sm ${
                    selectedForCompare.some((x) => x.element_id === elem.element_id)
                      ? "bg-indigo-600 text-white border-indigo-600"
                      : "bg-white text-slate-600 border-slate-300 hover:border-indigo-400 hover:text-indigo-600"
                  }`}
                  title="1:1 비교함에 담기 (최대 2개)"
                >
                  <span
                    className={`w-3.5 h-3.5 rounded flex items-center justify-center text-[10px] border ${
                      selectedForCompare.some((x) => x.element_id === elem.element_id)
                        ? "bg-white text-indigo-600 border-white font-bold"
                        : "border-slate-400 bg-slate-50"
                    }`}
                  >
                    {selectedForCompare.some((x) => x.element_id === elem.element_id) ? "✓" : ""}
                  </span>
                  <span>비교함</span>
                </button>
              </div>
            </Link>
          ))}
        </div>
      )}
        </>
      )}

      {/* Floating Bottom Compare Bar (Appears when 1+ elements selected) */}
      {selectedForCompare.length > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 bg-slate-900/95 backdrop-blur-md text-white px-5 py-3.5 rounded-2xl shadow-2xl border border-slate-700 flex items-center gap-5 animate-in slide-in-from-bottom-5 duration-200">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-indigo-600 flex items-center justify-center font-bold text-xs shadow">
              {selectedForCompare.length}
            </div>
            <div>
              <p className="text-xs font-bold flex items-center gap-1.5">
                <span>비교함 담김 ({selectedForCompare.length}/2)</span>
                {selectedForCompare.length === 2 && (
                  <span className="text-[10px] bg-emerald-500/20 text-emerald-300 px-1.5 py-0.2 rounded border border-emerald-500/40">
                    준비 완료
                  </span>
                )}
              </p>
              <p className="text-[11px] text-slate-400">
                {selectedForCompare.length === 2
                  ? "지금 바로 나란히 1:1 비교를 시작할 수 있습니다."
                  : "비교할 도표를 1개 더 선택해 주세요."}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setIsCompareModalOpen(true)}
              disabled={selectedForCompare.length !== 2}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-bold rounded-xl shadow-md transition-all flex items-center gap-1.5"
            >
              <span>1:1 비교하기</span>
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
              </svg>
            </button>

            <button
              type="button"
              onClick={() => setSelectedForCompare([])}
              className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium rounded-xl transition-colors"
            >
              선택 해제
            </button>
          </div>
        </div>
      )}

      {/* 1:1 Comparison Modal */}
      <ComparisonModal
        isOpen={isCompareModalOpen}
        onClose={() => setIsCompareModalOpen(false)}
        elements={selectedForCompare}
        backendUrl={backendUrl}
      />
    </main>
  );
}
