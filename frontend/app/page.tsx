"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/components/auth-provider";
import { ApiError, apiDelete, apiGet, apiPost } from "@/lib/api";

type LinkedInStatus = {
  connected: boolean;
  account_kind: string | null;
  display_name: string | null;
  expires_at: string | null;
};

type BlueskyStatus = {
  connected: boolean;
  handle: string | null;
  did: string | null;
  display_name: string | null;
};

type MastodonStatus = {
  connected: boolean;
  instance_url: string | null;
  handle: string | null;
  display_name: string | null;
};

type ThreadsStatus = {
  enabled: boolean;
  connected: boolean;
  username: string | null;
  display_name: string | null;
  expires_at: string | null;
};

type InstagramStatus = {
  enabled: boolean;
  connected: boolean;
  username: string | null;
  account_type: string | null;
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
  // Bluesky uses App Password (no OAuth) — inline form vs LinkedIn redirect.
  const [bskyStatus, setBskyStatus] = useState<BlueskyStatus | null>(null);
  const [bskyLoading, setBskyLoading] = useState(true);
  const [bskyFormOpen, setBskyFormOpen] = useState(false);
  const [bskyHandle, setBskyHandle] = useState("");
  const [bskyPassword, setBskyPassword] = useState("");
  const [bskyConnecting, setBskyConnecting] = useState(false);
  const [bskyError, setBskyError] = useState("");
  // Mastodon is federated — full OAuth, but the user must name their instance
  // first (we register an app on it server-side, then redirect to authorize).
  const [mastoStatus, setMastoStatus] = useState<MastodonStatus | null>(null);
  const [mastoLoading, setMastoLoading] = useState(true);
  const [mastoFormOpen, setMastoFormOpen] = useState(false);
  const [mastoInstance, setMastoInstance] = useState("");
  const [mastoConnecting, setMastoConnecting] = useState(false);
  const [mastoError, setMastoError] = useState("");
  // Threads is Meta-gated — the backend reports `enabled` (PLATFORM_THREADS_ENABLED).
  // When disabled the whole section is hidden. Connect is a LinkedIn-style redirect.
  const [threadsStatus, setThreadsStatus] = useState<ThreadsStatus | null>(null);
  const [threadsLoading, setThreadsLoading] = useState(true);
  const [threadsConnecting, setThreadsConnecting] = useState(false);
  const [threadsError, setThreadsError] = useState("");
  // Instagram is Meta-gated — same shape as Threads (Instagram Login redirect).
  const [instagramStatus, setInstagramStatus] = useState<InstagramStatus | null>(null);
  const [instagramLoading, setInstagramLoading] = useState(true);
  const [instagramConnecting, setInstagramConnecting] = useState(false);
  const [instagramError, setInstagramError] = useState("");

  const linkedInResult = searchParams.get("linkedin");
  const linkedInMessage = searchParams.get("message");
  const mastodonResult = searchParams.get("mastodon");
  const mastodonMessage = searchParams.get("message");
  const threadsResult = searchParams.get("threads");
  const threadsMessage = searchParams.get("message");
  const instagramResult = searchParams.get("instagram");
  const instagramMessage = searchParams.get("message");

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

  useEffect(() => {
    if (!session) return;
    setBskyLoading(true);
    apiGet<BlueskyStatus>("/auth/bluesky/status")
      .then(setBskyStatus)
      .catch(() => setBskyStatus({ connected: false, handle: null, did: null, display_name: null }))
      .finally(() => setBskyLoading(false));
  }, [session]);

  useEffect(() => {
    if (!session) return;
    setMastoLoading(true);
    apiGet<MastodonStatus>("/auth/mastodon/status")
      .then(setMastoStatus)
      .catch(() =>
        setMastoStatus({
          connected: false,
          instance_url: null,
          handle: null,
          display_name: null,
        })
      )
      .finally(() => setMastoLoading(false));
  }, [session, mastodonResult]);

  useEffect(() => {
    if (!session) return;
    setThreadsLoading(true);
    apiGet<ThreadsStatus>("/auth/threads/status")
      .then(setThreadsStatus)
      .catch(() =>
        setThreadsStatus({
          enabled: false,
          connected: false,
          username: null,
          display_name: null,
          expires_at: null,
        })
      )
      .finally(() => setThreadsLoading(false));
  }, [session, threadsResult]);

  useEffect(() => {
    if (!session) return;
    setInstagramLoading(true);
    apiGet<InstagramStatus>("/auth/instagram/status")
      .then(setInstagramStatus)
      .catch(() =>
        setInstagramStatus({
          enabled: false,
          connected: false,
          username: null,
          account_type: null,
          expires_at: null,
        })
      )
      .finally(() => setInstagramLoading(false));
  }, [session, instagramResult]);

  const connectInstagram = async () => {
    setInstagramConnecting(true);
    setInstagramError("");
    try {
      const { authorize_url } = await apiGet<{ authorize_url: string }>(
        "/auth/instagram/start"
      );
      window.location.href = authorize_url;
    } catch (e) {
      setInstagramError(e instanceof ApiError ? e.body : (e as Error).message);
      setInstagramConnecting(false);
    }
  };

  const disconnectInstagram = async () => {
    if (
      !confirm(
        "Disconnect Instagram? Any scheduled Instagram publishes will fail."
      )
    )
      return;
    try {
      await apiDelete("/auth/instagram/disconnect");
      setInstagramStatus({
        enabled: true,
        connected: false,
        username: null,
        account_type: null,
        expires_at: null,
      });
    } catch (e) {
      setInstagramError(e instanceof ApiError ? e.body : (e as Error).message);
    }
  };

  const connectThreads = async () => {
    setThreadsConnecting(true);
    setThreadsError("");
    try {
      const { authorize_url } = await apiGet<{ authorize_url: string }>(
        "/auth/threads/start"
      );
      window.location.href = authorize_url;
    } catch (e) {
      setThreadsError(e instanceof ApiError ? e.body : (e as Error).message);
      setThreadsConnecting(false);
    }
  };

  const disconnectThreads = async () => {
    if (!confirm("Disconnect Threads? Any scheduled Threads publishes will fail."))
      return;
    try {
      await apiDelete("/auth/threads/disconnect");
      setThreadsStatus({
        enabled: true,
        connected: false,
        username: null,
        display_name: null,
        expires_at: null,
      });
    } catch (e) {
      setThreadsError(e instanceof ApiError ? e.body : (e as Error).message);
    }
  };

  const connectMastodon = async () => {
    setMastoConnecting(true);
    setMastoError("");
    try {
      const { authorize_url } = await apiGet<{ authorize_url: string }>(
        `/auth/mastodon/start?instance=${encodeURIComponent(mastoInstance.trim())}`
      );
      window.location.href = authorize_url;
    } catch (e) {
      setMastoError(e instanceof ApiError ? e.body : (e as Error).message);
      setMastoConnecting(false);
    }
  };

  const disconnectMastodon = async () => {
    if (!confirm("Disconnect Mastodon? Any scheduled Mastodon publishes will fail."))
      return;
    try {
      await apiDelete("/auth/mastodon/disconnect");
      setMastoStatus({
        connected: false,
        instance_url: null,
        handle: null,
        display_name: null,
      });
    } catch (e) {
      setMastoError(e instanceof ApiError ? e.body : (e as Error).message);
    }
  };

  const connectBluesky = async () => {
    setBskyConnecting(true);
    setBskyError("");
    try {
      const res = await apiPost<BlueskyStatus>("/auth/bluesky/connect", {
        handle: bskyHandle.trim(),
        app_password: bskyPassword,
      });
      setBskyStatus(res);
      setBskyFormOpen(false);
      setBskyHandle("");
      setBskyPassword("");
    } catch (e) {
      setBskyError(e instanceof ApiError ? e.body : (e as Error).message);
    } finally {
      setBskyConnecting(false);
    }
  };

  const disconnectBluesky = async () => {
    if (!confirm("Disconnect Bluesky? Any scheduled Bluesky publishes will fail.")) return;
    try {
      await apiDelete("/auth/bluesky/disconnect");
      setBskyStatus({ connected: false, handle: null, did: null, display_name: null });
    } catch (e) {
      setBskyError(e instanceof ApiError ? e.body : (e as Error).message);
    }
  };

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
        {mastodonResult === "connected" && (
          <div className="rounded border border-green-700 bg-green-950/30 p-4 text-sm">
            Mastodon connected.
          </div>
        )}
        {mastodonResult === "error" && (
          <div className="rounded border border-red-700 bg-red-950/30 p-4 text-sm">
            Mastodon error:{" "}
            <span className="font-mono text-xs">{mastodonMessage}</span>
          </div>
        )}
        {threadsResult === "connected" && (
          <div className="rounded border border-green-700 bg-green-950/30 p-4 text-sm">
            Threads connected.
          </div>
        )}
        {threadsResult === "error" && (
          <div className="rounded border border-red-700 bg-red-950/30 p-4 text-sm">
            Threads error:{" "}
            <span className="font-mono text-xs">{threadsMessage}</span>
          </div>
        )}
        {instagramResult === "connected" && (
          <div className="rounded border border-green-700 bg-green-950/30 p-4 text-sm">
            Instagram connected.
          </div>
        )}
        {instagramResult === "error" && (
          <div className="rounded border border-red-700 bg-red-950/30 p-4 text-sm">
            Instagram error:{" "}
            <span className="font-mono text-xs">{instagramMessage}</span>
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
          <h2 className="text-lg font-semibold mb-4">Bluesky</h2>
          {bskyLoading ? (
            <p className="text-sm text-zinc-500">Loading status…</p>
          ) : bskyStatus?.connected ? (
            <div className="space-y-3">
              <p className="text-sm">
                Connected as{" "}
                <span className="font-medium">
                  @{bskyStatus.handle}
                </span>
                {bskyStatus.display_name && (
                  <span className="text-zinc-500"> ({bskyStatus.display_name})</span>
                )}
              </p>
              <p className="text-xs text-zinc-500 font-mono break-all">
                DID: {bskyStatus.did}
              </p>
              <button
                onClick={disconnectBluesky}
                className="text-xs text-zinc-400 hover:text-white underline"
              >
                Disconnect
              </button>
            </div>
          ) : bskyFormOpen ? (
            <div className="space-y-3">
              <p className="text-xs text-zinc-500">
                Bluesky uses an app password, not OAuth. Generate one at{" "}
                <a
                  href="https://bsky.app/settings/app-passwords"
                  target="_blank"
                  rel="noreferrer"
                  className="underline hover:text-white"
                >
                  bsky.app/settings/app-passwords
                </a>.
              </p>
              <input
                type="text"
                placeholder="handle (e.g. nestwhirr.bsky.social)"
                value={bskyHandle}
                onChange={(e) => setBskyHandle(e.target.value)}
                className="w-full rounded bg-zinc-900 border border-zinc-800 px-3 py-2 text-sm"
              />
              <input
                type="password"
                placeholder="app password (xxxx-xxxx-xxxx-xxxx)"
                value={bskyPassword}
                onChange={(e) => setBskyPassword(e.target.value)}
                className="w-full rounded bg-zinc-900 border border-zinc-800 px-3 py-2 text-sm font-mono"
              />
              <div className="flex gap-2">
                <button
                  onClick={connectBluesky}
                  disabled={bskyConnecting || !bskyHandle.trim() || !bskyPassword}
                  className="rounded bg-white text-black font-medium px-4 py-2 text-sm hover:bg-zinc-200 disabled:opacity-50"
                >
                  {bskyConnecting ? "Connecting…" : "Save"}
                </button>
                <button
                  onClick={() => {
                    setBskyFormOpen(false);
                    setBskyError("");
                  }}
                  className="rounded border border-zinc-700 px-4 py-2 text-sm hover:bg-zinc-800"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setBskyFormOpen(true)}
              className="rounded bg-white text-black font-medium px-5 py-2.5 text-sm hover:bg-zinc-200"
            >
              Connect Bluesky
            </button>
          )}
          {bskyError && (
            <p className="text-red-400 text-xs mt-4 font-mono break-all">
              {bskyError}
            </p>
          )}
        </section>

        <section className="rounded border border-zinc-800 bg-zinc-950/50 p-6">
          <h2 className="text-lg font-semibold mb-4">Mastodon</h2>
          {mastoLoading ? (
            <p className="text-sm text-zinc-500">Loading status…</p>
          ) : mastoStatus?.connected ? (
            <div className="space-y-3">
              <p className="text-sm">
                Connected as{" "}
                <span className="font-medium">
                  @{mastoStatus.handle}
                </span>
                {mastoStatus.display_name && (
                  <span className="text-zinc-500"> ({mastoStatus.display_name})</span>
                )}
              </p>
              <p className="text-xs text-zinc-500 font-mono break-all">
                {mastoStatus.instance_url}
              </p>
              <button
                onClick={disconnectMastodon}
                className="text-xs text-zinc-400 hover:text-white underline"
              >
                Disconnect
              </button>
            </div>
          ) : mastoFormOpen ? (
            <div className="space-y-3">
              <p className="text-xs text-zinc-500">
                Mastodon is federated — enter your home instance. We register an
                app on it, then redirect you to authorize.
              </p>
              <input
                type="text"
                placeholder="instance (e.g. mastodon.social)"
                value={mastoInstance}
                onChange={(e) => setMastoInstance(e.target.value)}
                className="w-full rounded bg-zinc-900 border border-zinc-800 px-3 py-2 text-sm"
              />
              <div className="flex gap-2">
                <button
                  onClick={connectMastodon}
                  disabled={mastoConnecting || !mastoInstance.trim()}
                  className="rounded bg-white text-black font-medium px-4 py-2 text-sm hover:bg-zinc-200 disabled:opacity-50"
                >
                  {mastoConnecting ? "Redirecting…" : "Authorize"}
                </button>
                <button
                  onClick={() => {
                    setMastoFormOpen(false);
                    setMastoError("");
                  }}
                  className="rounded border border-zinc-700 px-4 py-2 text-sm hover:bg-zinc-800"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setMastoFormOpen(true)}
              className="rounded bg-white text-black font-medium px-5 py-2.5 text-sm hover:bg-zinc-200"
            >
              Connect Mastodon
            </button>
          )}
          {mastoError && (
            <p className="text-red-400 text-xs mt-4 font-mono break-all">
              {mastoError}
            </p>
          )}
        </section>

        {!threadsLoading && threadsStatus?.enabled && (
          <section className="rounded border border-zinc-800 bg-zinc-950/50 p-6">
            <h2 className="text-lg font-semibold mb-4">Threads</h2>
            {threadsStatus.connected ? (
              <div className="space-y-3">
                <p className="text-sm">
                  Connected as{" "}
                  <span className="font-medium">@{threadsStatus.username}</span>
                  {threadsStatus.display_name && (
                    <span className="text-zinc-500">
                      {" "}
                      ({threadsStatus.display_name})
                    </span>
                  )}
                </p>
                {threadsStatus.expires_at && (
                  <p className="text-xs text-zinc-500">
                    Token expires:{" "}
                    {new Date(threadsStatus.expires_at).toLocaleString()}
                  </p>
                )}
                <button
                  onClick={disconnectThreads}
                  className="text-xs text-zinc-400 hover:text-white underline"
                >
                  Disconnect
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-xs text-zinc-500">
                  Threads uses Meta&apos;s OAuth. You&apos;ll be redirected to
                  authorize, then back here.
                </p>
                <button
                  onClick={connectThreads}
                  disabled={threadsConnecting}
                  className="rounded bg-white text-black font-medium px-5 py-2.5 text-sm hover:bg-zinc-200 disabled:opacity-50"
                >
                  {threadsConnecting ? "Redirecting…" : "Connect Threads"}
                </button>
              </div>
            )}
            {threadsError && (
              <p className="text-red-400 text-xs mt-4 font-mono break-all">
                {threadsError}
              </p>
            )}
          </section>
        )}

        {!instagramLoading && instagramStatus?.enabled && (
          <section className="rounded border border-zinc-800 bg-zinc-950/50 p-6">
            <h2 className="text-lg font-semibold mb-4">Instagram</h2>
            {instagramStatus.connected ? (
              <div className="space-y-3">
                <p className="text-sm">
                  Connected as{" "}
                  <span className="font-medium">
                    @{instagramStatus.username}
                  </span>
                  {instagramStatus.account_type && (
                    <span className="text-zinc-500">
                      {" "}
                      ({instagramStatus.account_type.toLowerCase()})
                    </span>
                  )}
                </p>
                {instagramStatus.expires_at && (
                  <p className="text-xs text-zinc-500">
                    Token expires:{" "}
                    {new Date(instagramStatus.expires_at).toLocaleString()}
                  </p>
                )}
                <button
                  onClick={disconnectInstagram}
                  className="text-xs text-zinc-400 hover:text-white underline"
                >
                  Disconnect
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-xs text-zinc-500">
                  Instagram uses Meta&apos;s OAuth (Instagram Login). Requires a
                  Creator/Business account. You&apos;ll be redirected to
                  authorize, then back here.
                </p>
                <button
                  onClick={connectInstagram}
                  disabled={instagramConnecting}
                  className="rounded bg-white text-black font-medium px-5 py-2.5 text-sm hover:bg-zinc-200 disabled:opacity-50"
                >
                  {instagramConnecting ? "Redirecting…" : "Connect Instagram"}
                </button>
              </div>
            )}
            {instagramError && (
              <p className="text-red-400 text-xs mt-4 font-mono break-all">
                {instagramError}
              </p>
            )}
          </section>
        )}

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
