"use client";

import useSWR from "swr";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Save } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { fetcher, updateCron } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import type { CronConfig } from "@/lib/types";

const PRESETS = [
  { label: "Cada dia a las 6am", value: "0 6 * * *" },
  { label: "Cada dia a las 9am", value: "0 9 * * *" },
  { label: "Dos veces al dia (6am y 6pm)", value: "0 6,18 * * *" },
  { label: "Cada 12 horas", value: "0 */12 * * *" },
  { label: "Cada lunes a las 8am", value: "0 8 * * 1" },
  { label: "Personalizado", value: "custom" },
];

const schema = z.object({
  cron_expr: z.string().min(1),
  max_pages: z.number().int().min(0),
});

type FormValues = z.infer<typeof schema>;

export function CronCard() {
  const { data: config, mutate } = useSWR<CronConfig>("/api/cron", fetcher);

  const { register, handleSubmit, watch, setValue, reset, formState: { isSubmitting } } =
    useForm<FormValues>({
      resolver: zodResolver(schema),
      defaultValues: { cron_expr: "0 6 * * *", max_pages: 0 },
    });

  const cronExpr = watch("cron_expr");

  useEffect(() => {
    if (config) {
      reset({
        cron_expr: config.cron_expr,
        max_pages: config.max_pages ?? 0,
      });
    }
  }, [config, reset]);

  const selectedPreset =
    PRESETS.find((p) => p.value === cronExpr)?.value ?? "custom";

  function handlePresetChange(value: string | null) {
    if (value && value !== "custom") {
      setValue("cron_expr", value);
    }
  }

  async function onSubmit(values: FormValues) {
    try {
      await updateCron(values);
      toast.success("Programación actualizada.");
      mutate();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <Card>
      <CardHeader className="border-b pb-3">
        <CardTitle>Programación</CardTitle>
      </CardHeader>
      <CardContent className="pt-4">
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-1.5">
            <Label>Preset</Label>
            <Select value={selectedPreset} onValueChange={handlePresetChange}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Selecciona un preset" />
              </SelectTrigger>
              <SelectContent>
                {PRESETS.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="cron_expr">Expresión cron</Label>
            <Input id="cron_expr" {...register("cron_expr")} placeholder="0 6 * * *" />
            <p className="text-xs text-muted-foreground">
              Formato: minuto hora dia-mes mes dia-semana (zona: Europe/Madrid)
            </p>
          </div>

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

          {config?.next_run && (
            <p className="text-sm text-muted-foreground">
              Próxima ejecución: <strong>{formatDate(config.next_run)}</strong>
            </p>
          )}

          <Button type="submit" disabled={isSubmitting} className="gap-1.5">
            <Save className="size-4" />
            Guardar
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
