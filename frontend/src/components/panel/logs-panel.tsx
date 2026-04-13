"use client";

import { useState } from "react";
import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LogViewer } from "@/components/logs/log-viewer";
import { fetcher } from "@/lib/api";

interface LogsResponse {
  lines: string[];
}

interface LogsPanelProps {
  isActive: boolean;
}

export function LogsPanel({ isActive }: LogsPanelProps) {
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [limit, setLimit] = useState(200);

  const { data } = useSWR<LogsResponse>(
    `/api/logs?lines=${limit}`,
    fetcher,
    {
      refreshInterval: autoRefresh && isActive ? 3000 : 0,
      revalidateOnFocus: true,
    }
  );

  return (
    <Card>
      <CardHeader className="border-b pb-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <CardTitle>Registros</CardTitle>
            {isActive && autoRefresh && (
              <span className="text-xs text-emerald-600 dark:text-emerald-400">
                actualizando...
              </span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <Label htmlFor="log-limit" className="text-sm">Líneas</Label>
              <Input
                id="log-limit"
                type="number"
                min={50}
                max={1000}
                step={50}
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value))}
                className="w-20"
              />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={autoRefresh}
                onCheckedChange={(v) => setAutoRefresh(!!v)}
              />
              Auto-actualizar
            </label>
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-4">
        <div className="max-h-[400px] overflow-y-auto">
          <LogViewer lines={data?.lines ?? []} />
        </div>
      </CardContent>
    </Card>
  );
}
