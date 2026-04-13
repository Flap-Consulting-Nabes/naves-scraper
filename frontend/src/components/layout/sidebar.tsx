"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  List,
  LogOut,
  Menu,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth-context";
import { useScraperStatus } from "@/hooks/use-scraper-status";

const navItems = [
  { href: "/control", label: "Panel", icon: LayoutDashboard },
  { href: "/anuncios", label: "Anuncios", icon: List },
];

const stateColors: Record<string, string> = {
  running: "bg-emerald-500",
  error: "bg-red-500",
  stopped: "bg-yellow-500",
  idle: "bg-muted-foreground",
};

const stateLabels: Record<string, string> = {
  running: "En ejecución",
  error: "Error",
  stopped: "Detenido",
  idle: "Inactivo",
};

export function Sidebar() {
  const pathname = usePathname();
  const { logout } = useAuth();
  const { status } = useScraperStatus();
  const [mobileOpen, setMobileOpen] = useState(false);

  const state = status?.state ?? "idle";
  const dotColor = stateColors[state] ?? stateColors.idle;
  const stateLabel = stateLabels[state] ?? state;

  return (
    <>
      {/* Mobile hamburger */}
      <button
        onClick={() => setMobileOpen(true)}
        className="fixed left-3 top-3 z-50 flex size-10 items-center justify-center rounded-lg border bg-card sm:hidden"
        aria-label="Abrir menú"
      >
        <Menu className="size-5" />
      </button>

      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 sm:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar panel */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r bg-card transition-transform duration-200",
          mobileOpen ? "translate-x-0" : "-translate-x-full sm:translate-x-0"
        )}
      >
        {/* Header */}
        <div className="flex h-14 items-center border-b px-4">
          <span className="text-base font-semibold tracking-tight">Naves Scraper</span>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-0.5">
          {navItems.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || pathname.startsWith(href + "/");
            return (
              <Link
                key={href}
                href={href}
                onClick={() => setMobileOpen(false)}
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                  active
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                <Icon className="size-4 shrink-0" />
                {label}
              </Link>
            );
          })}
        </nav>

        {/* Status + Logout */}
        <div className="border-t px-4 py-3 space-y-2">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span
              className={cn("size-2 rounded-full shrink-0", dotColor, state === "running" && "animate-pulse")}
            />
            <span>{stateLabel}</span>
            {status?.challenge_waiting && (
              <span className="ml-auto font-medium text-amber-600">Captcha</span>
            )}
          </div>
          <button
            onClick={logout}
            className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <LogOut className="size-4" />
            Cerrar sesión
          </button>
        </div>
      </aside>
    </>
  );
}
