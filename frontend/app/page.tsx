"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/components/auth-provider";
import { ApiError, apiGet } from "@/lib/api";

type LinkedInStatus = {
  connected: boolean;
  account_kind: string | null;
  display_name: string | null;
  expires_at: string | null;
};

type TokenExpiry = {
  level: "ok" | "amber" | "red";
  title: string;
  subtitle: string;
};

function tokenExpiry(expiresAt: string | null): TokenExpiry | null {
  if (!expiresAt) return null;
  const expMs = new Date(expiresAt).getTime();
  if (Number.isNaN(expMs)) return null;
  const days = (expMs - Date.now()) / 86_400_000;
  const human = new Date(expMs).toLocaleString();
  if (days < 0) {
    const ago = Math.ceil(-days);
    return {
      level: "red",
      title: "LinkedIn token expired. Publishing is paused.",
      subtitle: `Expired ${ago} day${ago === 1 ? "" : "s"} ago (${human}). Reconnect to resume.`,
    };
  }
  if (days <= 3) {
    const n = Math.ceil(days);
    return {
      level: "red",
      title: `LinkedIn token expires in ${n} day${n === 1 ? "" : "s"}.`,
      subtitle: `Standard dev apps don't issue refresh tokens — reconnect manually before ${human}.`,
    };
  }
  if (days <= 10) {
    const n = Math.ceil(days);
    return {
      level: "amber",
      title: `LinkedIn token expires in ${n} days.`,
      subtitle: `Reconnect any time before ${human} to avoid a publishing gap.`,
    };
  }
  return { level: "ok", title: "", subtitle: "" };
}

