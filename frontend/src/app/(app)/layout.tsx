"use client";

import { AuthGuard } from "@/lib/auth-guard";
import { Sidebar } from "@/components/layout/sidebar";
import { AlertBanner } from "@/components/layout/alert-banner";
import { ChromePopupProvider } from "@/providers/chrome-popup-provider";
import { ErrorBoundary } from "@/components/error-boundary";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <ChromePopupProvider>
        <div className="flex min-h-screen">
          <Sidebar />
          <div className="flex min-w-0 flex-1 flex-col sm:pl-64">
            <AlertBanner />
            <main className="min-w-0 flex-1 overflow-x-hidden p-4 sm:px-6">
              <ErrorBoundary>
                {children}
              </ErrorBoundary>
            </main>
          </div>
        </div>
      </ChromePopupProvider>
    </AuthGuard>
  );
}
