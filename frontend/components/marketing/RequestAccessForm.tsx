"use client";

import { useState } from "react";
import { apiPostPublic } from "@/lib/api";

// Public access-request form (Phase 14 Chunk H) — posts to the unauthenticated
// `POST /access-requests`. Includes the backend's honeypot field (`website`,
// visually hidden) so bots that fill every input get silently dropped. The
// endpoint always 202s opaquely, so any non-error response is treated as
// "received" — we never reveal whether the email was new, duplicate, or dropped.

type State = "idle" | "sending" | "sent" | "error";

export default function RequestAccessForm() {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [company, setCompany] = useState("");
  const [reason, setReason] = useState("");
  const [website, setWebsite] = useState(""); // honeypot
  const [state, setState] = useState<State>("idle");
  const [error, setError] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setState("sending");
    setError("");
    try {
      await apiPostPublic("/access-requests", {
        email,
        name: name || null,
        company: company || null,
        reason: reason || null,
        website: website || null,
      });
      setState("sent");
    } catch {
      // Keep it generic — the endpoint is opaque by design.
      setError("Something went wrong. Please try again.");
      setState("error");
    }
  };

  if (state === "sent") {
    return (
      <div className="rounded-lg border border-status-published/40 bg-status-published/10 p-6 text-center">
        <p className="font-serif text-xl text-ink-hi">Request received.</p>
        <p className="mt-2 text-sm text-ink-mid">
          If you&apos;re approved, an invite lands in your inbox. Keep an eye on{" "}
          <span className="text-ink-hi">{email}</span>.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <input
          type="email"
          required
          placeholder="you@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded-md border border-border bg-surface-2 px-4 py-3 text-sm text-ink-hi placeholder:text-ink-lo focus:border-accent focus:outline-none"
        />
        <input
          type="text"
          placeholder="Your name (optional)"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full rounded-md border border-border bg-surface-2 px-4 py-3 text-sm text-ink-hi placeholder:text-ink-lo focus:border-accent focus:outline-none"
        />
      </div>
      <input
        type="text"
        placeholder="Company (optional)"
        value={company}
        onChange={(e) => setCompany(e.target.value)}
        className="w-full rounded-md border border-border bg-surface-2 px-4 py-3 text-sm text-ink-hi placeholder:text-ink-lo focus:border-accent focus:outline-none"
      />
      <textarea
        placeholder="What would you use it for? (optional)"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        rows={3}
        className="w-full resize-none rounded-md border border-border bg-surface-2 px-4 py-3 text-sm text-ink-hi placeholder:text-ink-lo focus:border-accent focus:outline-none"
      />

      {/* Honeypot — hidden from humans, catnip for bots. aria-hidden + off-screen,
          never tab-focusable. A non-empty value ⇒ the backend drops the row. */}
      <div aria-hidden className="absolute left-[-9999px] top-[-9999px] h-0 w-0 overflow-hidden">
        <label>
          Website
          <input
            type="text"
            tabIndex={-1}
            autoComplete="off"
            value={website}
            onChange={(e) => setWebsite(e.target.value)}
          />
        </label>
      </div>

      <button
        type="submit"
        disabled={state === "sending"}
        className="w-full rounded-md bg-accent px-5 py-3 text-sm font-medium text-accent-ink transition-opacity hover:opacity-90 disabled:opacity-50"
      >
        {state === "sending" ? "Requesting…" : "Request access"}
      </button>
      {error && <p className="text-sm text-status-failed">{error}</p>}
      <p className="text-center text-xs text-ink-lo">
        Already invited?{" "}
        <a href="/login" className="text-ink-mid underline hover:text-ink-hi">
          Sign in
        </a>
      </p>
    </form>
  );
}
