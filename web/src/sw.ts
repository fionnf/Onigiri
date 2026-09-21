/// <reference lib="webworker" />
import { cleanupOutdatedCaches, precacheAndRoute } from "workbox-precaching";

declare const self: ServiceWorkerGlobalScope;

cleanupOutdatedCaches();
precacheAndRoute(self.__WB_MANIFEST);

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