function Dashboard() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { session, loading: authLoading, signOut } = useAuth();
  const [status, setStatus] = useState<LinkedInStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState("");

  const linkedInResult = searchParams.get("linkedin");
  const linkedInMessage = searchParams.get("message");

  useEffect(() => {
    if (!authLoading && !session) router.replace("/login");
  }, [authLoading, session, router]);

  useEffect(() => {
    if (!session) return;
    setStatusLoading(true);
    apiGet<LinkedInStatus>("/auth/linkedin/status")
      .then(setStatus)
      .catch((e) => setError(e instanceof ApiError ? e.body : (e as Error).message))
      .finally(() => setStatusLoading(false));
  }, [session, linkedInResult]);

  const connect = async () => {
    setConnecting(true);
    setError("");
    try {
      const { authorize_url } = await apiGet<{ authorize_url: string }>(
        "/auth/linkedin/start"
      );
      window.location.href = authorize_url;
    } catch (e) {
      setError(e instanceof ApiError ? e.body : (e as Error).message);
      setConnecting(false);
    }
  };

  if (authLoading || !session) {
    return <div className="flex-1 p-8 text-zinc-500">Loading…</div>;
  }

  const expiry = tokenExpiry(status?.expires_at ?? null);

  return (
    <main className="flex-1 px-6 py-10">
      <header className="flex justify-between items-center mb-12 max-w-4xl mx-auto">
        <h1 className="text-2xl font-bold tracking-tight">AutoPost</h1>
        <div className="flex items-center gap-4 text-sm">
          <span className="text-zinc-500">{session.user.email}</span>
          <button onClick={signOut} className="text-zinc-400 hover:text-white">
            Sign out
          </button>
        </div>
      </header>

      <div className="max-w-4xl mx-auto space-y-6">
        {linkedInResult === "connected" && (
          <div className="rounded border border-green-700 bg-green-950/30 p-4 text-sm">
            LinkedIn connected.
          </div>
        )}
        {linkedInResult === "error" && (
          <div className="rounded border border-red-700 bg-red-950/30 p-4 text-sm">
            LinkedIn error:{" "}
            <span className="font-mono text-xs">{linkedInMessage}</span>
          </div>
        )}
        {expiry && expiry.level !== "ok" && (
          <div
            className={
              "rounded border p-4 text-sm flex items-center justify-between gap-4 " +
              (expiry.level === "red"
                ? "border-red-700 bg-red-950/40"
                : "border-amber-700 bg-amber-950/30")
            }
          >
            <div>
              <p className="font-medium">{expiry.title}</p>
              <p
                className={
                  "text-xs mt-1 " +
                  (expiry.level === "red" ? "text-red-300" : "text-amber-300")
                }
              >
                {expiry.subtitle}
              </p>
            </div>
            <button
              onClick={connect}
              disabled={connecting}
              className={
                "shrink-0 rounded font-medium px-4 py-2 text-sm disabled:opacity-50 " +
                (expiry.level === "red"
                  ? "bg-red-600 hover:bg-red-500 text-white"
                  : "bg-amber-500 hover:bg-amber-400 text-black")
              }
            >
              {connecting ? "Redirecting…" : "Reconnect LinkedIn"}
            </button>
          </div>
        )}

        <section className="rounded border border-zinc-800 bg-zinc-950/50 p-6">
          <h2 className="text-lg font-semibold mb-4">LinkedIn</h2>
          {statusLoading ? (
            <p className="text-sm text-zinc-500">Loading status…</p>
          ) : status?.connected ? (
            <div className="space-y-3">
              <p className="text-sm">
                Connected as{" "}
                <span className="font-medium">{status.display_name ?? "(no name)"}</span>
              </p>
              <div className="text-xs text-zinc-500 space-y-1">
                <p>Account kind: {status.account_kind}</p>
                <p>
                  Token expires:{" "}
                  {status.expires_at
                    ? new Date(status.expires_at).toLocaleString()
                    : "—"}
                </p>
              </div>
              <button
                onClick={connect}
                disabled={connecting}
                className="text-xs text-zinc-400 hover:text-white underline disabled:opacity-50"
              >
                {connecting ? "Redirecting…" : "Reconnect"}
              </button>
            </div>
          ) : (
            <button
              onClick={connect}
              disabled={connecting}
              className="rounded bg-white text-black font-medium px-5 py-2.5 text-sm hover:bg-zinc-200 disabled:opacity-50"
            >
              {connecting ? "Redirecting…" : "Connect LinkedIn"}
            </button>
          )}
          {error && (
            <p className="text-red-400 text-xs mt-4 font-mono break-all">{error}</p>
          )}
        </section>

        <section className="rounded border border-zinc-800 bg-zinc-950/50 p-6">
          <h2 className="text-lg font-semibold mb-1">Trends</h2>
          <p className="text-sm text-zinc-500 mb-4">
            Fresh items from RSS + HackerNews. Pull more on demand or wait for the
            6-hour cron.
          </p>
          <Link
            href="/trends"
            className="inline-block rounded bg-white text-black font-medium px-4 py-2 text-sm hover:bg-zinc-200"
          >
            Browse trends →
          </Link>
        </section>

        <section className="rounded border border-zinc-800 bg-zinc-950/50 p-6">
          <h2 className="text-lg font-semibold mb-1">Drafts</h2>
          <p className="text-sm text-zinc-500 mb-4">
            Generate founder-voice drafts from unconsumed trends. Review,
            edit, approve, and schedule them here.
          </p>
          <Link
            href="/drafts"
            className="inline-block rounded bg-white text-black font-medium px-4 py-2 text-sm hover:bg-zinc-200"
          >
            Open drafts →
          </Link>
        </section>

        <section className="rounded border border-zinc-800 bg-zinc-950/50 p-6">
          <h2 className="text-lg font-semibold mb-1">Scheduled</h2>
          <p className="text-sm text-zinc-500 mb-4">
            Approved posts waiting for their publish slot, next-up first.
          </p>
          <Link
            href="/scheduled"
            className="inline-block rounded bg-white text-black font-medium px-4 py-2 text-sm hover:bg-zinc-200"
          >
            View scheduled →
          </Link>
        </section>

        <section className="rounded border border-zinc-800 bg-zinc-950/50 p-6">
          <h2 className="text-lg font-semibold mb-1">Published</h2>
          <p className="text-sm text-zinc-500 mb-4">
            What&apos;s already gone live, most recent first. Each row links to
            the LinkedIn post.
          </p>
          <Link
            href="/published"
            className="inline-block rounded bg-white text-black font-medium px-4 py-2 text-sm hover:bg-zinc-200"
          >
            View published →
          </Link>
        </section>

        <section className="rounded border border-zinc-800 bg-zinc-950/50 p-6 text-sm text-zinc-500">
          <h2 className="text-base font-semibold text-zinc-300 mb-2">
            Coming soon
          </h2>
          <p>
            Publishing worker (Phase 6) and analytics (Phase 7) will appear
            here as they land.
          </p>
        </section>
      </div>
    </main>
  );
}

export default function HomePage() {
  return (
    <Suspense
      fallback={<div className="flex-1 p-8 text-zinc-500">Loading…</div>}
    >
      <Dashboard />
    </Suspense>
  );
}
