import type { Metadata, Viewport } from "next";

import Aurora from "@/components/Aurora";

import "./globals.css";

export const metadata: Metadata = {
  title: "MERROR",
  description: "A private, local-first conversational mirror.",
};

export const viewport: Viewport = {
  // The gradient is dark; tell the browser so system chrome matches instead of
  // framing the page in white.
  themeColor: "#07070b",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="antialiased">
        <Aurora />
        {children}
      </body>
    </html>
  );
}
