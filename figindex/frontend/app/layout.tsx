import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FigIndex - 도표·차트 자동 분류 색인 시스템",
  description: "PDF 문서 내 표·차트·다이어그램 전문 검색 및 갤러리 뷰어",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body className="antialiased font-sans">{children}</body>
    </html>
  );
}

