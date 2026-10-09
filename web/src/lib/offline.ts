import { useEffect, useState } from "react";

/** Whether the browser believes it has a connection. */
export function useOnline(): boolean {
  const [online, setOnline] = useState(() =>
    typeof navigator === "undefined" ? true : navigator.onLine,
  );
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);
  return online;
}

const WARMED_AT = "onigiri.offline.warmedAt";
const WARM_EVERY_MS = 6 * 60 * 60 * 1000;
const WARM_LIMIT = 100;

interface Summary {
  id: string;
  hero_url: string | null;
  updated_at: string;
}

function preferredUnits(): string {
  try {
    const stored = localStorage.getItem("onigiri.units");
    const value = stored ? (JSON.parse(stored) as string) : "original";
    return ["metric", "us"].includes(value) ? value : "original";
  } catch {
    return "original";
  }
}

/**
 * Fetch recent recipes and their photos once in a while, so the service worker keeps
 * a copy and they open in a kitchen with no signal. Cheap: a hundred small JSON
 * documents and thumbnails, only when online, at most every few hours.
 */
export async function warmOfflineCache(force = false): Promise<number> {
  if (!("serviceWorker" in navigator) || !navigator.onLine) return 0;
  try {
    const last = Number(localStorage.getItem(WARMED_AT) || 0);
    if (!force && Date.now() - last < WARM_EVERY_MS) return 0;
  } catch {
    /* storage blocked; warm anyway */
  }

  await navigator.serviceWorker.ready;
  const response = await fetch(`/api/recipes?limit=${WARM_LIMIT}&sort=recent`, {
    credentials: "same-origin",
  });
  if (!response.ok) return 0;
  const { items } = (await response.json()) as { items: Summary[] };

  // The same addresses the recipe screen asks for, so the saved copies are found.
  const units = preferredUnits();
  const scaledQuery = units === "original" ? "" : `?units=${units}`;
  const urls: string[] = [];
  for (const item of items) {
    urls.push(`/api/recipes/${item.id}`, `/api/recipes/${item.id}/scaled${scaledQuery}`);
    if (item.hero_url) urls.push(item.hero_url);
  }
  for (const extra of ["/api/tags", "/api/collections", "/api/stats", "/api/me/profile"]) {
    urls.push(extra);
  }

  // Four at a time, so a slow phone connection is not flooded.
  let next = 0;
  const worker = async () => {
    while (next < urls.length) {
      const url = urls[next++];
      try {
        await fetch(url, { credentials: "same-origin" });
      } catch {
        /* one failure should not stop the rest */
      }
    }
  };
  await Promise.all([worker(), worker(), worker(), worker()]);

  try {
    localStorage.setItem(WARMED_AT, String(Date.now()));
  } catch {
    /* fine: it simply warms again next time */
  }
  return items.length;
}

/** Tell the service worker to forget cached recipes, for example on sign out. */
export async function clearOfflineCache(): Promise<void> {
  try {
    localStorage.removeItem(WARMED_AT);
  } catch {
    /* ignore */
  }
  if ("serviceWorker" in navigator) {
    const registration = await navigator.serviceWorker.getRegistration();
    registration?.active?.postMessage({ type: "signed-out" });
  }
  if ("caches" in window) {
    await Promise.all([caches.delete("onigiri-api"), caches.delete("onigiri-media")]);
  }
}
