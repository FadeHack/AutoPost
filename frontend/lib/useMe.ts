"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

// Identity + role for the current user (backend `GET /me`). Used to gate the
// admin nav entry and the `/admin` route (Phase 14). Cached module-level so the
// rail, mobile bar, and admin page share a single fetch per page load.

export type Role = "admin" | "editor" | "viewer";

export type Me = {
  id: string;
  email: string;
  role: Role;
  workspace_id: string;
  workspace_name: string;
};

let cache: Me | null = null;
let inflight: Promise<Me> | null = null;
// Every mounted `useMe()` call registers its setter here so a write elsewhere
// (e.g. the workspace-rename control in Settings) can push the fresh value to
// every consumer — the rail, mobile bar, admin page — without each of them
// re-fetching or the caller needing to know who else is listening.
const subscribers = new Set<(m: Me) => void>();

/** Update the shared cache and notify every mounted `useMe()` consumer.
 * Call with the server's response after a write that changes `/me` data
 * (e.g. a workspace rename) so the UI reflects it immediately. */
export function setCachedMe(m: Me): void {
  cache = m;
  for (const notify of subscribers) notify(m);
}

export function useMe(): { me: Me | null; loading: boolean } {
  const [me, setMe] = useState<Me | null>(cache);
  const [loading, setLoading] = useState(!cache);

  useEffect(() => {
    subscribers.add(setMe);
    return () => {
      subscribers.delete(setMe);
    };
  }, []);

  useEffect(() => {
    // State already initializes from `cache`, so a warm cache needs no work
    // (and no synchronous setState in the effect body).
    if (cache) return;

    let alive = true;
    if (!inflight) {
      inflight = apiGet<Me>("/me").then((m) => {
        cache = m;
        return m;
      });
    }
    inflight
      .then((m) => {
        if (alive) {
          setMe(m);
          setLoading(false);
        }
      })
      .catch(() => {
        // Not signed in / transient — leave `me` null; callers redirect.
        if (alive) setLoading(false);
        inflight = null; // allow a retry on next mount
      });
    return () => {
      alive = false;
    };
  }, []);

  return { me, loading };
}
