"use client";

import { useEffect, useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import { DOC_STATUS } from "../lib/types";
import type { Document, DocStatus } from "../lib/types";

type UploadPanelProps = {
  backendUrl: string;
};

const DOC_STATUS_LABELS: Record<DocStatus, string> = {
  [DOC_STATUS.UPLOADED]: "업로드됨",
  [DOC_STATUS.PROCESSING]: "처리 중",
  [DOC_STATUS.COMPLETED]: "완료",
  [DOC_STATUS.FAILED]: "실패",
  [DOC_STATUS.DUPLICATE]: "중복",
};

function formatFileSize(size: number): string {
  if (size < 1024) return String(size) + " 바이트";
  if (size < 1024 * 1024) return (size / 1024).toFixed(1) + " KB";
  return (size / (1024 * 1024)).toFixed(1) + " MB";
}

function isBatchDocumentSettled(document: Document): boolean {
  return (
    document.doc_status === DOC_STATUS.COMPLETED ||
    document.doc_status === DOC_STATUS.FAILED ||
    document.doc_status === DOC_STATUS.DUPLICATE
  );
}

export default function UploadPanel({ backendUrl }: UploadPanelProps) {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadedDocuments, setUploadedDocuments] = useState<Document[]>([]);
  const [batchIds, setBatchIds] = useState<string[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const apiBaseUrl = backendUrl.trim().replace(/\/+$/, "");
    if (!apiBaseUrl || batchIds.length === 0) return;

    let cancelled = false;
    let isRefreshing = false;

    async function refreshBatchStatus() {
      if (isRefreshing) return;
      isRefreshing = true;
      try {
        for (const batch_id of batchIds) {
          const response = await fetch(
            apiBaseUrl + "/api/batches/" + encodeURIComponent(batch_id)
          );
          const responseBody = await response.json().catch(() => null);
          if (!response.ok || !Array.isArray(responseBody)) {
            throw new Error("문서 처리 상태를 불러오지 못했습니다.");
          }

          const batchDocuments = responseBody as Document[];
          if (cancelled) return;
          setUploadedDocuments((currentDocuments) => [
            ...batchDocuments,
            ...currentDocuments.filter((document) => document.batch_id !== batch_id),
          ]);

          const isBatchSettled =
            batchDocuments.length > 0 && batchDocuments.every(isBatchDocumentSettled);
          if (isBatchSettled) {
            setBatchIds((currentBatchIds) =>
              currentBatchIds.filter((currentBatchId) => currentBatchId !== batch_id)
            );
          }
        }
        if (!cancelled) setErrorMessage(null);
      } catch (error: unknown) {
        if (!cancelled) {
          setErrorMessage(
            error instanceof Error ? error.message : "문서 처리 상태를 불러오지 못했습니다."
          );
        }
      } finally {
        isRefreshing = false;
      }
    }

    void refreshBatchStatus();
    const intervalId = window.setInterval(() => {
      void refreshBatchStatus();
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [backendUrl, batchIds]);

  function addPdfFiles(newFiles: File[]) {
    const pdfFiles = newFiles.filter((selectedFile) =>
      selectedFile.name.toLowerCase().endsWith(".pdf")
    );
    setSelectedFiles((currentFiles) => [...currentFiles, ...pdfFiles]);
    setErrorMessage(
      pdfFiles.length === newFiles.length
        ? null
        : "PDF 파일만 선택할 수 있습니다. PDF가 아닌 파일은 목록에 넣지 않았습니다."
    );
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    if (event.target.files) {
      addPdfFiles(Array.from(event.target.files));
    }
    event.target.value = "";
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(false);
    addPdfFiles(Array.from(event.dataTransfer.files));
  }

  async function handleUpload() {
    const apiBaseUrl = backendUrl.trim().replace(/\/+$/, "");
    if (!apiBaseUrl || selectedFiles.length === 0 || isUploading) return;
    setIsUploading(true);
    setErrorMessage(null);

    const formData = new FormData();
    selectedFiles.forEach((selectedFile) => {
      formData.append("files", selectedFile, selectedFile.name);
    });

    try {
      const response = await fetch(apiBaseUrl + "/api/batches", {
        method: "POST",
        body: formData,
      });
      const responseBody = await response.json().catch(() => null);
      if (!response.ok) {
        const detail =
          typeof responseBody?.detail === "string"
            ? responseBody.detail
            : "PDF 업로드에 실패했습니다.";
        throw new Error(detail);
      }
      if (!Array.isArray(responseBody)) {
        throw new Error("서버 응답을 확인할 수 없습니다.");
      }

      const batchDocuments = responseBody as Document[];
      setUploadedDocuments((currentDocuments) => [
        ...batchDocuments,
        ...currentDocuments,
      ]);
      const batch_id = batchDocuments[0]?.batch_id;
      if (batch_id) {
        setBatchIds((currentBatchIds) =>
          currentBatchIds.includes(batch_id)
            ? currentBatchIds
            : [...currentBatchIds, batch_id]
        );
      }
      setSelectedFiles([]);
    } catch (error: unknown) {
      setErrorMessage(
        error instanceof Error ? error.message : "PDF 업로드에 실패했습니다."
      );
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <section className="space-y-6">
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-5">
          <h2 className="text-lg font-bold text-slate-900">PDF 여러 개 등록</h2>
          <p className="mt-1 text-sm text-slate-600">
            이 단계에서는 파일을 저장하고 중복 여부를 확인합니다. 문서 분석은 다음 단계에서 연결됩니다.
          </p>
        </div>

        <div
          onDragOver={(event) => {
            event.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          className={
            "rounded-xl border-2 border-dashed p-8 text-center transition-colors " +
            (isDragging ? "border-indigo-500 bg-indigo-50" : "border-slate-300 bg-slate-50")
          }
        >
          <p className="text-sm font-semibold text-slate-800">
            PDF를 여기로 끌어오거나 파일을 선택하세요.
          </p>
          <p className="mt-1 text-xs text-slate-500">
            PDF 파일 여러 개를 한 번에 고를 수 있습니다.
          </p>
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,application/pdf"
            multiple
            onChange={handleFileChange}
            className="sr-only"
            aria-label="업로드할 PDF 파일 선택"
          />
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="mt-4 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100"
          >
            PDF 선택
          </button>
        </div>

        {!backendUrl.trim() && (
          <p className="mt-3 text-sm text-rose-700">
            백엔드 주소가 설정되지 않아 업로드할 수 없습니다.
          </p>
        )}
        {errorMessage && (
          <p role="alert" className="mt-3 text-sm text-rose-700">
            {errorMessage}
          </p>
        )}

        <div className="mt-5">
          <h3 className="text-sm font-bold text-slate-800">
            선택한 파일 {selectedFiles.length}개
          </h3>
          {selectedFiles.length > 0 ? (
            <ul className="mt-2 divide-y divide-slate-100 rounded-lg border border-slate-200">
              {selectedFiles.map((selectedFile, index) => (
                <li
                  key={String(index) + "-" + selectedFile.name}
                  className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
                >
                  <span className="truncate text-slate-700">{selectedFile.name}</span>
                  <span className="shrink-0 text-xs text-slate-500">
                    {formatFileSize(selectedFile.size)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-slate-500">선택된 파일이 없습니다.</p>
          )}
        </div>

        <button
          type="button"
          onClick={handleUpload}
          disabled={isUploading || selectedFiles.length === 0 || !backendUrl.trim()}
          className="mt-5 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-bold text-white transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {isUploading ? "업로드 중..." : "선택한 PDF 올리기"}
        </button>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-bold text-slate-900">업로드 결과</h2>
        {uploadedDocuments.length > 0 ? (
          <div className="mt-4 space-y-5">
            {Array.from(
              new Set(
                uploadedDocuments
                  .map((document) => document.batch_id)
                  .filter((batch_id): batch_id is string => Boolean(batch_id))
              )
            ).map((batch_id) => {
              const batchDocuments = uploadedDocuments.filter(
                (document) => document.batch_id === batch_id
              );
              const settledCount = batchDocuments.filter(isBatchDocumentSettled).length;
              const progress = batchDocuments.length
                ? Math.round((settledCount / batchDocuments.length) * 100)
                : 0;

              return (
                <div key={batch_id}>
                  <div className="flex items-center justify-between gap-3 text-sm">
                    <h3 className="font-semibold text-slate-800">업로드 묶음</h3>
                    <span className="text-slate-600">
                      처리 결과 {settledCount}/{batchDocuments.length}건 ({progress}%)
                    </span>
                  </div>
                  <progress
                    className="mt-2 h-2 w-full accent-indigo-600"
                    value={settledCount}
                    max={batchDocuments.length || 1}
                    aria-label="문서 처리 진행률"
                  />
                  <ul className="mt-2 divide-y divide-slate-100 rounded-lg border border-slate-200">
                    {batchDocuments.map((document) => (
                      <li
                        key={document.doc_id}
                        className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-slate-800">
                            {document.doc_name}
                          </p>
                          {document.doc_error && (
                            <p className="mt-1 break-all text-xs text-slate-500">
                              {document.doc_status === DOC_STATUS.DUPLICATE
                                ? "기존 문서 ID: " + document.doc_error
                                : document.doc_error}
                            </p>
                          )}
                        </div>
                        <span
                          className={
                            "shrink-0 self-start rounded-full px-3 py-1 text-xs font-bold sm:self-auto " +
                            (document.doc_status === DOC_STATUS.COMPLETED
                              ? "bg-emerald-100 text-emerald-800"
                              : document.doc_status === DOC_STATUS.UPLOADED ||
                                document.doc_status === DOC_STATUS.PROCESSING
                              ? "bg-indigo-100 text-indigo-800"
                              : document.doc_status === DOC_STATUS.DUPLICATE
                              ? "bg-amber-100 text-amber-800"
                              : "bg-rose-100 text-rose-800")
                          }
                        >
                          {DOC_STATUS_LABELS[document.doc_status]}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="mt-2 text-sm text-slate-500">아직 등록한 PDF가 없습니다.</p>
        )}
      </div>
    </section>
  );
}
