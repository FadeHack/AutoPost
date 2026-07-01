"use client";

import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { ToastProvider } from "@/components/ui/Toast";
import { BrandSwitcher } from "./BrandSwitcher";
import { CommandBar } from "./CommandBar";
import { MobileTopBar } from "./MobileTopBar";
import { NavRail, MobileTabBar } from "./NavRail";
import { TokenHealthPill } from "./TokenHealthPill";

const RAIL_KEY = "autopost:rail-collapsed";

// The rail collapse is user-controlled and persisted — not a pure media query.
// On first visit (no saved choice) we collapse below the desktop breakpoint so
// tablets start icon-only, but the user can pin either state at any width.
function initialCollapsed(): boolean {
  // The shell only mounts client-side (it's gated on a resolved session), so a
  // lazy initializer is safe and avoids a setState-in-effect cascade.
  if (typeof window === "undefined") return false;
  const stored = window.localStorage.getItem(RAIL_KEY);
  if (stored === "1") return true;
  if (stored === "0") return false;
  return !window.matchMedia("(min-width: 1280px)").matches;
}

function useRail() {
  const [collapsed, setCollapsed] = useState<boolean>(initialCollapsed);

  const toggle = useCallback(() => {
    setCollapsed((c) => {
      const next = !c;
      window.localStorage.setItem(RAIL_KEY, next ? "1" : "0");
      return next;
    });
  }, []);

  return { collapsed, toggle };
}

function CollapseGlyph({ collapsed }: { collapsed: boolean }) {
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
      {/* Panel outline + a chevron pointing the way the rail will move. */}
      <rect x="3" y="4" width="14" height="12" rx="1.5" />
      <path d="M8 4v12" />
      {collapsed ? (
        <path d="M11.5 7.5 14 10l-2.5 2.5" />
      ) : (
        <path d="M6 7.5 3.5 10 6 12.5" />
      )}
    </svg>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { session, signOut } = useAuth();
  const { collapsed, toggle } = useRail();
  const [peeking, setPeeking] = useState(false);

  // Keyboard shortcut: `[` toggles the rail, but never while typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "[" || e.metaKey || e.ctrlKey || e.altKey) return;
      const el = document.activeElement as HTMLElement | null;
      if (
        el &&
        (el.tagName === "INPUT" ||
          el.tagName === "TEXTAREA" ||
          el.isContentEditable)
      )
        return;
      e.preventDefault();
      toggle();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [toggle]);

  // Bare layout for the login route and any unauthenticated state — the rail is
  // meaningless without a session, and protected pages handle their own redirect.
  if (pathname === "/login" || !session) {
    return <>{children}</>;
  }

  const email = session.user.email ?? "";
  const initial = email.charAt(0).toUpperCase() || "·";

  // `expanded` = the display state (pinned-open OR peeking on hover). Children
  // take a `collapsed` prop, so they follow the display state, not the pin.
  const expanded = !collapsed || peeking;

  return (
    <ToastProvider>
      <MobileTopBar />
      <div className="flex h-screen overflow-hidden pt-14 md:pt-0">
        <aside
          onMouseEnter={() => collapsed && setPeeking(true)}
          onMouseLeave={() => setPeeking(false)}
          className={
            "relative z-30 hidden h-screen shrink-0 transition-[width] duration-200 ease-out md:block " +
            (collapsed ? "w-16" : "w-60")
          }
        >
          {/* When collapsed the aside reserves only the icon width; the hover
              peek renders this panel as an opaque overlay so content never
              shifts under it. */}
          <div
            className={
              "flex h-screen flex-col border-r border-border px-2.5 py-3 " +
              (peeking
                ? "absolute inset-y-0 left-0 w-60 bg-surface-1 shadow-2xl shadow-black/50"
                : "w-full bg-surface-1/40")
            }
          >
            <BrandSwitcher collapsed={!expanded} />

            <div className="mt-4 flex-1 overflow-y-auto">
              <NavRail collapsed={!expanded} />
            </div>

            <div className="mt-2 space-y-2 border-t border-border pt-2">
              <button
                onClick={toggle}
                title={collapsed ? "Expand sidebar  [" : "Collapse sidebar  ["}
                className={
                  "flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-sm text-ink-mid transition-colors hover:bg-surface-1 hover:text-ink-hi " +
                  (expanded ? "" : "justify-center")
                }
              >
                <CollapseGlyph collapsed={collapsed} />
                {expanded && (
                  <span className="truncate">
                    {collapsed ? "Expand" : "Collapse"}
                  </span>
                )}
                {expanded && (
                  <kbd className="ml-auto rounded border border-border px-1 text-[10px] text-ink-lo">
                    [
                  </kbd>
                )}
              </button>

              <TokenHealthPill collapsed={!expanded} />

              {!expanded ? (
                <button
                  onClick={signOut}
                  title={`${email} — sign out`}
                  className="flex w-full items-center justify-center py-1.5"
                >
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-surface-2 text-xs text-ink-mid">
                    {initial}
                  </span>
                </button>
              ) : (
                <div className="flex items-center gap-2 px-1">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-2 text-xs text-ink-mid">
                    {initial}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-xs text-ink-lo">
                    {email}
                  </span>
                  <button
                    onClick={signOut}
                    className="shrink-0 text-xs text-ink-lo transition-colors hover:text-ink-hi"
                  >
                    Sign out
                  </button>
                </div>
              )}
            </div>
          </div>
        </aside>

        {/* The single scroll container. Simple pages scroll here; board/list
            pages fill the height (h-full) and scroll their own inner regions so
            their headers stay put instead of scrolling the whole page. */}
        <div className="min-w-0 flex-1 overflow-y-auto pb-20 md:pb-0">
          {children}
        </div>

        <MobileTabBar />
      </div>
      <CommandBar />
    </ToastProvider>
  );
}
