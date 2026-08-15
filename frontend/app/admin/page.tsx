"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/components/auth-provider";
import { useMe } from "@/lib/useMe";
import RequestsQueue from "@/components/admin/RequestsQueue";
import UsersTable from "@/components/admin/UsersTable";

// Admin panel (Phase 14 Chunk G). Admin-only control surface: review the public
// access-request queue and manage users. Gated twice — an unauthenticated
// visitor goes to /login, a signed-in non-admin is bounced to Today. The `?tab=`
// param deep-links each panel (mirrors Settings).

const TABS = [
  { id: "requests", label: "Requests" },
  { id: "users", label: "Users" },
] as const;

type TabId = (typeof TABS)[number]["id"];

function AdminInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { session, loading } = useAuth();
  const { me, loading: meLoading } = useMe();

  useEffect(() => {
    if (!loading && !session) router.replace("/login");
  }, [loading, session, router]);

  // Non-admins never see admin surfaces — bounce to Today once role resolves.
  useEffect(() => {
    if (session && !meLoading && me && me.role !== "admin") router.replace("/");
  }, [session, meLoading, me, router]);

  if (loading || !session || meLoading || !me) {
    return <main className="flex-1 p-8 text-ink-lo">Loading…</main>;
  }
  if (me.role !== "admin") {
    return <main className="flex-1 p-8 text-ink-lo">Redirecting…</main>;
  }

  const raw = searchParams.get("tab");
  const active: TabId = TABS.some((t) => t.id === raw) ? (raw as TabId) : "requests";

  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-10">
      <header className="mb-8">
        <h1 className="font-display text-3xl tracking-tight text-ink-hi">Admin</h1>
        <p className="mt-2 text-sm text-ink-mid">
          Review access requests and manage who can use the platform.
        </p>
      </header>

      <nav className="mb-8 flex flex-wrap gap-1 border-b border-border">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => router.replace(`/admin?tab=${t.id}`)}
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

      {active === "requests" && <RequestsQueue />}
      {active === "users" && <UsersTable />}
    </main>
  );
}

export default function AdminPage() {
  return (
    <Suspense fallback={<main className="flex-1 p-8 text-ink-lo">Loading…</main>}>
      <AdminInner />
    </Suspense>
  );
}
