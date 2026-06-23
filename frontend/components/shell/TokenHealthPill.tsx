"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { tokenExpiry } from "@/lib/tokenExpiry";

// Global chrome (DESIGN.md §2): the LinkedIn day-60 token death is the system's
// biggest operational failure mode, so its health follows the operator on every
// screen. Silent when healthy; amber/red pill with a Reconnect CTA otherwise.

type LinkedInStatus = { expires_at: string | null };

export function TokenHealthPill({ collapsed = false }: { collapsed?: boolean }) {
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);

  useEffect(() => {
    apiGet<LinkedInStatus>("/auth/linkedin/status")
      .then((s) => setExpiresAt(s.expires_at))
      .catch(() => setExpiresAt(null));
  }, []);

  const expiry = tokenExpiry(expiresAt);
  if (!expiry || expiry.level === "ok") return null;

  const red = expiry.level === "red";

  const reconnect = async () => {
    setConnecting(true);
    try {
      const { authorize_url } = await apiGet<{ authorize_url: string }>(
        "/auth/linkedin/start"
      );
      window.location.href = authorize_url;
    } catch {
      setConnecting(false);
    }
  };

  // Collapsed (icon-rail): a single dot is enough of a signal; full pill on hover-wide.
  if (collapsed) {
    return (
      <button
        onClick={reconnect}
        title={expiry.title}
        className="flex items-center justify-center py-2"
      >
        <span
          className={
            "h-2 w-2 rounded-full " +
            (red ? "bg-status-failed" : "bg-status-publishing")
          }
        />
      </button>
    );
  }

  return (
    <div
      className={
        "rounded-md border p-2.5 text-xs " +
        (red
          ? "border-status-failed/40 bg-status-failed/10"
          : "border-status-publishing/40 bg-status-publishing/10")
      }
    >
      <p className={"font-medium " + (red ? "text-status-failed" : "text-status-publishing")}>
        {expiry.title}
      </p>
      <button
        onClick={reconnect}
        disabled={connecting}
        className="mt-1.5 text-ink-mid underline underline-offset-2 hover:text-ink-hi disabled:opacity-50"
      >
        {connecting ? "Redirecting…" : "Reconnect LinkedIn"}
      </button>
    </div>
  );
}
