"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { useAuth } from "@/components/auth-provider";
import { PostCardMock } from "@/components/marketing/PostCardMock";

// Invited-user door (Phase 14). Same minimal-dark + serif identity as the
// landing and studio. Split layout: the artifact + tagline on the left (desktop
// only), the magic-link form on the right. `shouldCreateUser: false` keeps it
// invite-only — an un-provisioned email gets no link.

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [error, setError] = useState("");
  const router = useRouter();
  const { session, loading } = useAuth();

  useEffect(() => {
    if (!loading && session) router.replace("/");
  }, [loading, session, router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setStatus("sending");
    setError("");
    const { error: err } = await supabase.auth.signInWithOtp({
      email,
      // Invite-only: never create a new auth user from the login screen. An
      // un-invited email gets no magic link (request access on the landing page).
      options: { emailRedirectTo: window.location.origin, shouldCreateUser: false },
    });
    if (err) {
      setError(err.message);
      setStatus("error");
    } else {
      setStatus("sent");
    }
  };

  return (
    <main className="grid min-h-screen bg-bg text-ink-hi lg:grid-cols-2">
      {/* Brand / artifact panel — desktop only */}
      <aside className="hidden flex-col justify-between border-r border-border bg-surface-1/30 p-12 lg:flex">
        <a
          href="/"
          className="flex items-center gap-2.5 font-serif text-lg tracking-tight text-ink-hi"
        >
          <span className="inline-block h-2 w-2 rotate-45 bg-accent" aria-hidden />
          Nestwhirr Studio
        </a>

        <div className="mx-auto w-full max-w-xs">
          <PostCardMock />
        </div>

        <p className="max-w-sm font-serif text-lg italic leading-snug text-ink-mid">
          Founder-voice content, fanned out to every platform from a single
          approve.
        </p>
      </aside>

      {/* Form panel */}
      <section className="flex items-center justify-center px-6 py-16">
        <div className="w-full max-w-sm">
          <a
            href="/"
            className="mb-10 flex items-center gap-2.5 font-serif text-lg tracking-tight text-ink-hi lg:hidden"
          >
            <span className="inline-block h-2 w-2 rotate-45 bg-accent" aria-hidden />
            Nestwhirr Studio
          </a>

          <h1 className="font-serif text-3xl tracking-tight text-ink-hi">
            Sign in
          </h1>
          <p className="mt-2 text-sm text-ink-mid">
            We’ll email you a magic link — no password.
          </p>

          <div className="mt-8">
            {status === "sent" ? (
              <div className="rounded-md border border-status-published/40 bg-status-published/10 p-5 text-sm">
                <p className="text-ink-hi">
                  If <span className="font-medium">{email}</span> has access, a
                  magic link is on its way.
                </p>
                <p className="mt-2 text-ink-mid">
                  Don’t have access yet?{" "}
                  <a href="/#request" className="text-accent underline-offset-2 hover:underline">
                    Request an invite
                  </a>
                  .
                </p>
              </div>
            ) : (
              <form onSubmit={submit} className="space-y-3">
                <input
                  type="email"
                  required
                  placeholder="you@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoFocus
                  className="w-full rounded-md border border-border bg-surface-2 px-4 py-3 text-sm text-ink-hi placeholder:text-ink-lo focus:border-accent focus:outline-none"
                />
                <button
                  type="submit"
                  disabled={status === "sending"}
                  className="w-full rounded-md bg-accent px-5 py-3 text-sm font-medium text-accent-ink transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  {status === "sending" ? "Sending…" : "Send magic link"}
                </button>
                {error && <p className="text-sm text-status-failed">{error}</p>}
                <p className="pt-1 text-center text-xs text-ink-lo">
                  Not invited yet?{" "}
                  <a
                    href="/#request"
                    className="text-ink-mid underline-offset-2 hover:text-ink-hi hover:underline"
                  >
                    Request access
                  </a>
                </p>
              </form>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}
