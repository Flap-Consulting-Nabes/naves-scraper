"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { ListingsFilters, type ListingFilters } from "@/components/listings/listings-filters";
import { ListingsTable } from "@/components/listings/listings-table";
import type { ListingsResponse } from "@/lib/types";

function buildQuery(f: ListingFilters) {
  const p = new URLSearchParams();
  if (f.province) p.set("province", f.province);
  if (f.min_surface) p.set("min_surface", f.min_surface);
  if (f.max_price) p.set("max_price", f.max_price);
  p.set("page", String(f.page));
  return p.toString();
}

const DEFAULT_FILTERS: ListingFilters = {
  province: "",
  min_surface: "",
  max_price: "",
  page: 1,
};

export default function AnunciosPage() {
  const [filters, setFilters] = useState<ListingFilters>(DEFAULT_FILTERS);

  function handleFilterChange(partial: Partial<ListingFilters>) {
    setFilters((prev) => ({ ...prev, ...partial }));
  }

  const query = buildQuery(filters);
  const { data, isLoading, error } = useSWR<ListingsResponse>(
    `/api/listings?${query}`,
    fetcher,
    { revalidateOnFocus: false }
  );

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Anuncios</h1>
      <ListingsFilters filters={filters} onChange={handleFilterChange} />
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-400">
          Error al cargar anuncios. Verifica que la API esta activa.
        </div>
      )}
      <ListingsTable
        data={data}
        isLoading={isLoading}
        page={filters.page}
        onPageChange={(p) => handleFilterChange({ page: p })}
      />
    </div>
  );
}
