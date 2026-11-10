"use client";

import { useEffect, useState } from "react";

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

interface ReviewTabProps {
  backendUrl: string;
  onItemApproved?: () => void;
}

export default function ReviewTab({ backendUrl, onItemApproved }: ReviewTabProps) {
  const [elements, setElements] = useState<VisualElement[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [processingId, setProcessingId] = useState<string | null>(null);
  const [feedbackMsg, setFeedbackMsg] = useState<{ id: string; text: string; type: "success" | "error" } | null>(null);

  // Admin Auth States
  const [adminPassword, setAdminPassword] = useState<string>("");
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [passwordInput, setPasswordInput] = useState<string>("");
  const [authError, setAuthError] = useState<string | null>(null);
  const [isVerifying, setIsVerifying] = useState<boolean>(false);

  // Editable drafts indexed by element_id
  const [drafts, setDrafts] = useState<
    Record<
      string,
      {
        element_type: "TABLE" | "CHART" | "DIAGRAM";
        title_or_caption: string;
        summary: string;
        raw_json_table: string;
      }
    >
  >({});

  // Check existing session token on mount
  useEffect(() => {
    const savedPw = sessionStorage.getItem("figindex_admin_pw");
    if (savedPw) {
      verifyAndLogin(savedPw);
    }
  }, []);

  async function verifyAndLogin(passwordToTest: string) {
    try {
      setIsVerifying(true);
      setAuthError(null);
      const res = await fetch(`${backendUrl}/api/admin/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: passwordToTest }),
      });

      if (!res.ok) {
        throw new Error("관리자 비밀번호가 올바르지 않습니다.");
      }

      // Success
      setAdminPassword(passwordToTest);
      setIsAuthenticated(true);
      sessionStorage.setItem("figindex_admin_pw", passwordToTest);
      fetchReviewQueue(passwordToTest);
    } catch (err: any) {
      setAuthError(err.message || "인증 실패");
      setIsAuthenticated(false);
      sessionStorage.removeItem("figindex_admin_pw");
    } finally {
      setIsVerifying(false);
    }
  }

  const handleLoginSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!passwordInput.trim()) {
      setAuthError("비밀번호를 입력해 주세요.");
      return;
    }
    verifyAndLogin(passwordInput.trim());
  };

  const handleLogout = () => {
    sessionStorage.removeItem("figindex_admin_pw");
    setAdminPassword("");
    setIsAuthenticated(false);
    setPasswordInput("");
    setElements([]);
  };

  async function fetchReviewQueue(pw = adminPassword) {
    if (!pw) return;
    try {
      setLoading(true);
      const res = await fetch(`${backendUrl}/api/review/elements`, {
        headers: {
          "X-Admin-Password": pw,
        },
      });

      if (res.status === 401) {
        handleLogout();
        setAuthError("인증이 만료되었거나 비밀번호가 올바르지 않습니다.");
        return;
      }

      if (res.ok) {
        const data: VisualElement[] = await res.json();
        setElements(data);

        // Initialize editable form drafts
        const initialDrafts: Record<string, any> = {};
        data.forEach((elem) => {
          initialDrafts[elem.element_id] = {
            element_type: elem.element_type,
            title_or_caption: elem.title_or_caption,
            summary: elem.summary,
            raw_json_table: elem.structured_data
              ? JSON.stringify(elem.structured_data, null, 2)
              : "",
          };
        });
        setDrafts(initialDrafts);
      }
    } catch (err) {
      console.error("Failed to fetch review elements:", err);
    } finally {
      setLoading(false);
    }
  }

  const handleFieldChange = (id: string, field: string, value: string) => {
    setDrafts((prev) => ({
      ...prev,
      [id]: {
        ...prev[id],
        [field]: value,
      },
    }));
  };

  const handleDecision = async (elementId: string, action: "APPROVE" | "REJECT") => {
    setProcessingId(elementId);
    setFeedbackMsg(null);
    const draft = drafts[elementId];

    let parsedStructuredData = null;
    if (draft.raw_json_table && draft.raw_json_table.trim()) {
      try {
        parsedStructuredData = JSON.parse(draft.raw_json_table);
      } catch (err) {
        alert("표 데이터 JSON 형식이 올바르지 않습니다. 문법을 확인해 주세요.");
        setProcessingId(null);
        return;
      }
    }

    try {
      const payload = {
        action: action,
        element_type: draft.element_type,
        title_or_caption: draft.title_or_caption,
        summary: draft.summary,
        structured_data: parsedStructuredData,
      };

      const res = await fetch(`${backendUrl}/api/review/${elementId}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Admin-Password": adminPassword,
        },
        body: JSON.stringify(payload),
      });

      if (res.status === 401) {
        alert("관리자 권한이 유효하지 않습니다. 다시 로그인해 주세요.");
        handleLogout();
        return;
      }

      if (!res.ok) throw new Error("검수 처리 요청에 실패했습니다.");

      // Success feedback
      const msgText =
        action === "APPROVE"
          ? "✅ 승인 완료! 해당 도표가 갤러리 검색 결과에 실시간 반영되었습니다."
          : "🚫 반려 완료되었습니다. (검수 목록에서 제외됨)";

      setFeedbackMsg({ id: elementId, text: msgText, type: "success" });

      // Remove from pending list after short animation
      setTimeout(() => {
        setElements((prev) => prev.filter((x) => x.element_id !== elementId));
        setFeedbackMsg(null);
        if (action === "APPROVE" && onItemApproved) {
          onItemApproved();
        }
      }, 900);
    } catch (err: any) {
      setFeedbackMsg({ id: elementId, text: `오류: ${err.message}`, type: "error" });
    } finally {
      setProcessingId(null);
    }
  };

  // 1. Password Protection Gate (Not Authenticated)
  if (!isAuthenticated) {
    return (
      <div className="max-w-md mx-auto my-12 p-8 bg-white rounded-3xl border border-slate-200 shadow-xl text-center">
        <div className="w-16 h-16 rounded-2xl bg-amber-100 text-amber-600 flex items-center justify-center text-3xl mx-auto mb-4 shadow-sm">
          🔒
        </div>
        <h3 className="text-xl font-bold text-slate-900 mb-2">관리자 검수 권한 인증</h3>
        <p className="text-xs text-slate-500 mb-6">
          확신도 0.80 미만 도표 검수 및 승인·반려 작업은 관리자 비밀번호 인증이 필요합니다.
        </p>

        <form onSubmit={handleLoginSubmit} className="space-y-4">
          <div>
            <input
              type="password"
              value={passwordInput}
              onChange={(e) => setPasswordInput(e.target.value)}
              placeholder="관리자 비밀번호를 입력하세요"
              className="w-full px-4 py-3 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-500 text-sm shadow-inner"
              autoFocus
            />
          </div>

          {authError && (
            <p className="text-xs text-rose-600 font-semibold bg-rose-50 py-1.5 px-3 rounded-lg border border-rose-200">
              {authError}
            </p>
          )}

          <button
            type="submit"
            disabled={isVerifying}
            className="w-full py-3 bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-white font-bold rounded-xl text-sm transition-colors shadow-md flex items-center justify-center gap-2"
          >
            {isVerifying && <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>}
            <span>인증 및 검수 대기열 열기</span>
          </button>
        </form>

        <p className="text-[11px] text-slate-400 mt-5">
          * 초기 기본 비밀번호는 환경변수 <code>ADMIN_PASSWORD</code>에 설정되어 있습니다.
        </p>
      </div>
    );
  }

  // 2. Loading State
  if (loading) {
    return (
      <div className="py-20 text-center text-slate-500 text-sm">
        <div className="w-8 h-8 border-3 border-amber-500 border-t-transparent rounded-full animate-spin mx-auto mb-3"></div>
        <p>확신도 0.80 미만 검수 대기 도표를 불러오는 중입니다...</p>
      </div>
    );
  }

  // 3. Authenticated Review Queue View
  return (
    <div className="space-y-6">
      {/* Review Queue Summary Banner */}
      <div className="bg-amber-50 border border-amber-200 rounded-2xl p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-amber-500 text-white font-bold flex items-center justify-center text-lg shadow-sm">
            🛡️
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-bold text-sm text-amber-900">
                Human-in-the-Loop 관리자 검수 대기열
              </h3>
              <span className="text-[10px] bg-emerald-100 text-emerald-800 px-2 py-0.5 rounded-full font-bold border border-emerald-300">
                관리자 인증 완료 🟢
              </span>
            </div>
            <p className="text-xs text-amber-700">
              AI 확신도가 0.80 미만인 도표입니다. 오류를 수정한 뒤 <strong>[승인]</strong>하면 즉시 일반 검색 결과에 노출됩니다.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs font-bold px-3 py-1 bg-amber-200/70 text-amber-800 rounded-full">
            대기 중: {elements.length}건
          </span>
          <button
            onClick={() => fetchReviewQueue()}
            className="text-xs px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-700 font-semibold rounded-lg border border-amber-200 transition-colors shadow-sm"
          >
            새로고침
          </button>
          <button
            onClick={handleLogout}
            className="text-xs px-3 py-1.5 bg-slate-200 hover:bg-slate-300 text-slate-700 font-medium rounded-lg transition-colors"
            title="관리자 세션 로그아웃"
          >
            로그아웃
          </button>
        </div>
      </div>

      {/* Empty State */}
      {elements.length === 0 ? (
        <div className="py-16 text-center bg-white rounded-2xl border border-dashed text-slate-400">
          <svg className="w-12 h-12 mx-auto text-emerald-400 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p className="font-bold text-slate-700 text-base">모든 검수가 완료되었습니다!</p>
          <p className="text-xs text-slate-400 mt-1">확신도 0.80 미만의 대기 도표가 없습니다.</p>
        </div>
      ) : (
        <div className="space-y-6">
          {elements.map((elem) => {
            const draft = drafts[elem.element_id] || {
              element_type: elem.element_type,
              title_or_caption: elem.title_or_caption,
              summary: elem.summary,
              raw_json_table: "",
            };

            const isProcessing = processingId === elem.element_id;
            const currentFeedback = feedbackMsg?.id === elem.element_id ? feedbackMsg : null;

            return (
              <div
                key={elem.element_id}
                className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden p-5 transition-all hover:border-indigo-300"
              >
                {/* Status Bar */}
                <div className="flex flex-wrap items-center justify-between gap-2 pb-3 mb-4 border-b border-slate-100 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-slate-700">
                      {elem.extra_metadata?.company || elem.source_org} | {elem.doc_name}
                    </span>
                    <span className="text-slate-400">p.{elem.page_number}</span>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="text-rose-600 font-bold bg-rose-50 border border-rose-200 px-2.5 py-0.5 rounded-full">
                      ⚠️ 확신도 {(elem.confidence_score * 100).toFixed(1)}% (검수 필요)
                    </span>
                  </div>
                </div>

                {/* Main 2-Column: Left Crop vs Right Editor */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
                  {/* Left: Original Cropped Image */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between text-xs text-slate-500">
                      <span className="font-semibold text-slate-700">리포트 원본 크롭 이미지</span>
                      <a
                        href={`${backendUrl}${elem.image_path}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-indigo-600 hover:underline flex items-center gap-0.5"
                      >
                        크게 보기 ↗
                      </a>
                    </div>
                    <div className="bg-slate-50 border border-slate-200 rounded-xl p-2 flex items-center justify-center max-h-[360px] overflow-hidden shadow-inner">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={`${backendUrl}${elem.image_path}`}
                        alt={elem.title_or_caption}
                        className="max-h-[340px] max-w-full object-contain rounded"
                      />
                    </div>
                  </div>

                  {/* Right: Interactive Editing Form */}
                  <div className="space-y-4">
                    {/* Element Type Selector */}
                    <div>
                      <label className="block text-xs font-bold text-slate-700 mb-1">
                        도표 유형 수정
                      </label>
                      <div className="flex gap-2">
                        {["TABLE", "CHART", "DIAGRAM"].map((t) => (
                          <button
                            key={t}
                            type="button"
                            onClick={() => handleFieldChange(elem.element_id, "element_type", t)}
                            className={`px-3 py-1.5 rounded-lg text-xs font-bold border transition-all ${
                              draft.element_type === t
                                ? "bg-indigo-600 text-white border-indigo-600 shadow-sm"
                                : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
                            }`}
                          >
                            {t}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Title or Caption Input */}
                    <div>
                      <label className="block text-xs font-bold text-slate-700 mb-1">
                        제목 / 캡션 수정
                      </label>
                      <input
                        type="text"
                        value={draft.title_or_caption}
                        onChange={(e) =>
                          handleFieldChange(elem.element_id, "title_or_caption", e.target.value)
                        }
                        className="w-full px-3 py-2 text-xs border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 font-medium"
                      />
                    </div>

                    {/* Summary Input */}
                    <div>
                      <label className="block text-xs font-bold text-slate-700 mb-1">
                        요약문 수정
                      </label>
                      <textarea
                        rows={2}
                        value={draft.summary}
                        onChange={(e) =>
                          handleFieldChange(elem.element_id, "summary", e.target.value)
                        }
                        className="w-full px-3 py-2 text-xs border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none text-slate-700"
                      />
                    </div>

                    {/* Structured Table Value Editor (JSON) */}
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <label className="text-xs font-bold text-slate-700">
                          표 수치 데이터 (structured_data JSON)
                        </label>
                        <span className="text-[10px] text-slate-400">
                          columns 및 rows 수치 직접 수정 가능
                        </span>
                      </div>
                      <textarea
                        rows={5}
                        value={draft.raw_json_table}
                        placeholder="{ 'columns': [...], 'rows': [...] }"
                        onChange={(e) =>
                          handleFieldChange(elem.element_id, "raw_json_table", e.target.value)
                        }
                        className="w-full px-3 py-2 text-[11px] font-mono border border-slate-300 rounded-lg bg-slate-50 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                      />
                    </div>

                    {/* Action Buttons */}
                    <div className="pt-2 flex items-center justify-between gap-3 border-t border-slate-100">
                      {currentFeedback && (
                        <span
                          className={`text-xs font-semibold ${
                            currentFeedback.type === "success" ? "text-emerald-600" : "text-rose-600"
                          }`}
                        >
                          {currentFeedback.text}
                        </span>
                      )}
                      {!currentFeedback && <div></div>}

                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => handleDecision(elem.element_id, "REJECT")}
                          disabled={isProcessing}
                          className="px-4 py-2 bg-rose-50 hover:bg-rose-100 text-rose-700 font-bold rounded-xl text-xs border border-rose-200 transition-colors disabled:opacity-50"
                        >
                          반려 (REJECT)
                        </button>

                        <button
                          type="button"
                          onClick={() => handleDecision(elem.element_id, "APPROVE")}
                          disabled={isProcessing}
                          className="px-5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-xl text-xs shadow-md transition-colors disabled:opacity-50 flex items-center gap-1.5"
                        >
                          {isProcessing && <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin"></div>}
                          <span>승인 및 검색 노출 (APPROVE)</span>
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
