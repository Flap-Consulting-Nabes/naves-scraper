"use client";

import { AlertTriangle, Loader2, Monitor, RefreshCw } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

interface CaptchaModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onViewChrome: () => void;
  onStopAndRenew: () => void;
  vncAvailable: boolean;
  starting: boolean;
}

export function CaptchaModal({
  open,
  onOpenChange,
  onViewChrome,
  onStopAndRenew,
  vncAvailable,
  starting,
}: CaptchaModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <div className="mx-auto mb-2 flex size-14 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-950/50">
            <AlertTriangle className="size-7 text-amber-600 dark:text-amber-400 animate-pulse" />
          </div>
          <DialogTitle className="text-center text-lg">
            Captcha detectado
          </DialogTitle>
          <DialogDescription className="text-center">
            El scraper ha encontrado un captcha que requiere resolución manual.
            Abre Chrome para resolver el captcha y continuar el scraping.
          </DialogDescription>
        </DialogHeader>

        <DialogFooter className="sm:flex-col sm:gap-2">
          {vncAvailable && (
            <Button
              onClick={onViewChrome}
              className="w-full gap-2 bg-amber-600 text-white hover:bg-amber-700 dark:bg-amber-600 dark:hover:bg-amber-700"
            >
              <Monitor className="size-4" />
              Ver Chrome
            </Button>
          )}
          <Button
            variant="outline"
            onClick={onStopAndRenew}
            disabled={starting}
            className="w-full gap-2"
          >
            {starting ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <RefreshCw className="size-4" />
            )}
            Parar y renovar sesión
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
