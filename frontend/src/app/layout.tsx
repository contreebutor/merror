import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MERROR",
  description: "A private, local-first conversational mirror.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
