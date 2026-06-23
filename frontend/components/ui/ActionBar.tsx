import type { ReactNode } from "react";

// The persistent draft action row (DESIGN.md §4/§5C). Presentational primitives
// only — the cockpit (Chunk C) composes these into the status-aware
// Edit/Render/Approve/Schedule/Publish bar. `ActionBar` is the sticky container;
// `ActionButton` carries the visual weight per action.

export function ActionBar({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={
        "sticky bottom-0 z-20 flex flex-wrap items-center gap-2 border-t border-border bg-surface-1/85 px-4 py-3 backdrop-blur " +
        className
      }
    >
      {children}
    </div>
  );
}

type Variant = "primary" | "secondary" | "danger" | "ghost";

const VARIANT: Record<Variant, string> = {
  // Accent = the parchment fill; the single highest-emphasis action (Approve).
  primary:
    "bg-accent text-accent-ink hover:bg-accent/90 disabled:bg-surface-2 disabled:text-ink-lo",
  secondary:
    "border border-border bg-surface-2 text-ink-hi hover:bg-surface-1 disabled:text-ink-lo",
  danger:
    "border border-status-failed/40 bg-status-failed/10 text-status-failed hover:bg-status-failed/20 disabled:opacity-50",
  ghost:
    "text-ink-mid hover:bg-surface-1 hover:text-ink-hi disabled:text-ink-lo",
};

export function ActionButton({
  children,
  onClick,
  variant = "secondary",
  disabled = false,
  loading = false,
  title,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: Variant;
  disabled?: boolean;
  loading?: boolean;
  title?: string;
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      title={title}
      className={
        "inline-flex items-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed " +
        VARIANT[variant]
      }
    >
      {loading && (
        <span className="h-3.5 w-3.5 animate-spin rounded-full border-[1.5px] border-current border-t-transparent" />
      )}
      {children}
    </button>
  );
}
