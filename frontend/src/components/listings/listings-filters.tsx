"use client";

import useSWR from "swr";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { X } from "lucide-react";
import { fetcher } from "@/lib/api";

export interface ListingFilters {
  province: string;
  min_surface: string;
  max_price: string;
  page: number;
}

interface ProvincesResponse {
  provinces: string[];
}

interface Props {
  filters: ListingFilters;
  onChange: (f: Partial<ListingFilters>) => void;
}

export function ListingsFilters({ filters, onChange }: Props) {
  const { data } = useSWR<ProvincesResponse>(
    "/api/listings/provinces",
    fetcher,
    { revalidateOnFocus: false }
  );

  const provinces = data?.provinces ?? [];

  function reset() {
    onChange({ province: "", min_surface: "", max_price: "", page: 1 });
  }

  const hasFilters = filters.province || filters.min_surface || filters.max_price;

  return (
    <div className="flex flex-wrap items-end gap-3">
      {/* Provincia */}
      <div className="space-y-1">
        <Label>Provincia</Label>
        <Select
          value={filters.province || "__all__"}
          onValueChange={(v) => onChange({ province: v === "__all__" ? "" : (v ?? ""), page: 1 })}
        >
          <SelectTrigger className="w-44">
            <SelectValue placeholder="Todas" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">Todas</SelectItem>
            {provinces.map((p) => (
              <SelectItem key={p} value={p}>{p}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Superficie min */}
      <div className="space-y-1">
        <Label>Superficie min (m2)</Label>
        <Input
          type="number"
          className="w-28"
          placeholder="0"
          value={filters.min_surface}
          onChange={(e) => onChange({ min_surface: e.target.value, page: 1 })}
        />
      </div>

      {/* Precio max */}
      <div className="space-y-1">
        <Label>Precio max (EUR)</Label>
        <Input
          type="number"
          className="w-28"
          placeholder="—"
          value={filters.max_price}
          onChange={(e) => onChange({ max_price: e.target.value, page: 1 })}
        />
      </div>

      {hasFilters && (
        <Button variant="ghost" size="sm" onClick={reset} className="gap-1">
          <X className="size-3.5" />
          Limpiar
        </Button>
      )}
    </div>
  );
}
