import { useTranslation } from 'react-i18next';
import { WifiOff, RefreshCw } from "lucide-react";
import type { SSEStatus } from "@/hooks/useSSE";

interface Props {
  status: SSEStatus;
  retryAttempt?: number;
}

export function ConnectionBanner({ status, retryAttempt }: Props) {
  const { t } = useTranslation();
  // "disconnected" is the store's boot state and the deliberate-teardown state
  // (navigating away from a session) — neither is a connection loss, so only
  // an active reconnect loop may surface the banner.
  if (status !== "reconnecting") return null;
  const terminal = (retryAttempt ?? 0) >= 5;

  return (
    <div
      className="absolute inset-x-0 top-0 z-30 flex min-h-8 items-center gap-2 border-b border-warning/30 bg-warning/15 px-4 py-2 text-xs text-warning"
      role="status"
    >
      {!terminal ? (
        <>
          <RefreshCw className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          <span>{t('connection.reconnecting', { attempt: retryAttempt || 1 })}</span>
        </>
      ) : (
        <>
          <WifiOff className="h-3.5 w-3.5" aria-hidden="true" />
          <span>{t('connection.disconnected')}</span>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="ms-auto rounded-md border border-warning/40 px-2 py-0.5 font-medium transition-colors hover:bg-warning/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-warning/40"
          >
            {t('connection.reload' as never)}
          </button>
        </>
      )}
    </div>
  );
}
