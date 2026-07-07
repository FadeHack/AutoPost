"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { Banner } from "@/components/ui/Banner";
import { ApiError, apiDelete, apiGet, apiPost } from "@/lib/api";
import { tokenExpiry } from "@/lib/tokenExpiry";

// Settings → Connections (DESIGN.md §5G). The five platform-account sections,
// moved verbatim out of the old home card-wall so Today opens on the work, not
// on plumbing touched ~once per 60 days. Logic is unchanged from the prior
// home page; chrome is restyled onto the design tokens + kit Banner. Meta-gated
// Threads/Instagram stay hidden until the backend reports `enabled`.
//
// OAuth callbacks redirect to `/` (Today), which surfaces the connect/error
// confirmation; this component just reflects current status on mount.

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

type XStatus = {
  enabled: boolean;
  connected: boolean;
  username: string | null;
  display_name: string | null;
  expires_at: string | null;
};

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-md border border-border bg-surface-1 p-6">
      <h2 className="mb-4 text-base font-medium text-ink-hi">{title}</h2>
      {children}
    </section>
  );
}

const PRIMARY_BTN =
  "rounded-md bg-accent px-5 py-2.5 text-sm font-medium text-accent-ink hover:bg-accent/90 disabled:opacity-50";
const INPUT =
  "w-full rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-ink-hi outline-none focus:border-ink-lo";
const LINK_BTN = "text-xs text-ink-mid underline hover:text-ink-hi";

