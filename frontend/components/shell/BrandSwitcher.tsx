"use client";

import { useEffect, useRef, useState } from "react";

// The multi-company seam (DESIGN.md §2). One static brand today — the value is
// that the app is structured "inside a brand", so brand #2 is a dropdown entry,
// not an IA redesign. Real tenant isolation is deferred to Phase 14.
const CURRENT_BRAND = "Nestwhirr";

export function BrandSwitcher({ collapsed = false }: { collapsed?: boolean }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2.5 rounded-md px-2 py-2 text-left transition-colors hover:bg-surface-2"
        title={`${CURRENT_BRAND} — switch brand`}
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent font-serif text-sm text-accent-ink">
          {CURRENT_BRAND[0]}
        </span>
        {!collapsed && (
          <>
            <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink-hi">
              {CURRENT_BRAND}
            </span>
            <svg
              className="h-3.5 w-3.5 shrink-0 text-ink-lo"
              viewBox="0 0 12 12"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.4"
            >
              <path d="M3 4.5 6 7.5 9 4.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </>
        )}
      </button>

      {open && !collapsed && (
        <div className="absolute left-0 right-0 top-full z-30 mt-1 overflow-hidden rounded-md border border-border bg-surface-1 shadow-2xl shadow-black/60">
          <div className="flex items-center gap-2.5 px-2.5 py-2 text-sm">
            <span className="flex h-6 w-6 items-center justify-center rounded bg-accent font-serif text-xs text-accent-ink">
              {CURRENT_BRAND[0]}
            </span>
            <span className="flex-1 truncate text-ink-hi">{CURRENT_BRAND}</span>
            <span className="text-accent">✓</span>
          </div>
          <div className="border-t border-border px-2.5 py-2 text-xs text-ink-lo">
            Add brand — coming soon
          </div>
        </div>
      )}
    </div>
  );
}
