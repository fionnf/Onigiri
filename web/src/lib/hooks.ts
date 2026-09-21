import type { Job } from "@/api/types";
import { useCallback, useEffect, useRef, useState } from "react";

/** Delay a fast-changing value so search does not fire on every keystroke. */
export function useDebounced<T>(value: T, delay = 250): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return settled;
}

export type Theme = "system" | "light" | "dark";

export function useTheme(): [Theme, (next: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem("onigiri.theme") as Theme) || "system",
  );
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    localStorage.setItem("onigiri.theme", theme);
  }, [theme]);
  return [theme, setTheme];
}

/** Keep the screen on while cooking. Quietly does nothing where unsupported. */
export function useWakeLock(active: boolean): boolean {
  const [held, setHeld] = useState(false);
  const lockRef = useRef<WakeLockSentinel | null>(null);

  useEffect(() => {
    let cancelled = false;

    const acquire = async () => {
      if (!("wakeLock" in navigator)) return;
      try {
        const lock = await navigator.wakeLock.request("screen");
        if (cancelled) {
          await lock.release();
          return;
        }
        lockRef.current = lock;
        setHeld(true);
        lock.addEventListener("release", () => setHeld(false));
      } catch {
        setHeld(false);
      }
    };

    const onVisible = () => {
      if (document.visibilityState === "visible" && active && !lockRef.current) void acquire();
    };

    if (active) {
      void acquire();
      document.addEventListener("visibilitychange", onVisible);
    }

    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisible);
      lockRef.current?.release().catch(() => {});
      lockRef.current = null;
      setHeld(false);
    };
  }, [active]);

  return held;
}

type ShortcutMap = Record<string, (event: KeyboardEvent) => void>;

/** Single-key shortcuts, ignored while the cook is typing. */
export function useShortcuts(map: ShortcutMap, enabled = true): void {
  const mapRef = useRef(map);
  mapRef.current = map;

  useEffect(() => {
    if (!enabled) return;
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable);
      if (typing && event.key !== "Escape") return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const action = mapRef.current[event.key];
      if (action) {
        event.preventDefault();
        action(event);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [enabled]);
}

/** Follow one capture over server-sent events, falling back to polling. */
export function useJobStream(jobId: string | undefined): Job | null {
  const [job, setJob] = useState<Job | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let closed = false;
    let poll: ReturnType<typeof setInterval> | undefined;

    const source = new EventSource(`/api/jobs/${jobId}/events`, { withCredentials: true });
    source.addEventListener("job", (event) => {
      if (closed) return;
      try {
        setJob(JSON.parse((event as MessageEvent).data) as Job);
      } catch {
        /* a malformed frame is not worth breaking the screen over */
      }
    });
    source.onerror = () => {
      source.close();
      if (closed || poll) return;
      poll = setInterval(async () => {
        try {
          const response = await fetch(`/api/jobs/${jobId}`, { credentials: "same-origin" });
          if (!response.ok) return;
          const next = (await response.json()) as Job;
          setJob(next);
          if (["done", "failed", "needs_input"].includes(next.status) && poll) {
            clearInterval(poll);
            poll = undefined;
          }
        } catch {
          /* keep trying until the screen goes away */
        }
      }, 1500);
    };

    return () => {
      closed = true;
      source.close();
      if (poll) clearInterval(poll);
    };
  }, [jobId]);

  return job;
}

/** A value kept in localStorage, for per-device preferences only. */
export function useLocal<T>(key: string, initial: T): [T, (next: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = localStorage.getItem(key);
      return stored ? (JSON.parse(stored) as T) : initial;
    } catch {
      return initial;
    }
  });
  const update = useCallback(
    (next: T) => {
      setValue(next);
      try {
        localStorage.setItem(key, JSON.stringify(next));
      } catch {
        /* private browsing; the preference is simply not remembered */
      }
    },
    [key],
  );
  return [value, update];
}

export interface Timer {
  id: number;
  label: string;
  total: number;
  remaining: number;
  running: boolean;
}

/** Several kitchen timers at once, counted down from wall-clock time. */
export function useTimers() {
  const [timers, setTimers] = useState<Timer[]>([]);
  const deadlines = useRef(new Map<number, number>());

  useEffect(() => {
    if (!timers.some((t) => t.running)) return;
    const tick = setInterval(() => {
      setTimers((current) =>
        current.map((timer) => {
          if (!timer.running) return timer;
          const deadline = deadlines.current.get(timer.id);
          if (!deadline) return timer;
          const remaining = Math.max(0, Math.round((deadline - Date.now()) / 1000));
          if (remaining === 0 && timer.remaining > 0) ring();
          return { ...timer, remaining, running: remaining > 0 };
        }),
      );
    }, 250);
    return () => clearInterval(tick);
  }, [timers]);

  const start = useCallback((seconds: number, label: string) => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    deadlines.current.set(id, Date.now() + seconds * 1000);
    setTimers((current) => [
      ...current,
      { id, label, total: seconds, remaining: seconds, running: true },
    ]);
  }, []);

  const stop = useCallback((id: number) => {
    deadlines.current.delete(id);
    setTimers((current) => current.filter((timer) => timer.id !== id));
  }, []);

  const toggle = useCallback((id: number) => {
    setTimers((current) =>
      current.map((timer) => {
        if (timer.id !== id) return timer;
        if (timer.running) {
          deadlines.current.delete(id);
          return { ...timer, running: false };
        }
        deadlines.current.set(id, Date.now() + timer.remaining * 1000);
        return { ...timer, running: true };
      }),
    );
  }, []);

  return { timers, start, stop, toggle };
}

function ring(): void {
  try {
    if ("vibrate" in navigator) navigator.vibrate([200, 100, 200]);
    const Ctx =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.2, ctx.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 1.2);
    osc.start();
    osc.stop(ctx.currentTime + 1.3);
    setTimeout(() => ctx.close().catch(() => {}), 1600);
  } catch {
    /* a silent timer is still a timer */
  }
}
