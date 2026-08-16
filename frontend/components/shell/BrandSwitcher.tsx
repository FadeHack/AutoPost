"use client";

import { useEffect, useRef, useState } from "react";

import { useMe } from "@/lib/useMe";

// The multi-company seam (DESIGN.md §2). Reads the caller's real workspace name
// off `GET /me` rather than a hardcoded brand — Phase 14 shipped real per-user
// tenant isolation (`workspaces`), but each user still gets exactly one
// workspace, so switching between several brands isn't a built feature yet.
// This renders what's actually true (your one real workspace) instead of
// implying a working multi-brand switcher; "Add brand" stays an honest,
// disabled-looking placeholder for the day membership-per-workspace lands.

export function BrandSwitcher({ collapsed = false }: { collapsed?: boolean }) {
  const { me } = useMe();
  const brandName = me?.workspace_name ?? "…";
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
        title={`${brandName} — switch brand`}
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent font-display text-sm text-accent-ink">
          {brandName[0]}
        </span>
        {!collapsed && (
          <>
            <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink-hi">
              {brandName}
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
            <span className="flex h-6 w-6 items-center justify-center rounded bg-accent font-display text-xs text-accent-ink">
              {brandName[0]}
            </span>
            <span className="flex-1 truncate text-ink-hi">{brandName}</span>
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
