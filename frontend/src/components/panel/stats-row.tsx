"use client";

import useSWR from "swr";
import { Building2, CheckCircle, Clock, Globe } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useWebflowStatus } from "@/hooks/use-webflow-status";
import { fetcher } from "@/lib/api";
import { formatNumber } from "@/lib/utils";
import type { ListingsResponse } from "@/lib/types";

function StatCard({
  title,
  value,
  icon: Icon,
  isLoading,
}: {
  title: string;
  value: string | number;
  icon: React.ElementType;
  isLoading: boolean;
}) {
  return (
    <Card size="sm">
      <CardHeader className="flex-row items-center justify-between pb-1">
        <CardTitle className="text-sm text-muted-foreground font-normal">{title}</CardTitle>
        <Icon className="size-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-7 w-20" />
        ) : (
          <p className="text-2xl font-bold">{value}</p>
        )}
      </CardContent>
    </Card>
  );
}

export function StatsRow() {
  const { data: listingsData, isLoading: listingsLoading, error: listingsError } = useSWR<ListingsResponse>(
    "/api/listings?page_size=1",
    fetcher,
    { revalidateOnFocus: false }
  );
  const { webflow, isLoading: webflowLoading } = useWebflowStatus();

  if (listingsError) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-400">
        Error al cargar estadisticas. Verifica que la API esta activa.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      <StatCard
        title="Total anuncios"
        value={formatNumber(listingsData?.total)}
        icon={Building2}
        isLoading={listingsLoading}
      />
      <StatCard
        title="En Webflow"
        value={formatNumber(webflow?.synced)}
        icon={Globe}
        isLoading={webflowLoading}
      />
      <StatCard
        title="Pendientes sync"
        value={formatNumber(webflow?.pending)}
        icon={Clock}
        isLoading={webflowLoading}
      />
      <StatCard
        title="Total Webflow"
        value={formatNumber(webflow?.total)}
        icon={CheckCircle}
        isLoading={webflowLoading}
      />
    </div>
  );
}
