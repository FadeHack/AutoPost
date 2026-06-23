import type { ReactNode } from "react";

// One inline alert, four tones — replaces the ~8 hand-rolled colored <div>
// banners in the old home page (DESIGN.md §4). Tones map to the semantic
// pipeline tokens so success/error read the same everywhere.

export type BannerTone = "success" | "error" | "warn" | "info";

const TONE: Record<BannerTone, string> = {
  success: "border-status-published/40 bg-status-published/10 text-status-published",
  error: "border-status-failed/40 bg-status-failed/10 text-status-failed",
  warn: "border-status-publishing/40 bg-status-publishing/10 text-status-publishing",
  info: "border-border bg-surface-1 text-ink-mid",
};

export function Banner({
  tone = "info",
  title,
  children,
  onDismiss,
  className = "",
}: {
  tone?: BannerTone;
  title?: ReactNode;
  children?: ReactNode;
  onDismiss?: () => void;
  className?: string;
}) {
  return (
    <div
      className={
        "flex items-start gap-3 rounded-md border p-3 text-sm " +
        TONE[tone] +
        (className ? " " + className : "")
      }
      role={tone === "error" ? "alert" : "status"}
    >
      <div className="min-w-0 flex-1">
        {title && <p className="font-medium">{title}</p>}
        {children && (
          <div className={"text-xs " + (title ? "mt-1 opacity-80" : "")}>
            {children}
          </div>
        )}
      </div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          aria-label="Dismiss"
          className="shrink-0 text-current opacity-60 transition-opacity hover:opacity-100"
        >
          <svg
            className="h-3.5 w-3.5"
            viewBox="0 0 14 14"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          >
            <path d="M3.5 3.5 10.5 10.5M10.5 3.5 3.5 10.5" />
          </svg>
        </button>
      )}
    </div>
  );
}
