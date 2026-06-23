"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { ToastProvider } from "@/components/ui/Toast";
import { BrandSwitcher } from "./BrandSwitcher";
import { CommandBar } from "./CommandBar";
import { NavRail, MobileTabBar } from "./NavRail";
import { TokenHealthPill } from "./TokenHealthPill";

// Collapses the rail to icon-only below 1280px (tablet). Safe to use a media
// query here because the shell only renders for an authenticated session, which
// is resolved client-side — the rail never renders on the server.
function useWideRail(): boolean {
  const [wide, setWide] = useState(true);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1280px)");
    const apply = () => setWide(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);
  return wide;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { session, signOut } = useAuth();
  const wide = useWideRail();
  const collapsed = !wide;

  // Bare layout for the login route and any unauthenticated state — the rail is
  // meaningless without a session, and protected pages handle their own redirect.
  if (pathname === "/login" || !session) {
    return <>{children}</>;
  }

  const email = session.user.email ?? "";
  const initial = email.charAt(0).toUpperCase() || "·";

  return (
    <ToastProvider>
      <div className="flex min-h-screen">
        <aside
        className={
          "sticky top-0 hidden h-screen shrink-0 flex-col border-r border-border bg-surface-1/40 px-2.5 py-3 md:flex " +
          (collapsed ? "w-16 items-stretch" : "w-60")
        }
      >
        <BrandSwitcher collapsed={collapsed} />

        <div className="mt-4 flex-1 overflow-y-auto">
          <NavRail collapsed={collapsed} />
        </div>

        <div className="mt-2 space-y-2 border-t border-border pt-2">
          <TokenHealthPill collapsed={collapsed} />

          {collapsed ? (
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
      </aside>

        {/* Pages own their own <main>; this is just the content column. */}
        <div className="min-w-0 flex-1 pb-20 md:pb-0">{children}</div>

        <MobileTabBar />
      </div>
      <CommandBar />
    </ToastProvider>
  );
}
