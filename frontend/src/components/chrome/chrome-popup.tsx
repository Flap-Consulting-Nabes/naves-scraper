"use client";

import { useCallback, useRef, useState } from "react";
import dynamic from "next/dynamic";
import type { VncScreenHandle } from "react-vnc";
import { Monitor } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";

const VncScreen = dynamic(
  () => import("react-vnc").then((mod) => mod.VncScreen),
  { ssr: false }
);

interface ChromePopupProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  wsPort: number;
}

export function ChromePopup({ open, onOpenChange, wsPort }: ChromePopupProps) {
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const vncRef = useRef<VncScreenHandle | null>(null);

  const wsUrl = typeof window !== "undefined"
    ? `ws://${window.location.hostname}:${wsPort}`
    : "";

  const handleConnect = useCallback(() => {
    setConnected(true);
    setError(null);
  }, []);

  const handleDisconnect = useCallback(() => {
    setConnected(false);
  }, []);

  const handleError = useCallback(() => {
    setError("No se pudo conectar al panel Chrome. Verifica que x11vnc y websockify estan activos.");
    setConnected(false);
  }, []);

  const handleOpenChange = useCallback((nextOpen: boolean) => {
    if (!nextOpen) {
      try {
        vncRef.current?.disconnect();
      } catch {
        // ignore
      }
      setConnected(false);
      setError(null);
    }
    onOpenChange(nextOpen);
  }, [onOpenChange]);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        style={{
          position: "fixed",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: "90vw",
          height: "90vh",
          maxWidth: "90vw",
          borderRadius: "0.75rem",
        }}
        className="z-50 flex flex-col gap-0 border shadow-2xl ring-1 ring-black/10 p-0 overflow-hidden"
        showCloseButton={false}
      >
        <div className="flex items-center justify-between border-b bg-background px-4 py-2 rounded-t-xl">
          <div className="flex items-center gap-2">
            <Monitor className="size-4" />
            <DialogTitle>Chrome remoto</DialogTitle>
            {connected && (
              <span className="text-xs text-emerald-600 dark:text-emerald-400">
                conectado
              </span>
            )}
          </div>
          <button
            onClick={() => handleOpenChange(false)}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
            <span className="sr-only">Cerrar</span>
          </button>
        </div>

        <div className="flex-1 overflow-hidden bg-[#1a1a1a] rounded-b-xl" style={{ minHeight: 0 }}>
          {error ? (
            <div className="flex items-center justify-center h-full p-4 text-sm text-destructive">
              {error}
            </div>
          ) : (
            open && wsUrl && (
              <VncScreen
                url={wsUrl}
                scaleViewport
                background="#1a1a1a"
                style={{ width: "100%", height: "100%" }}
                onConnect={handleConnect}
                onDisconnect={handleDisconnect}
                onSecurityFailure={handleError}
                ref={vncRef}
              />
            )
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
