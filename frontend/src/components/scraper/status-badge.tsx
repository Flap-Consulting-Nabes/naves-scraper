import { cn } from "@/lib/utils";

type ScraperState = "idle" | "running" | "error" | "stopped";

const configs: Record<ScraperState, { label: string; classes: string }> = {
  idle: {
    label: "Inactivo",
    classes: "bg-muted text-muted-foreground",
  },
  running: {
    label: "En ejecución",
    classes: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300",
  },
  error: {
    label: "Error",
    classes: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
  },
  stopped: {
    label: "Detenido",
    classes: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300",
  },
};

interface StatusBadgeProps {
  state: string;
  compact?: boolean;
}

export function StatusBadge({ state, compact }: StatusBadgeProps) {
  const cfg = configs[state as ScraperState] ?? configs.idle;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full font-medium",
        compact ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm",
        cfg.classes
      )}
    >
      <span
        className={cn(
          "rounded-full",
          compact ? "size-1.5" : "size-2",
          state === "running" ? "bg-current animate-pulse" : "bg-current opacity-70"
        )}
      />
      {cfg.label}
    </span>
  );
}
