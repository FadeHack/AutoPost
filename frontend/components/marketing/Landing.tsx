"use client";

import { motion } from "motion/react";
import RequestAccessForm from "./RequestAccessForm";
import { StudioWalkthrough } from "./StudioWalkthrough";
import { ThemeToggle } from "@/components/shell/ThemeToggle";
import { reveal } from "@/lib/motion";

// Marketing landing for logged-out visitors. Newsroom / print-magazine identity
// (DESIGN.md §3): a masthead, column rules, Fraunces display + Newsreader serif,
// a drop-cap opener. The hero centerpiece is a LIVE studio walkthrough
// (StudioWalkthrough) — the tool demonstrating itself, not a screenshot. Themes
// light/dark automatically because it's built entirely on design tokens.

const PLATFORMS = ["LinkedIn", "Bluesky", "Mastodon", "Threads", "Instagram", "X"];

const CAPABILITIES = [
  {
    n: "01",
    title: "Sounds like you wrote it",
    body: "Opinionated, human, one idea per post. The hook lands in the first line, before anyone taps “see more.” Never generic, never filler.",
  },
  {
    n: "02",
    title: "Approve once, live everywhere",
    body: "Approve a single idea and it reshapes itself for every platform you’ve connected. Each version is written to fit that network, never a blunt copy-paste.",
  },
  {
    n: "03",
    title: "Always about what’s actually new",
    body: "Every post reacts to what’s genuinely happening right now. No stale takes, no invented trends, nothing the model simply guessed at.",
  },
  {
    n: "04",
    title: "On-brand visuals, every time",
    body: "Each post ships with a clean, recognizable graphic that looks designed, not generated. Consistent, publish-ready, unmistakably yours.",
  },
];

const PIPELINE = [
  { stage: "Trends", note: "Pulled from real sources" },
  { stage: "Draft", note: "Generated in your voice" },
  { stage: "Approved", note: "One review, one click" },
  { stage: "Scheduled", note: "Queued per platform" },
  { stage: "Published", note: "Fanned out live" },
];

function Wordmark({ size = "base" }: { size?: "base" | "lg" }) {
  return (
    <span
      className={
        "flex items-center gap-2.5 font-display tracking-tight text-ink-hi " +
        (size === "lg" ? "text-2xl" : "text-lg")
      }
    >
      <span className="inline-block h-2 w-2 rotate-45 bg-accent" aria-hidden />
      Nestwhirr Studio
    </span>
  );
}

function Section({ children, ...rest }: React.ComponentProps<typeof motion.section>) {
  return (
    <motion.section
      variants={reveal}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, margin: "-80px" }}
      {...rest}
    >
      {children}
    </motion.section>
  );
}

