"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Play, Square, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { runScraper, stopScraper } from "@/lib/api";
import { useScraperStatus } from "@/hooks/use-scraper-status";
import { useState } from "react";

const schema = z.object({
  max_pages: z.number().int().min(0),
  dry_run: z.boolean(),
  reset: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

export function RunForm() {
  const { status, isRunning, mutate } = useScraperStatus();
  const [stopping, setStopping] = useState(false);

  const { register, handleSubmit, watch, setValue, formState: { isSubmitting } } =
    useForm<FormValues>({
      resolver: zodResolver(schema),
      defaultValues: { max_pages: 0, dry_run: false, reset: false },
    });

  const dryRun = watch("dry_run");
  const reset = watch("reset");

  async function onSubmit(values: FormValues) {
    try {
      await runScraper(values);
      toast.success("Scraper iniciado.");
      mutate();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function handleStop() {
    setStopping(true);
    try {
      await stopScraper();
      toast.info("Deteniendo scraper...");
      mutate();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setStopping(false);
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="max_pages">Páginas máximas</Label>
        <Input
          id="max_pages"
          type="number"
          min={0}
          {...register("max_pages", { valueAsNumber: true })}
          className="w-32"
        />
        <p className="text-xs text-muted-foreground">0 = sin límite</p>
      </div>

      <div className="flex flex-col gap-2">
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={dryRun}
            onCheckedChange={(v) => setValue("dry_run", !!v)}
          />
          Modo prueba (sin escritura en BD)
        </label>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={reset}
            onCheckedChange={(v) => setValue("reset", !!v)}
          />
          Reiniciar desde página 1 (ignorar checkpoint)
        </label>
      </div>

      <div className="flex gap-2">
        <Button
          type="submit"
          disabled={isRunning || isSubmitting}
          className="gap-1.5"
        >
          {isSubmitting ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Play className="size-4" />
          )}
          Iniciar
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={!isRunning || stopping}
          onClick={handleStop}
          className="gap-1.5"
        >
          {stopping ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Square className="size-4" />
          )}
          Detener
        </Button>
      </div>

      {status?.pid && isRunning && (
        <p className="text-xs text-muted-foreground">PID: {status.pid}</p>
      )}
    </form>
  );
}
