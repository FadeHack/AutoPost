"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { apiGet } from "@/lib/api";
import { useMe } from "@/lib/useMe";

// Navigation = a worklist (DESIGN.md §2). Badges surface "what needs me":
// Inbox = unconsumed trends, Drafts = posts in draft/failed awaiting action.

type NavItem = {
  href: string;
  label: string;
  icon: ReactNode;
  badge?: "inbox" | "drafts";
};

// Minimal line-art glyphs — flat, hairline, no emoji (DESIGN.md §3).
const I = {
  today: (
    <path d="M3 9.5 10 4l7 5.5V16a1 1 0 0 1-1 1h-3v-4H7v4H4a1 1 0 0 1-1-1V9.5Z" />
  ),
  inbox: (
    <path d="M3 12h3l1.5 2.5h5L14 12h3M3 12l2.5-7h9L17 12M3 12v4a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-4" />
  ),
  drafts: <path d="M4 16.5 14 6.5l-2.5-2.5L1.5 14v2.5H4ZM12 6l2 2" />,
  calendar: (
    <path d="M4 5h12a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1ZM3 9h14M7 3v3M13 3v3" />
  ),
  published: <path d="M4 10.5 8.5 15 16 5.5" />,
  settings: (
    <path d="M10 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM10 2v2M10 16v2M3.5 10h-2M18.5 10h-2M5 5l-1.4-1.4M16.4 16.4 15 15M5 15l-1.4 1.4M16.4 3.6 15 5" />
  ),
  // Shield — admin-only control surface.
  admin: <path d="M10 2.5 4 5v4.5c0 3.5 2.4 6.4 6 8 3.6-1.6 6-4.5 6-8V5l-6-2.5Z" />,
};

function Glyph({ d }: { d: ReactNode }) {
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
      {d}
    </svg>
  );
}

const NAV: NavItem[] = [
  { href: "/", label: "Today", icon: <Glyph d={I.today} /> },
  { href: "/trends", label: "Inbox", icon: <Glyph d={I.inbox} />, badge: "inbox" },
  { href: "/drafts", label: "Drafts", icon: <Glyph d={I.drafts} />, badge: "drafts" },
  { href: "/scheduled", label: "Calendar", icon: <Glyph d={I.calendar} /> },
  { href: "/published", label: "Published", icon: <Glyph d={I.published} /> },
  { href: "/settings", label: "Settings", icon: <Glyph d={I.settings} /> },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}

// Shared "needs me" counts, fetched once per shell mount.
function useWorklistBadges() {
  const [counts, setCounts] = useState<{ inbox: number; drafts: number }>({
    inbox: 0,
    drafts: 0,
  });

  useEffect(() => {
    let alive = true;
    // Aggregate counts, not full rows: two tiny calls instead of pulling up to
    // 300 PostRead/TrendRead rows (targets eager-loaded) on every shell mount.
    Promise.all([
      apiGet<{ unconsumed: number }>("/trends/stats").catch(() => ({
        unconsumed: 0,
      })),
      apiGet<{ draft: number; failed: number }>("/posts/stats").catch(() => ({
        draft: 0,
        failed: 0,
      })),
    ]).then(([trends, posts]) => {
      if (!alive) return;
      setCounts({
        inbox: trends.unconsumed ?? 0,
        drafts: (posts.draft ?? 0) + (posts.failed ?? 0),
      });
    });
    return () => {
      alive = false;
    };
  }, []);

  return counts;
}

function Badge({ n }: { n: number }) {
  if (n <= 0) return null;
  return (
    <span className="ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-surface-2 px-1.5 text-[11px] font-medium text-ink-mid">
      {n > 99 ? "99+" : n}
    </span>
  );
}

function RailLink({
  item,
  collapsed,
  n,
}: {
  item: NavItem;
  collapsed: boolean;
  n: number;
}) {
  const pathname = usePathname();
  const active = isActive(pathname, item.href);
  return (
    <Link
      href={item.href}
      title={collapsed ? item.label : undefined}
      className={
        "group relative flex items-center gap-3 rounded-md px-2.5 py-2 text-sm transition-colors " +
        (active
          ? "bg-surface-2 text-ink-hi"
          : "text-ink-mid hover:bg-surface-1 hover:text-ink-hi") +
        (collapsed ? " justify-center" : "")
      }
    >
      <span className={active ? "text-accent" : ""}>{item.icon}</span>
      {!collapsed && <span className="truncate">{item.label}</span>}
      {!collapsed && item.badge ? <Badge n={n} /> : null}
      {collapsed && n > 0 ? (
        <span className="absolute right-2 top-1.5 h-2 w-2 rounded-full bg-accent" />
      ) : null}
    </Link>
  );
}

/** Desktop / tablet vertical rail. `collapsed` → icon-only (tablet). */
export function NavRail({ collapsed = false }: { collapsed?: boolean }) {
  const counts = useWorklistBadges();
  const { me } = useMe();

  return (
    <nav className="flex flex-col gap-0.5">
      {NAV.map((item) => (
        <RailLink
          key={item.href}
          item={item}
          collapsed={collapsed}
          n={item.badge ? counts[item.badge] : 0}
        />
      ))}
      {me?.role === "admin" && (
        <>
          <div className="my-1 border-t border-border" />
          <RailLink
            item={{ href: "/admin", label: "Admin", icon: <Glyph d={I.admin} /> }}
            collapsed={collapsed}
            n={0}
          />
        </>
      )}
    </nav>
  );
}

/** Mobile bottom tab bar (DESIGN.md §6). Drops Settings to keep it to 5 thumbs. */
export function MobileTabBar() {
  const pathname = usePathname();
  const counts = useWorklistBadges();
  const items = NAV.filter((i) => i.href !== "/settings");

  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t border-border bg-surface-1/95 backdrop-blur md:hidden">
      {items.map((item) => {
        const active = isActive(pathname, item.href);
        const n = item.badge ? counts[item.badge] : 0;
        return (
          <Link
            key={item.href}
            href={item.href}
            className={
              "relative flex flex-1 flex-col items-center gap-1 py-2.5 text-[11px] " +
              (active ? "text-ink-hi" : "text-ink-lo")
            }
          >
            <span className={active ? "text-accent" : ""}>{item.icon}</span>
            <span>{item.label}</span>
            {n > 0 && (
              <span className="absolute right-[22%] top-1.5 h-1.5 w-1.5 rounded-full bg-accent" />
            )}
          </Link>
        );
      })}
    </nav>
  );
}
