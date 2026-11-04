import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Decision Intelligence Simulator",
  description: "How a proactive enterprise AI agent observes, evaluates, decides and asks for help.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
