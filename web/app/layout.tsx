import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Sidebar } from "@/components/sidebar";
import { AutoRefresh } from "@/components/auto-refresh";
import "./globals.css";

export const metadata: Metadata = {
  title: "TreadingBot Dashboard",
  description: "Paper trading operations dashboard for TreadingBot"
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <Sidebar />
          <main className="content">
            <AutoRefresh interval={60000} />
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