export default function Connections() {
  const { session } = useAuth();

  const [status, setStatus] = useState<LinkedInStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState("");

  const [bskyStatus, setBskyStatus] = useState<BlueskyStatus | null>(null);
  const [bskyLoading, setBskyLoading] = useState(true);
  const [bskyFormOpen, setBskyFormOpen] = useState(false);
  const [bskyHandle, setBskyHandle] = useState("");
  const [bskyPassword, setBskyPassword] = useState("");
  const [bskyConnecting, setBskyConnecting] = useState(false);
  const [bskyError, setBskyError] = useState("");

  const [mastoStatus, setMastoStatus] = useState<MastodonStatus | null>(null);
  const [mastoLoading, setMastoLoading] = useState(true);
  const [mastoFormOpen, setMastoFormOpen] = useState(false);
  const [mastoInstance, setMastoInstance] = useState("");
  const [mastoConnecting, setMastoConnecting] = useState(false);
  const [mastoError, setMastoError] = useState("");

  const [threadsStatus, setThreadsStatus] = useState<ThreadsStatus | null>(null);
  const [threadsLoading, setThreadsLoading] = useState(true);
  const [threadsConnecting, setThreadsConnecting] = useState(false);
  const [threadsError, setThreadsError] = useState("");

  const [instagramStatus, setInstagramStatus] =
    useState<InstagramStatus | null>(null);
  const [instagramLoading, setInstagramLoading] = useState(true);
  const [instagramConnecting, setInstagramConnecting] = useState(false);
  const [instagramError, setInstagramError] = useState("");

  const [xStatus, setXStatus] = useState<XStatus | null>(null);
  const [xLoading, setXLoading] = useState(true);
  const [xConnecting, setXConnecting] = useState(false);
  const [xError, setXError] = useState("");

  useEffect(() => {
    if (!session) return;
    setStatusLoading(true);
    apiGet<LinkedInStatus>("/auth/linkedin/status")
      .then(setStatus)
      .catch((e) => setError(e instanceof ApiError ? e.body : (e as Error).message))
      .finally(() => setStatusLoading(false));
  }, [session]);

  useEffect(() => {
    if (!session) return;
    setBskyLoading(true);
    apiGet<BlueskyStatus>("/auth/bluesky/status")
      .then(setBskyStatus)
      .catch(() =>
        setBskyStatus({ connected: false, handle: null, did: null, display_name: null }),
      )
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
        }),
      )
      .finally(() => setMastoLoading(false));
  }, [session]);

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
        }),
      )
      .finally(() => setThreadsLoading(false));
  }, [session]);

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
        }),
      )
      .finally(() => setInstagramLoading(false));
  }, [session]);

  useEffect(() => {
    if (!session) return;
    setXLoading(true);
    apiGet<XStatus>("/auth/x/status")
      .then(setXStatus)
      .catch(() =>
        setXStatus({
          enabled: false,
          connected: false,
          username: null,
          display_name: null,
          expires_at: null,
        }),
      )
      .finally(() => setXLoading(false));
  }, [session]);

  const connect = async () => {
    setConnecting(true);
    setError("");
    try {
      const { authorize_url } = await apiGet<{ authorize_url: string }>(
        "/auth/linkedin/start",
      );
      window.location.href = authorize_url;
    } catch (e) {
      setError(e instanceof ApiError ? e.body : (e as Error).message);
      setConnecting(false);
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
    if (!confirm("Disconnect Bluesky? Any scheduled Bluesky publishes will fail."))
      return;
    try {
      await apiDelete("/auth/bluesky/disconnect");
      setBskyStatus({ connected: false, handle: null, did: null, display_name: null });
    } catch (e) {
      setBskyError(e instanceof ApiError ? e.body : (e as Error).message);
    }
  };

  const connectMastodon = async () => {
    setMastoConnecting(true);
    setMastoError("");
    try {
      const { authorize_url } = await apiGet<{ authorize_url: string }>(
        `/auth/mastodon/start?instance=${encodeURIComponent(mastoInstance.trim())}`,
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

  const connectThreads = async () => {
    setThreadsConnecting(true);
    setThreadsError("");
    try {
      const { authorize_url } = await apiGet<{ authorize_url: string }>(
        "/auth/threads/start",
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

  const connectInstagram = async () => {
    setInstagramConnecting(true);
    setInstagramError("");
    try {
      const { authorize_url } = await apiGet<{ authorize_url: string }>(
        "/auth/instagram/start",
      );
      window.location.href = authorize_url;
    } catch (e) {
      setInstagramError(e instanceof ApiError ? e.body : (e as Error).message);
      setInstagramConnecting(false);
    }
  };

  const disconnectInstagram = async () => {
    if (!confirm("Disconnect Instagram? Any scheduled Instagram publishes will fail."))
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

  const connectX = async () => {
    setXConnecting(true);
    setXError("");
    try {
      const { authorize_url } = await apiGet<{ authorize_url: string }>(
        "/auth/x/start",
      );
      window.location.href = authorize_url;
    } catch (e) {
      setXError(e instanceof ApiError ? e.body : (e as Error).message);
      setXConnecting(false);
    }
  };

  const disconnectX = async () => {
    if (!confirm("Disconnect X? Any scheduled X publishes will fail.")) return;
    try {
      await apiDelete("/auth/x/disconnect");
      setXStatus({
        enabled: true,
        connected: false,
        username: null,
        display_name: null,
        expires_at: null,
      });
    } catch (e) {
      setXError(e instanceof ApiError ? e.body : (e as Error).message);
    }
  };

  const expiry = tokenExpiry(status?.expires_at ?? null);

  return (
    <div className="space-y-5">
      {expiry && expiry.level !== "ok" && (
        <Banner tone={expiry.level === "red" ? "error" : "warn"} title={expiry.title}>
          <div className="flex items-center justify-between gap-4">
            <span>{expiry.subtitle}</span>
            <button onClick={connect} disabled={connecting} className={PRIMARY_BTN}>
              {connecting ? "Redirecting…" : "Reconnect"}
            </button>
          </div>
        </Banner>
      )}

      <Section title="LinkedIn">
        {statusLoading ? (
          <p className="text-sm text-ink-lo">Loading status…</p>
        ) : status?.connected ? (
          <div className="space-y-3">
            <p className="text-sm text-ink-hi">
              Connected as{" "}
              <span className="font-medium">
                {status.display_name ?? "(no name)"}
              </span>
            </p>
            <div className="space-y-1 text-xs text-ink-lo">
              <p>Account kind: {status.account_kind}</p>
              <p>
                Token expires:{" "}
                {status.expires_at
                  ? new Date(status.expires_at).toLocaleString()
                  : "—"}
              </p>
            </div>
            <button onClick={connect} disabled={connecting} className={LINK_BTN}>
              {connecting ? "Redirecting…" : "Reconnect"}
            </button>
          </div>
        ) : (
          <button onClick={connect} disabled={connecting} className={PRIMARY_BTN}>
            {connecting ? "Redirecting…" : "Connect LinkedIn"}
          </button>
        )}
        {error && (
          <Banner tone="error" className="mt-4">
            <span className="font-mono break-all">{error}</span>
          </Banner>
        )}
      </Section>

      <Section title="Bluesky">
        {bskyLoading ? (
          <p className="text-sm text-ink-lo">Loading status…</p>
        ) : bskyStatus?.connected ? (
          <div className="space-y-3">
            <p className="text-sm text-ink-hi">
              Connected as <span className="font-medium">@{bskyStatus.handle}</span>
              {bskyStatus.display_name && (
                <span className="text-ink-lo"> ({bskyStatus.display_name})</span>
              )}
            </p>
            <p className="break-all font-mono text-xs text-ink-lo">
              DID: {bskyStatus.did}
            </p>
            <button onClick={disconnectBluesky} className={LINK_BTN}>
              Disconnect
            </button>
          </div>
        ) : bskyFormOpen ? (
          <div className="space-y-3">
            <p className="text-xs text-ink-lo">
              Bluesky uses an app password, not OAuth. Generate one at{" "}
              <a
                href="https://bsky.app/settings/app-passwords"
                target="_blank"
                rel="noreferrer"
                className="underline hover:text-ink-hi"
              >
                bsky.app/settings/app-passwords
              </a>
              .
            </p>
            <input
              type="text"
              placeholder="handle (e.g. nestwhirr.bsky.social)"
              value={bskyHandle}
              onChange={(e) => setBskyHandle(e.target.value)}
              className={INPUT}
            />
            <input
              type="password"
              placeholder="app password (xxxx-xxxx-xxxx-xxxx)"
              value={bskyPassword}
              onChange={(e) => setBskyPassword(e.target.value)}
              className={INPUT + " font-mono"}
            />
            <div className="flex gap-2">
              <button
                onClick={connectBluesky}
                disabled={bskyConnecting || !bskyHandle.trim() || !bskyPassword}
                className={PRIMARY_BTN}
              >
                {bskyConnecting ? "Connecting…" : "Save"}
              </button>
              <button
                onClick={() => {
                  setBskyFormOpen(false);
                  setBskyError("");
                }}
                className="rounded-md border border-border px-4 py-2 text-sm text-ink-mid hover:bg-surface-2"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button onClick={() => setBskyFormOpen(true)} className={PRIMARY_BTN}>
            Connect Bluesky
          </button>
        )}
        {bskyError && (
          <Banner tone="error" className="mt-4">
            <span className="font-mono break-all">{bskyError}</span>
          </Banner>
        )}
      </Section>

      <Section title="Mastodon">
        {mastoLoading ? (
          <p className="text-sm text-ink-lo">Loading status…</p>
        ) : mastoStatus?.connected ? (
          <div className="space-y-3">
            <p className="text-sm text-ink-hi">
              Connected as <span className="font-medium">@{mastoStatus.handle}</span>
              {mastoStatus.display_name && (
                <span className="text-ink-lo"> ({mastoStatus.display_name})</span>
              )}
            </p>
            <p className="break-all font-mono text-xs text-ink-lo">
              {mastoStatus.instance_url}
            </p>
            <button onClick={disconnectMastodon} className={LINK_BTN}>
              Disconnect
            </button>
          </div>
        ) : mastoFormOpen ? (
          <div className="space-y-3">
            <p className="text-xs text-ink-lo">
              Mastodon is federated — enter your home instance. We register an app
              on it, then redirect you to authorize.
            </p>
            <input
              type="text"
              placeholder="instance (e.g. mastodon.social)"
              value={mastoInstance}
              onChange={(e) => setMastoInstance(e.target.value)}
              className={INPUT}
            />
            <div className="flex gap-2">
              <button
                onClick={connectMastodon}
                disabled={mastoConnecting || !mastoInstance.trim()}
                className={PRIMARY_BTN}
              >
                {mastoConnecting ? "Redirecting…" : "Authorize"}
              </button>
              <button
                onClick={() => {
                  setMastoFormOpen(false);
                  setMastoError("");
                }}
                className="rounded-md border border-border px-4 py-2 text-sm text-ink-mid hover:bg-surface-2"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button onClick={() => setMastoFormOpen(true)} className={PRIMARY_BTN}>
            Connect Mastodon
          </button>
        )}
        {mastoError && (
          <Banner tone="error" className="mt-4">
            <span className="font-mono break-all">{mastoError}</span>
          </Banner>
        )}
      </Section>

      {!threadsLoading && threadsStatus?.enabled && (
        <Section title="Threads">
          {threadsStatus.connected ? (
            <div className="space-y-3">
              <p className="text-sm text-ink-hi">
                Connected as{" "}
                <span className="font-medium">@{threadsStatus.username}</span>
                {threadsStatus.display_name && (
                  <span className="text-ink-lo"> ({threadsStatus.display_name})</span>
                )}
              </p>
              {threadsStatus.expires_at && (
                <p className="text-xs text-ink-lo">
                  Token expires:{" "}
                  {new Date(threadsStatus.expires_at).toLocaleString()}
                </p>
              )}
              <button onClick={disconnectThreads} className={LINK_BTN}>
                Disconnect
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-xs text-ink-lo">
                Threads uses Meta&apos;s OAuth. You&apos;ll be redirected to
                authorize, then back here.
              </p>
              <button
                onClick={connectThreads}
                disabled={threadsConnecting}
                className={PRIMARY_BTN}
              >
                {threadsConnecting ? "Redirecting…" : "Connect Threads"}
              </button>
            </div>
          )}
          {threadsError && (
            <Banner tone="error" className="mt-4">
              <span className="font-mono break-all">{threadsError}</span>
            </Banner>
          )}
        </Section>
      )}

      {!instagramLoading && instagramStatus?.enabled && (
        <Section title="Instagram">
          {instagramStatus.connected ? (
            <div className="space-y-3">
              <p className="text-sm text-ink-hi">
                Connected as{" "}
                <span className="font-medium">@{instagramStatus.username}</span>
                {instagramStatus.account_type && (
                  <span className="text-ink-lo">
                    {" "}
                    ({instagramStatus.account_type.toLowerCase()})
                  </span>
                )}
              </p>
              {instagramStatus.expires_at && (
                <p className="text-xs text-ink-lo">
                  Token expires:{" "}
                  {new Date(instagramStatus.expires_at).toLocaleString()}
                </p>
              )}
              <button onClick={disconnectInstagram} className={LINK_BTN}>
                Disconnect
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-xs text-ink-lo">
                Instagram uses Meta&apos;s OAuth (Instagram Login). Requires a
                Creator/Business account. You&apos;ll be redirected to authorize,
                then back here.
              </p>
              <button
                onClick={connectInstagram}
                disabled={instagramConnecting}
                className={PRIMARY_BTN}
              >
                {instagramConnecting ? "Redirecting…" : "Connect Instagram"}
              </button>
            </div>
          )}
          {instagramError && (
            <Banner tone="error" className="mt-4">
              <span className="font-mono break-all">{instagramError}</span>
            </Banner>
          )}
        </Section>
      )}

      {!xLoading && xStatus?.enabled && (
        <Section title="X">
          {xStatus.connected ? (
            <div className="space-y-3">
              <p className="text-sm text-ink-hi">
                Connected as{" "}
                <span className="font-medium">@{xStatus.username}</span>
                {xStatus.display_name && (
                  <span className="text-ink-lo"> ({xStatus.display_name})</span>
                )}
              </p>
              {xStatus.expires_at && (
                <p className="text-xs text-ink-lo">
                  Token expires:{" "}
                  {new Date(xStatus.expires_at).toLocaleString()} (auto-refreshes)
                </p>
              )}
              <button onClick={disconnectX} className={LINK_BTN}>
                Disconnect
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-xs text-ink-lo">
                X uses OAuth 2.0. You&apos;ll be redirected to authorize, then
                back here. Note: the X API is paid — each publish costs ~$0.015.
              </p>
              <button onClick={connectX} disabled={xConnecting} className={PRIMARY_BTN}>
                {xConnecting ? "Redirecting…" : "Connect X"}
              </button>
            </div>
          )}
          {xError && (
            <Banner tone="error" className="mt-4">
              <span className="font-mono break-all">{xError}</span>
            </Banner>
          )}
        </Section>
      )}
    </div>
  );
}
