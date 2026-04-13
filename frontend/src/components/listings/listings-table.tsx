import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { ChevronLeft, ChevronRight, ExternalLink } from "lucide-react";
import type { Listing, ListingsResponse } from "@/lib/types";
import { formatCurrency, formatDate, formatNumber } from "@/lib/utils";

interface Props {
  data: ListingsResponse | undefined;
  isLoading: boolean;
  page: number;
  onPageChange: (p: number) => void;
}

export function ListingsTable({ data, isLoading, page, onPageChange }: Props) {
  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  const listings = data?.items ?? [];
  const total = data?.total ?? 0;
  const pageSize = data?.page_size ?? 50;
  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="space-y-3">
      <div className="text-xs text-muted-foreground">
        {total} anuncios encontrados
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Titulo</TableHead>
            <TableHead>Provincia</TableHead>
            <TableHead className="text-right">Superficie</TableHead>
            <TableHead className="text-right">Precio</TableHead>
            <TableHead className="text-right">Publicado</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {listings.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="py-8 text-center text-muted-foreground">
                Sin resultados
              </TableCell>
            </TableRow>
          ) : (
            listings.map((l: Listing) => (
              <TableRow key={l.listing_id}>
                <TableCell className="max-w-xs truncate font-medium">{l.title ?? "\u2014"}</TableCell>
                <TableCell>{l.province ?? "—"}</TableCell>
                <TableCell className="text-right">
                  {l.surface_m2 != null ? `${formatNumber(l.surface_m2)} m2` : "—"}
                </TableCell>
                <TableCell className="text-right">
                  {l.price_numeric != null ? formatCurrency(l.price_numeric) : "—"}
                </TableCell>
                <TableCell className="text-right text-muted-foreground">
                  {formatDate(l.published_at)}
                </TableCell>
                <TableCell>
                  {l.url && (
                    <a
                      href={l.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                    >
                      <ExternalLink className="size-3" />
                    </a>
                  )}
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>

      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">
            Página {page} de {totalPages}
          </span>
          <div className="flex gap-1">
            <Button
              size="icon-sm"
              variant="outline"
              disabled={page <= 1}
              onClick={() => onPageChange(page - 1)}
            >
              <ChevronLeft className="size-4" />
            </Button>
            <Button
              size="icon-sm"
              variant="outline"
              disabled={page >= totalPages}
              onClick={() => onPageChange(page + 1)}
            >
              <ChevronRight className="size-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
