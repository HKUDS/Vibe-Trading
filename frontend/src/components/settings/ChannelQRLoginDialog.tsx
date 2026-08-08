import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { Loader2, RotateCcw, X } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { useTranslation } from "react-i18next";
import type { ChannelQRLoginResponse } from "@/lib/api";

interface ChannelQRLoginDialogProps {
  open: boolean;
  channelName: string;
  login: ChannelQRLoginResponse | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onRetry: () => void;
}

export function ChannelQRLoginDialog({
  open,
  channelName,
  login,
  loading,
  error,
  onClose,
  onRetry,
}: ChannelQRLoginDialogProps) {
  const { t } = useTranslation();
  const closeRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (previouslyFocused?.isConnected) previouslyFocused.focus();
    };
  }, [open]);

  if (!open) return null;

  const status = login?.status;
  const canRetry = Boolean(error || status === "expired" || status === "failed");
  const statusText = status
    ? t(`settings.channels.qr.status.${status}`)
    : t("settings.channels.qr.preparing");

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="channel-qr-login-title"
        className="w-full max-w-sm rounded-2xl border bg-background p-5 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 id="channel-qr-login-title" className="text-base font-semibold">
              {t("settings.channels.qr.title", { channel: channelName })}
            </h2>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              {t("settings.channels.qr.description")}
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label={t("settings.channels.qr.close")}
            className="rounded-md p-1 text-muted-foreground transition hover:bg-muted hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-5 flex min-h-64 items-center justify-center rounded-xl border bg-white p-4">
          {login?.qr_content && status !== "authenticated" ? (
            <QRCodeSVG
              value={login.qr_content}
              size={224}
              level="M"
              marginSize={2}
              title={t("settings.channels.qr.codeTitle", { channel: channelName })}
            />
          ) : status === "authenticated" ? (
            <div className="text-center text-sm font-medium text-emerald-700">
              {t("settings.channels.qr.connected")}
            </div>
          ) : (
            <Loader2 className="h-8 w-8 animate-spin text-primary" aria-label={t("settings.channels.qr.preparing")} />
          )}
        </div>

        <div className="mt-4 text-center">
          <p aria-live="polite" className="text-sm font-medium">{error || login?.message || statusText}</p>
          {status === "scanned" && (
            <p className="mt-1 text-xs text-muted-foreground">{t("settings.channels.qr.confirmOnPhone")}</p>
          )}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          {canRetry && (
            <button
              type="button"
              onClick={onRetry}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
              {t("settings.channels.qr.retry")}
            </button>
          )}
          <button type="button" onClick={onClose} className="rounded-md border px-3 py-2 text-sm text-muted-foreground">
            {status === "authenticated" ? t("settings.channels.qr.done") : t("settings.channels.qr.cancel")}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
