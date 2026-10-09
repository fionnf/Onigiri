/// <reference lib="webworker" />
import { CacheableResponsePlugin } from "workbox-cacheable-response";
import { ExpirationPlugin } from "workbox-expiration";
import {
  cleanupOutdatedCaches,
  createHandlerBoundToURL,
  precacheAndRoute,
} from "workbox-precaching";
import { NavigationRoute, registerRoute } from "workbox-routing";
import { CacheFirst, NetworkFirst } from "workbox-strategies";

declare const self: ServiceWorkerGlobalScope;

cleanupOutdatedCaches();
precacheAndRoute(self.__WB_MANIFEST);

// ------------------------------------------------------------------ offline
// The kitchen is where the signal drops. Every recipe opened, and every recipe
// the app warms in the background, stays readable without a connection.

// Any app route opens the app shell, so /r/<id> works offline after a reload.
registerRoute(
  new NavigationRoute(createHandlerBoundToURL("/index.html"), {
    denylist: [/^\/api\//, /^\/share-target/],
  }),
);

const READABLE_API = [
  /^\/api\/auth\/me$/,
  /^\/api\/recipes(\/[^/]+)?$/,
  /^\/api\/recipes\/[^/]+\/scaled$/,
  /^\/api\/(tags|collections|stats)$/,
  /^\/api\/me\/profile$/,
];

// Fresh data when online, the last copy when not. Only same-origin GETs that
// returned 200 are kept, so an error page never replaces a good copy.
registerRoute(
  ({ url, request, sameOrigin }) =>
    sameOrigin && request.method === "GET" && READABLE_API.some((re) => re.test(url.pathname)),
  new NetworkFirst({
    cacheName: "onigiri-api",
    networkTimeoutSeconds: 5,
    plugins: [
      new CacheableResponsePlugin({ statuses: [200] }),
      new ExpirationPlugin({ maxEntries: 600, maxAgeSeconds: 60 * 60 * 24 * 90 }),
    ],
  }),
);

// Photos never change once stored, so they are served from the phone first.
registerRoute(
  ({ url, request, sameOrigin }) =>
    sameOrigin && request.method === "GET" && url.pathname.startsWith("/api/media/"),
  new CacheFirst({
    cacheName: "onigiri-media",
    plugins: [
      new CacheableResponsePlugin({ statuses: [200] }),
      new ExpirationPlugin({
        maxEntries: 400,
        maxAgeSeconds: 60 * 60 * 24 * 180,
        purgeOnQuotaError: true,
      }),
    ],
  }),
);

// Signing out must not leave the recipes readable on a shared device.
self.addEventListener("message", (event) => {
  if (event.data?.type === "signed-out") {
    event.waitUntil(
      Promise.all([caches.delete("onigiri-api"), caches.delete("onigiri-media")]).then(() => {}),
    );
  }
});

self.addEventListener("install", () => {
  void self.skipWaiting();
});
self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

const SHARE_DB = "onigiri-share";
const SHARE_STORE = "payloads";

function openShareDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(SHARE_DB, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(SHARE_STORE)) {
        request.result.createObjectStore(SHARE_STORE, { keyPath: "id" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function stashShare(form: FormData): Promise<void> {
  const files = form.getAll("files").filter((entry): entry is File => entry instanceof File);
  const payload = {
    id: "pending",
    url: String(form.get("url") ?? ""),
    text: String(form.get("text") ?? ""),
    title: String(form.get("title") ?? ""),
    files,
  };
  const db = await openShareDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(SHARE_STORE, "readwrite");
    tx.objectStore(SHARE_STORE).put(payload);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  db.close();
}

/**
 * The share sheet POSTs here from outside the site, which a SameSite=Lax session
 * cookie would not survive. Intercepting the navigation keeps the whole exchange
 * inside the app: the payload is stashed locally and the page uploads it as a
 * normal same-origin request once it opens.
 */
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "POST" || url.pathname !== "/share-target") return;

  event.respondWith(
    (async () => {
      try {
        await stashShare(await event.request.formData());
      } catch {
        // Fall through: the Add screen still opens, just empty.
      }
      return Response.redirect("/add?shared=1", 303);
    })(),
  );
});
