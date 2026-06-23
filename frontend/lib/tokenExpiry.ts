// Single source of truth for LinkedIn token-health tiers (DESIGN.md §2).
// Standard LinkedIn dev apps don't issue refresh tokens, so the ~60-day access
// token must be manually reconnected — this drives the global health pill and
// the Today screen so day-60 is never a surprise. Silent >10d, amber ≤10d,
// red ≤3d or already expired.

export type TokenExpiryLevel = "ok" | "amber" | "red";

export type TokenExpiry = {
  level: TokenExpiryLevel;
  title: string;
  subtitle: string;
};

export function tokenExpiry(expiresAt: string | null): TokenExpiry | null {
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
