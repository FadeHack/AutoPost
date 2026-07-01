"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { BrandSwitcher } from "./BrandSwitcher";
import { TokenHealthPill } from "./TokenHealthPill";

// Mobile app bar (DESIGN.md §6). The bottom tab bar carries primary navigation;
// this carries everything else the rail holds but the tabs don't — brand
// switch, Settings, token health, and sign-out — so nothing in the rail is
// unreachable on a phone. `md:hidden`; the rail owns these from `md` up.

function GearGlyph() {
  return (
    <svg
      className="h-[18px] w-[18px]"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M10 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM10 2v2M10 16v2M3.5 10h-2M18.5 10h-2M5 5l-1.4-1.4M16.4 16.4 15 15M5 15l-1.4 1.4M16.4 3.6 15 5" />
    </svg>
  );
}

export function MobileTopBar() {
  const { session, signOut } = useAuth();
  const [menu, setMenu] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menu) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setMenu(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [menu]);

  if (!session) return null;

  const email = session.user.email ?? "";
  const initial = email.charAt(0).toUpperCase() || "·";

  return (
    <header className="fixed inset-x-0 top-0 z-40 flex h-14 items-center gap-2 border-b border-border bg-surface-1/95 px-3 backdrop-blur md:hidden">
      <div className="min-w-0 flex-1">
        <BrandSwitcher />
      </div>

      <TokenHealthPill collapsed />

      <Link
        href="/settings"
        aria-label="Settings"
        className="flex h-9 w-9 items-center justify-center rounded-md text-ink-mid transition-colors hover:bg-surface-2 hover:text-ink-hi"
      >
        <GearGlyph />
      </Link>

      <div ref={ref} className="relative">
        <button
          onClick={() => setMenu((v) => !v)}
          aria-label="Account"
          className="flex h-9 w-9 items-center justify-center"
        >
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-surface-2 text-xs text-ink-mid">
            {initial}
          </span>
        </button>

        {menu && (
          <div className="absolute right-0 top-full z-50 mt-1 w-52 overflow-hidden rounded-md border border-border bg-surface-1 shadow-2xl shadow-black/60">
            <div className="truncate px-3 py-2 text-xs text-ink-lo">{email}</div>
            <button
              onClick={signOut}
              className="w-full border-t border-border px-3 py-2 text-left text-sm text-ink-mid transition-colors hover:bg-surface-2 hover:text-ink-hi"
            >
              Sign out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
