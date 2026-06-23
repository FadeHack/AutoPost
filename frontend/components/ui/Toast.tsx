"use client";

import { createContext, useCallback, useContext, useState } from "react";
import { Banner, type BannerTone } from "./Banner";

// Transient notifications for actions that complete off-screen (publish fired,
// trends refreshed). Built on Banner so toasts and inline alerts share one
// visual language. Mounted once by AppShell; call via `useToast()`.

type Toast = { id: number; tone: BannerTone; title: string; body?: string };

type ToastContextValue = {
  notify: (t: { tone?: BannerTone; title: string; body?: string }) => void;
};

const ToastContext = createContext<ToastContextValue>({ notify: () => {} });

export function useToast() {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const notify = useCallback(
    ({ tone = "info", title, body }: { tone?: BannerTone; title: string; body?: string }) => {
      const id = Date.now() + Math.random();
      setToasts((prev) => [...prev, { id, tone, title, body }]);
      window.setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, 5000);
    },
    [],
  );

  const dismiss = (id: number) =>
    setToasts((prev) => prev.filter((t) => t.id !== id));

  return (
    <ToastContext.Provider value={{ notify }}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} className="pointer-events-auto">
            <Banner tone={t.tone} title={t.title} onDismiss={() => dismiss(t.id)}>
              {t.body}
            </Banner>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
