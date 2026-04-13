"use client";

import { useEffect, useRef } from "react";

interface Props {
  lines: string[];
}

function lineClass(line: string): string {
  if (line.includes("ERROR") || line.includes("error") || line.includes("[SESSION_NAV:failed]") || line.includes("[WARMUP:nav_failed]"))
    return "text-red-500";
  if (line.includes("WARN") || line.includes("warn") || line.includes("[WARMUP:captcha_skip]") || line.includes("[SESSION_NAV:blank]"))
    return "text-yellow-600 dark:text-yellow-400";
  if (line.includes("[CAPTCHA_REQUIRED]") || line.includes("[CAPTCHA_WAITING]") || line.includes("[CAPTCHA_TIMEOUT]"))
    return "text-amber-600 dark:text-amber-400 font-medium";
  if (line.includes("[CAPTCHA_SOLVED]") || line.includes("[SESSION_SAVED]") || line.includes("[WARMUP:complete]") || line.includes("[WARMUP:captcha_ok]"))
    return "text-emerald-600 dark:text-emerald-400 font-medium";
  if (line.includes("[WARMUP:") || line.includes("[WARMUP_"))
    return "text-cyan-600 dark:text-cyan-400";
  if (line.includes("[SESSION_NAV:") || line.includes("[SESSION]") || line.includes("[SESSION_SAVED]") || line.includes("[LOGIN_WAITING]") || line.includes("[SESSION_TIMEOUT]"))
    return "text-blue-600 dark:text-blue-400";
  if (line.includes("INFO") || line.includes("info"))
    return "text-foreground";
  return "text-muted-foreground";
}

export function LogViewer({ lines }: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines.length]);

  return (
    <div className="relative rounded-lg border bg-muted/30">
      <pre className="p-4 text-xs leading-relaxed font-mono text-foreground whitespace-pre-wrap break-all">
        {lines.length === 0 ? (
          <span className="text-muted-foreground">Sin registros.</span>
        ) : (
          lines.map((line, i) => (
            <span key={i} className={lineClass(line)}>
              {line}
              {"\n"}
            </span>
          ))
        )}
        <div ref={endRef} />
      </pre>
    </div>
  );
}