export default function Landing() {
  return (
    <main className="min-h-screen bg-bg text-ink-hi">
      {/* Masthead */}
      <header className="border-b border-border">
        <div className="mx-auto w-full max-w-6xl px-6">
          <div className="flex items-center justify-between border-b border-border py-2 text-[11px] uppercase tracking-[0.18em] text-ink-lo">
            <span>Founder-voice content studio</span>
            <span className="hidden sm:inline">Invite-only edition</span>
          </div>
          <div className="flex items-center justify-between py-4">
            <Wordmark size="lg" />
            <div className="flex items-center gap-1">
              <ThemeToggle variant="icon" />
              <a
                href="/login"
                className="px-2 text-sm text-ink-mid transition-colors hover:text-ink-hi"
              >
                Sign in
              </a>
            </div>
          </div>
        </div>
      </header>

      {/* Hero — centered feature headline over the live walkthrough */}
      <section className="mx-auto w-full max-w-6xl px-6 pb-8 pt-14 sm:pt-20">
        <motion.div
          variants={reveal}
          initial="hidden"
          animate="show"
          className="mx-auto max-w-3xl text-center"
        >
          <p className="text-xs uppercase tracking-[0.24em] text-ink-lo">
            Invite-only · founder-voice content studio
          </p>
          <h1 className="mt-5 font-display text-[2.7rem] leading-[1.04] tracking-tight text-ink-hi sm:text-6xl">
            Publish like a founder.
            <br />
            <span className="italic text-accent">Everywhere.</span> From one
            decision.
          </h1>
          <p className="mx-auto mt-6 max-w-xl font-serif text-lg leading-relaxed text-ink-mid">
            An editorial cockpit that turns what’s actually new into opinionated,
            human posts — and fans a single approve out across every platform,
            each in its own voice and format.
          </p>
        </motion.div>

        {/* The centerpiece */}
        <motion.div
          variants={reveal}
          initial="hidden"
          animate="show"
          transition={{ delay: 0.1 }}
          className="mx-auto mt-12 max-w-5xl"
        >
          <StudioWalkthrough />
        </motion.div>

        <div className="mx-auto mt-10 flex max-w-3xl flex-wrap items-center justify-center gap-3">
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
      </section>

      {/* What it does — editorial numbered rows with a drop-cap opener */}
      <Section className="border-t border-border bg-surface-1/40">
        <div className="mx-auto w-full max-w-6xl px-6 py-20">
          <h2 className="font-display text-3xl tracking-tight text-ink-hi">
            What it does
          </h2>
          <div className="mt-12 grid gap-x-12 gap-y-10 sm:grid-cols-2">
            {CAPABILITIES.map((c, i) => (
              <div key={c.n} className="border-t border-border pt-6">
                <div className="flex items-baseline gap-4">
                  <span className="font-display text-lg text-accent">{c.n}</span>
                  <div>
                    <h3 className="font-display text-xl text-ink-hi">{c.title}</h3>
                    <p
                      className={
                        "mt-2.5 text-sm leading-relaxed text-ink-mid " +
                        (i === 0 ? "dropcap" : "")
                      }
                    >
                      {c.body}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </Section>

      {/* How it works — the pipeline spine */}
      <Section id="how" className="scroll-mt-8 border-t border-border">
        <div className="mx-auto w-full max-w-6xl px-6 py-20">
          <h2 className="font-display text-3xl tracking-tight text-ink-hi">
            How it works
          </h2>
          <p className="mt-3 max-w-2xl font-serif text-[15px] leading-relaxed text-ink-mid">
            One hard status spine, from raw signal to live post. You live in the
            review loop; the machine handles retrieval, rewriting, rendering, and
            the multi-platform fan-out.
          </p>
          <ol className="mt-12 grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-5">
            {PIPELINE.map((p, i) => (
              <li key={p.stage} className="bg-bg p-5">
                <div className="font-display text-sm text-accent">
                  {String(i + 1).padStart(2, "0")}
                </div>
                <div className="mt-3 font-display text-lg text-ink-hi">
                  {p.stage}
                </div>
                <div className="mt-1 text-xs leading-relaxed text-ink-lo">
                  {p.note}
                </div>
              </li>
            ))}
          </ol>
          <div className="mt-8">
            <p className="text-[11px] uppercase tracking-[0.22em] text-ink-lo">
              Same idea, every platform
            </p>
            <div className="mt-3 flex flex-wrap items-baseline gap-x-5 gap-y-1.5 font-serif text-sm text-ink-mid">
              {PLATFORMS.map((p) => (
                <span key={p}>{p}</span>
              ))}
              <span className="text-ink-lo">and more</span>
            </div>
          </div>
        </div>
      </Section>

      {/* Request access */}
      <Section
        id="request"
        className="scroll-mt-8 border-t border-border bg-surface-1/40"
      >
        <div className="mx-auto w-full max-w-xl px-6 py-20">
          <h2 className="text-center font-display text-4xl tracking-tight text-ink-hi">
            Request access
          </h2>
          <p className="mx-auto mt-4 max-w-md text-center font-serif text-[15px] leading-relaxed text-ink-mid">
            We’re onboarding a handful of operators at a time. Tell us where to
            send the invite.
          </p>
          <div className="mt-10">
            <RequestAccessForm />
          </div>
        </div>
      </Section>

      <footer className="border-t border-border">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-3 px-6 py-8 text-xs text-ink-lo">
          <Wordmark />
          <span>Founder-voice content, multi-platform.</span>
        </div>
      </footer>
    </main>
  );
}
