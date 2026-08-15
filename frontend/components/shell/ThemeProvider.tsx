"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

// Dual-theme control (DESIGN.md §3/§6). Warm-paper light + refined dark share
// one token contract in globals.css; this only flips `data-theme` on <html>.
// A no-flash inline script in layout.tsx sets the initial attribute before
// paint — this provider takes over for runtime toggling + system-change sync.

export const THEME_STORAGE_KEY = "autopost:theme";

// "system" follows the OS; "light"/"dark" pin an explicit choice.
export type ThemePref = "light" | "dark" | "system";
type Resolved = "light" | "dark";

type ThemeContextValue = {
  /** The user's stored preference (may be "system"). */
  pref: ThemePref;
  /** The concrete theme actually applied right now. */
  resolved: Resolved;
  setPref: (p: ThemePref) => void;
  /** Convenience: cycle light ↔ dark (drops "system" into an explicit pin). */
  toggle: () => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

function systemResolved(): Resolved {
  if (typeof window === "undefined") return "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function readStoredPref(): ThemePref {
  if (typeof window === "undefined") return "system";
  const s = window.localStorage.getItem(THEME_STORAGE_KEY);
  return s === "light" || s === "dark" ? s : "system";
}

function apply(resolved: Resolved) {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", resolved);
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Lazy init keeps SSR/first-client render aligned with the no-flash script.
  const [pref, setPrefState] = useState<ThemePref>(readStoredPref);
  const [resolved, setResolved] = useState<Resolved>(() =>
    pref === "system" ? systemResolved() : pref,
  );

  const setPref = useCallback((p: ThemePref) => {
    setPrefState(p);
    try {
      if (p === "system") window.localStorage.removeItem(THEME_STORAGE_KEY);
      else window.localStorage.setItem(THEME_STORAGE_KEY, p);
    } catch {
      /* storage may be unavailable (private mode) — theme still applies */
    }
    const next = p === "system" ? systemResolved() : p;
    setResolved(next);
    apply(next);
  }, []);

  const toggle = useCallback(() => {
    setPref(resolved === "dark" ? "light" : "dark");
  }, [resolved, setPref]);

  // When following the system and the OS flips, track it live.
  useEffect(() => {
    if (pref !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      const next = systemResolved();
      setResolved(next);
      apply(next);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [pref]);

  const value = useMemo(
    () => ({ pref, resolved, setPref, toggle }),
    [pref, resolved, setPref, toggle],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
