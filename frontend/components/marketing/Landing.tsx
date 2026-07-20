"use client";

import RequestAccessForm from "./RequestAccessForm";
import { PostCardMock } from "./PostCardMock";

// Marketing landing for logged-out visitors (Phase 14 Chunk H). Wears the same
// minimal-dark + serif-display identity as the rendered cards and studio chrome
// (DESIGN.md §3 — "the studio looks like the artifact"), and literally puts the
// artifact — a rendered post card — in the hero. Flat, hairline, no shadows or
// gradients (DESIGN.md §3 Texture). Bands: hero · what-it-does · how-it-works
// (the pipeline spine) · request-access. AppShell renders this bare (no rail).

const PLATFORMS = ["LinkedIn", "Bluesky", "Mastodon", "Threads", "Instagram", "X"];

const CAPABILITIES = [
  {
    n: "01",
    title: "Founder voice, not AI spam",
    body: "Every draft is post-processed to strip the tells — the em-dash seams, the “in today’s fast-paced world,” the tidy closing summary. One opinion per post, hook in the first line.",
  },
  {
    n: "02",
    title: "One approve, six platforms",
    body: "Approve a single idea; it fans out to LinkedIn, Bluesky, Mastodon, Threads, Instagram, and X — each rewritten to its own character budget and shape, never copy-pasted.",
  },
  {
    n: "03",
    title: "Retrieval, not hallucination",
    body: "A retrieval layer pulls what’s actually new from RSS, Hacker News, and Reddit. The model analyzes real signal — it’s never asked to “know the latest.”",
  },
  {
    n: "04",
    title: "The card identity, rendered",
    body: "Posts ship as the locked minimal-dark visual — serif headline, accent strap — rendered from templates to pixel-perfect PNGs. No diffusion gamble.",
  },
];

const PIPELINE = [
  { stage: "Trends", note: "Pulled from real sources" },
  { stage: "Draft", note: "Generated in your voice" },
  { stage: "Approved", note: "One review, one click" },
  { stage: "Scheduled", note: "Queued per platform" },
  { stage: "Published", note: "Fanned out live" },
];

function Wordmark() {
  return (
    <span className="flex items-center gap-2.5 font-serif text-lg tracking-tight text-ink-hi">
      <span className="inline-block h-2 w-2 rotate-45 bg-accent" aria-hidden />
      Nestwhirr Studio
    </span>
  );
}

export default function Landing() {
  return (
    <main className="min-h-screen bg-bg text-ink-hi">
      {/* Top bar */}
      <header className="border-b border-border">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-5">
          <Wordmark />
          <a
            href="/login"
            className="text-sm text-ink-mid transition-colors hover:text-ink-hi"
          >
            Sign in
          </a>
        </div>
      </header>

      {/* Hero — text left, the artifact right */}
      <section className="mx-auto grid w-full max-w-6xl items-center gap-14 px-6 py-16 sm:py-24 lg:grid-cols-[1.1fr_0.9fr]">
        <div>
          <p className="text-xs uppercase tracking-[0.24em] text-ink-lo">
            Founder-voice content studio
          </p>
          <h1 className="mt-6 font-serif text-[2.6rem] leading-[1.05] tracking-tight text-ink-hi sm:text-6xl">
            Publish like a founder.
            <br />
            <span className="italic text-accent">Everywhere.</span> From one
            decision.
          </h1>
          <p className="mt-7 max-w-xl text-lg leading-relaxed text-ink-mid">
            An editorial cockpit that turns what’s actually new into opinionated,
            human posts — and fans a single approve out across every platform,
            each in its own voice and format.
          </p>
          <div className="mt-9 flex flex-wrap items-center gap-3">
            <a
              href="#request"
              className="rounded-md bg-accent px-6 py-3 text-sm font-medium text-accent-ink transition-opacity hover:opacity-90"
            >
              Request access
            </a>
            <a
              href="#how"
              className="rounded-md border border-border px-6 py-3 text-sm text-ink-mid transition-colors hover:border-ink-lo hover:text-ink-hi"
            >
              See how it works
            </a>
          </div>
          <p className="mt-5 text-xs text-ink-lo">Invite-only while we’re early.</p>
        </div>

        <div className="mx-auto w-full max-w-sm lg:mx-0">
          <PostCardMock />
          <div className="mt-6">
            <p className="text-[11px] uppercase tracking-[0.22em] text-ink-lo">
              Same idea, every platform
            </p>
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-ink-mid">
              {PLATFORMS.map((p) => (
                <span key={p}>{p}</span>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* What it does — editorial numbered rows */}
      <section className="border-t border-border bg-surface-1/30">
        <div className="mx-auto w-full max-w-6xl px-6 py-20">
          <h2 className="font-serif text-3xl tracking-tight text-ink-hi">
            What it does
          </h2>
          <div className="mt-12 grid gap-x-12 gap-y-10 sm:grid-cols-2">
            {CAPABILITIES.map((c) => (
              <div key={c.n} className="border-t border-border pt-6">
                <div className="flex items-baseline gap-4">
                  <span className="font-serif text-lg text-accent">{c.n}</span>
                  <div>
                    <h3 className="font-serif text-xl text-ink-hi">{c.title}</h3>
                    <p className="mt-2.5 text-sm leading-relaxed text-ink-mid">
                      {c.body}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works — the pipeline spine */}
      <section id="how" className="scroll-mt-8 border-t border-border">
        <div className="mx-auto w-full max-w-6xl px-6 py-20">
          <h2 className="font-serif text-3xl tracking-tight text-ink-hi">
            How it works
          </h2>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-ink-mid">
            One hard status spine, from raw signal to live post. You live in the
            review loop; the machine handles retrieval, rewriting, rendering, and
            the multi-platform fan-out.
          </p>
          <ol className="mt-12 grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-5">
            {PIPELINE.map((p, i) => (
              <li key={p.stage} className="bg-bg p-5">
                <div className="font-serif text-sm text-accent">
                  {String(i + 1).padStart(2, "0")}
                </div>
                <div className="mt-3 font-serif text-lg text-ink-hi">
                  {p.stage}
                </div>
                <div className="mt-1 text-xs leading-relaxed text-ink-lo">
                  {p.note}
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* Request access */}
      <section
        id="request"
        className="scroll-mt-8 border-t border-border bg-surface-1/30"
      >
        <div className="mx-auto w-full max-w-xl px-6 py-20">
          <h2 className="text-center font-serif text-4xl tracking-tight text-ink-hi">
            Request access
          </h2>
          <p className="mx-auto mt-4 max-w-md text-center text-sm leading-relaxed text-ink-mid">
            We’re onboarding a handful of operators at a time. Tell us where to
            send the invite.
          </p>
          <div className="mt-10">
            <RequestAccessForm />
          </div>
        </div>
      </section>

      <footer className="border-t border-border">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-3 px-6 py-8 text-xs text-ink-lo">
          <Wordmark />
          <span>Founder-voice content, multi-platform.</span>
        </div>
      </footer>
    </main>
  );
}
