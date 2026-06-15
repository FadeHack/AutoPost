"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { useAuth } from "@/components/auth-provider";

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
      options: { emailRedirectTo: window.location.origin },
    });
    if (err) {
      setError(err.message);
      setStatus("error");
    } else {
      setStatus("sent");
    }
  };

  return (
    <main className="flex-1 flex items-center justify-center px-4 py-16">
      <div className="w-full max-w-md space-y-8">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">AutoPost</h1>
          <p className="text-sm text-zinc-500 mt-1">Sign in to continue</p>
        </div>

        {status === "sent" ? (
          <div className="rounded border border-green-700 bg-green-950/30 p-4 text-sm">
            Check <span className="font-medium">{email}</span> for a magic link.
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <input
              type="email"
              required
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoFocus
              className="w-full rounded border border-zinc-700 bg-zinc-900 px-4 py-3 text-sm focus:outline-none focus:border-zinc-500"
            />
            <button
              type="submit"
              disabled={status === "sending"}
              className="w-full rounded bg-white text-black font-medium py-3 text-sm hover:bg-zinc-200 disabled:opacity-50"
            >
              {status === "sending" ? "Sending…" : "Send magic link"}
            </button>
            {error && <p className="text-red-400 text-sm">{error}</p>}
          </form>
        )}
      </div>
    </main>
  );
}
