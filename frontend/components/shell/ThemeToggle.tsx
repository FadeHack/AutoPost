"use client";

import { useEffect, useState } from "react";
import { useTheme } from "./ThemeProvider";

// Sun / moon line-art glyphs — flat, hairline, matching the rail icon language.
function SunGlyph() {
  return (
    <svg
      className="h-[18px] w-[18px] shrink-0"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="10" cy="10" r="3.5" />
      <path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.5 4.5 6 6M14 14l1.5 1.5M15.5 4.5 14 6M6 14l-1.5 1.5" />
    </svg>
  );
}

function MoonGlyph() {
  return (
    <svg
      className="h-[18px] w-[18px] shrink-0"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M16 11.5A6.5 6.5 0 0 1 8.5 4a6.5 6.5 0 1 0 7.5 7.5Z" />
    </svg>
  );
}

/**
 * Theme toggle. `variant="rail"` renders a full-width labelled row (rail
 * footer); `variant="icon"` renders a compact square button (mobile bar / login).
 * Flips light ↔ dark; a first click from a "system" preference pins the opposite
 * of whatever is currently showing.
 */
export function ThemeToggle({
  variant = "rail",
  collapsed = false,
}: {
  variant?: "rail" | "icon";
  collapsed?: boolean;
}) {
  const { resolved, toggle } = useTheme();
  // The concrete theme is only known on the client (localStorage / system).
  // Until mounted, render a stable default so SSR and first client render agree.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const isDark = mounted ? resolved === "dark" : true;
  const next = isDark ? "light" : "dark";
  const label = `Switch to ${next} mode`;
  const Glyph = isDark ? MoonGlyph : SunGlyph;

  if (variant === "icon") {
    return (
      <button
        onClick={toggle}
        aria-label={label}
        title={label}
        className="flex h-9 w-9 items-center justify-center rounded-md text-ink-mid transition-colors hover:bg-surface-2 hover:text-ink-hi"
      >
        <Glyph />
      </button>
    );
  }

  return (
    <button
      onClick={toggle}
      title={label}
      className={
        "flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-sm text-ink-mid transition-colors hover:bg-surface-2 hover:text-ink-hi " +
        (collapsed ? "justify-center" : "")
      }
    >
      <Glyph />
      {!collapsed && <span className="truncate">{isDark ? "Dark" : "Light"}</span>}
      {!collapsed && (
        <span className="ml-auto text-[10px] uppercase tracking-wider text-ink-lo">
          {next}
        </span>
      )}
    </button>
  );
}
