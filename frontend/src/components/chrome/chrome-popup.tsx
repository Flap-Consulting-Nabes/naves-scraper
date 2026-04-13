"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import dynamic from "next/dynamic";
import type { VncScreenHandle } from "react-vnc";
import { Monitor, X } from "lucide-react";

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
  const [dims, setDims] = useState({ w: 0, h: 0 });
  const vncRef = useRef<VncScreenHandle | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const wsUrl = typeof window !== "undefined"
    ? `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.hostname}:${wsPort}`
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

  const handleClose = useCallback(() => {
    try {
      vncRef.current?.disconnect();
    } catch {
      // ignore
    }
    setConnected(false);
    setError(null);
    onOpenChange(false);
  }, [onOpenChange]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") handleClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, handleClose]);

  useEffect(() => {
    if (!open) {
      setDims({ w: 0, h: 0 });
      return;
    }
    const el = containerRef.current;
    if (!el) return;

    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setDims({ w: Math.floor(width), h: Math.floor(height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [open]);

  if (!open) return null;

  return createPortal(
    <>
      {/* Backdrop — 100% inline styles */}
      <div
        onClick={handleClose}
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          zIndex: 9998,
          backgroundColor: "rgba(0, 0, 0, 0.5)",
          backdropFilter: "blur(2px)",
        }}
      />

      {/* Popup — 100% inline styles for positioning */}
      <div
        style={{
          position: "fixed",
          zIndex: 9999,
          top: "2.5vh",
          left: "2.5vw",
          width: "95vw",
          height: "95vh",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          borderRadius: "12px",
          border: "1px solid rgba(0, 0, 0, 0.1)",
          boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.25)",
          backgroundColor: "var(--popover, #fff)",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "8px 16px",
            borderBottom: "1px solid rgba(0, 0, 0, 0.1)",
            backgroundColor: "var(--background, #fff)",
            flexShrink: 0,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <Monitor style={{ width: 16, height: 16 }} />
            <span style={{ fontSize: "16px", fontWeight: 500 }}>Chrome remoto</span>
            {connected && (
              <span style={{ fontSize: "12px", color: "#059669" }}>conectado</span>
            )}
          </div>
          <button
            onClick={handleClose}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: "6px",
              borderRadius: "6px",
              border: "none",
              background: "transparent",
              cursor: "pointer",
              color: "inherit",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "rgba(0,0,0,0.05)")}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
          >
            <X style={{ width: 16, height: 16 }} />
          </button>
        </div>

        {/* VNC area */}
        <div
          ref={containerRef}
          style={{
            flex: 1,
            overflow: "hidden",
            backgroundColor: "#1a1a1a",
            minHeight: 0,
          }}
        >
          {error ? (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                height: "100%",
                padding: "16px",
                fontSize: "14px",
                color: "#ef4444",
              }}
            >
              {error}
            </div>
          ) : (
            wsUrl && dims.w > 0 && dims.h > 0 && (
              <VncScreen
                url={wsUrl}
                scaleViewport
                background="#1a1a1a"
                style={{ width: `${dims.w}px`, height: `${dims.h}px` }}
                onConnect={handleConnect}
                onDisconnect={handleDisconnect}
                onSecurityFailure={handleError}
                ref={vncRef}
              />
            )
          )}
        </div>
      </div>
    </>,
    document.body
  );
}
