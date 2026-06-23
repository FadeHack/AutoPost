"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/components/auth-provider";
import Connections from "@/components/settings/Connections";
import Prompts from "@/components/settings/Prompts";
import Templates from "@/components/settings/Templates";
import VoiceRules from "@/components/settings/VoiceRules";

// Settings (DESIGN.md §5G). Sub-nav: Connections · Prompts · Templates · Voice.
// The active tab lives in `?tab=` so panels deep-link and the browser back
// button works. Connections shipped early in Chunk D; Prompts/Templates/Voice
// land here in Chunk I.

const TABS = [
  { id: "connections", label: "Connections" },
  { id: "prompts", label: "Prompts" },
  { id: "templates", label: "Templates" },
  { id: "voice", label: "Voice" },
] as const;

type TabId = (typeof TABS)[number]["id"];

function SettingsInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { session, loading } = useAuth();

  useEffect(() => {
    if (!loading && !session) router.replace("/login");
  }, [loading, session, router]);

  if (loading || !session) {
    return <main className="flex-1 p-8 text-ink-lo">Loading…</main>;
  }

  const raw = searchParams.get("tab");
  const active: TabId = TABS.some((t) => t.id === raw)
    ? (raw as TabId)
    : "connections";

  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-10">
      <header className="mb-8">
        <h1 className="font-serif text-3xl tracking-tight text-ink-hi">
          Settings
        </h1>
        <p className="mt-2 text-sm text-ink-mid">
          Platform connections, prompt versions, visual templates, and voice
          rules.
        </p>
      </header>

      <nav className="mb-8 flex flex-wrap gap-1 border-b border-border">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => router.replace(`/settings?tab=${t.id}`)}
            className={
              "border-b-2 px-3 py-2 text-sm transition-colors " +
              (t.id === active
                ? "border-accent font-medium text-ink-hi"
                : "border-transparent text-ink-lo hover:text-ink-mid")
            }
          >
            {t.label}
          </button>
        ))}
      </nav>

      {active === "connections" && <Connections />}
      {active === "prompts" && <Prompts />}
      {active === "templates" && <Templates />}
      {active === "voice" && <VoiceRules />}
    </main>
  );
}

export default function SettingsPage() {
  return (
    <Suspense fallback={<main className="flex-1 p-8 text-ink-lo">Loading…</main>}>
      <SettingsInner />
    </Suspense>
  );
}
