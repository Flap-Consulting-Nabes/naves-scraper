"use client";

import { useState } from "react";
import { Play, Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "./status-badge";
import { useScraperStatus } from "@/hooks/use-scraper-status";
import { runScraper } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import { toast } from "sonner";

export function ScraperCard() {
  const { status, isLoading, needsRenewal, mutate } = useScraperStatus();
  const [restarting, setRestarting] = useState(false);

  async function handleRestart() {
    setRestarting(true);
    try {
      await runScraper({ max_pages: 0, dry_run: false, reset: false });
      toast.success("Scraper iniciado.");
      mutate();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setRestarting(false);
    }
  }

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-32" />
        </CardHeader>
        <CardContent className="space-y-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </CardContent>
      </Card>
    );
  }

  const canRestart =
    (status?.state === "error" || status?.state === "stopped") && !needsRenewal;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between border-b pb-3">
        <CardTitle>Estado del scraper</CardTitle>
        <StatusBadge state={status?.state ?? "idle"} />
      </CardHeader>
      <CardContent className="pt-3 space-y-2 text-sm">
        {status?.state === "running" && (
          <>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Página actual</span>
              <span className="font-medium">{status.current_page ?? "—"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Nuevos</span>
              <span className="font-medium text-emerald-600">{status.total_new ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Omitidos</span>
              <span className="font-medium">{status.total_skipped ?? 0}</span>
            </div>
          </>
        )}
        {status?.started_at && (
          <div className="flex justify-between">
            <span className="text-muted-foreground">Iniciado</span>
            <span>{formatDate(status.started_at)}</span>
          </div>
        )}
        {status?.finished_at && (
          <div className="flex justify-between">
            <span className="text-muted-foreground">Finalizado</span>
            <span>{formatDate(status.finished_at)}</span>
          </div>
        )}
        {status?.last_error && (
          <p className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {status.last_error}
          </p>
        )}
        {(!status || status.state === "idle") && !status?.last_error && (
          <p className="text-muted-foreground">Sin actividad reciente.</p>
        )}
        {canRestart && (
          <Button
            size="sm"
            variant="outline"
            onClick={handleRestart}
            disabled={restarting}
            className="gap-1.5 w-full mt-1"
          >
            {restarting ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Play className="size-4" />
            )}
            Iniciar scraper
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
