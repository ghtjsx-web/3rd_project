"use client";

import { useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

// Configure pdfjs worker to unpkg CDN for reliable browser compatibility
pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

interface PdfViewerProps {
  pdfUrl: string;
  initialPage: number;
}

export default function PdfViewer({ pdfUrl, initialPage }: PdfViewerProps) {
  const [numPages, setNumPages] = useState<number | null>(null);
  const [currentPage, setCurrentPage] = useState<number>(initialPage || 1);
  const [scale, setScale] = useState<number>(1.0);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  function onDocumentLoadSuccess({ numPages }: { numPages: number }) {
    setNumPages(numPages);
    setLoading(false);
    setLoadError(null);
  }

  function onDocumentLoadError(error: Error) {
    console.error("PDF load error:", error);
    setLoadError("원문 PDF를 불러오지 못했습니다.");
    setLoading(false);
  }

  return (
    <div className="flex flex-col h-full bg-slate-900 rounded-2xl overflow-hidden border border-slate-800 shadow-lg text-white">
      {/* Top Controller Bar */}
      <div className="p-3 bg-slate-800/90 backdrop-blur border-b border-slate-700 flex items-center justify-between text-xs">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-slate-300">원문 리포트 PDF</span>
          <span className="px-2 py-0.5 rounded bg-indigo-600/30 text-indigo-300 font-mono font-bold border border-indigo-500/30">
            {currentPage} / {numPages || "?"} 페이지
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
            disabled={currentPage <= 1}
            className="px-2.5 py-1 bg-slate-700 hover:bg-slate-600 disabled:opacity-40 rounded transition-colors"
          >
            ◀ 이전
          </button>
          <button
            onClick={() => setCurrentPage((p) => (numPages ? Math.min(numPages, p + 1) : p + 1))}
            disabled={numPages ? currentPage >= numPages : false}
            className="px-2.5 py-1 bg-slate-700 hover:bg-slate-600 disabled:opacity-40 rounded transition-colors"
          >
            다음 ▶
          </button>

          <div className="h-4 w-px bg-slate-700 mx-1"></div>

          <button
            onClick={() => setScale((s) => Math.max(0.6, s - 0.15))}
            className="px-2 py-1 bg-slate-700 hover:bg-slate-600 rounded"
            title="축소"
          >
            -
          </button>
          <span className="text-[11px] font-mono text-slate-400 w-10 text-center">
            {Math.round(scale * 100)}%
          </span>
          <button
            onClick={() => setScale((s) => Math.min(1.8, s + 0.15))}
            className="px-2 py-1 bg-slate-700 hover:bg-slate-600 rounded"
            title="확대"
          >
            +
          </button>

          <a
            href={pdfUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-2 px-2.5 py-1 bg-indigo-600 hover:bg-indigo-500 text-white rounded font-medium transition-colors"
          >
            새 창
          </a>
        </div>
      </div>

      {/* PDF Canvas View Area */}
      <div className="flex-1 overflow-auto p-4 flex justify-center items-start bg-slate-950">
        {loading && (
          <div className="py-20 flex flex-col items-center gap-2 text-slate-400 text-xs">
            <div className="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
            <span>원문 PDF {currentPage}페이지 로딩 중...</span>
          </div>
        )}

        {loadError ? (
          <div className="py-16 text-center text-xs text-rose-400">
            <p className="font-semibold mb-2">{loadError}</p>
            <a
              href={pdfUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="underline text-indigo-400 hover:text-indigo-300"
            >
              여기를 클릭해 브라우저 내장 뷰어로 직접 열기
            </a>
          </div>
        ) : (
          <Document
            file={pdfUrl}
            onLoadSuccess={onDocumentLoadSuccess}
            onLoadError={onDocumentLoadError}
            loading=""
            className="flex justify-center shadow-2xl"
          >
            <Page
              pageNumber={currentPage}
              scale={scale}
              renderTextLayer={false}
              renderAnnotationLayer={false}
              className="rounded overflow-hidden"
            />
          </Document>
        )}
      </div>
    </div>
  );
}

