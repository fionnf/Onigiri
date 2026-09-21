/**
 * The service worker catches the share-target POST and stashes it here, because a
 * cross-site POST navigation would not carry the SameSite=Lax session cookie.
 */
const DB_NAME = "onigiri-share";
const STORE = "payloads";

export interface SharedPayload {
  url: string;
  text: string;
  title: string;
  files: File[];
}

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) {
        request.result.createObjectStore(STORE, { keyPath: "id" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

/** Read the pending share and clear it, so a reload does not capture twice. */
export async function takeShared(): Promise<SharedPayload | null> {
  try {
    const db = await open();
    const value = await new Promise<SharedPayload | undefined>((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      const store = tx.objectStore(STORE);
      const get = store.get("pending");
      get.onsuccess = () => {
        store.delete("pending");
        resolve(get.result as SharedPayload | undefined);
      };
      get.onerror = () => reject(get.error);
    });
    db.close();
    if (!value) return null;
    return {
      url: value.url ?? "",
      text: value.text ?? "",
      title: value.title ?? "",
      files: Array.isArray(value.files) ? value.files : [],
    };
  } catch {
    return null;
  }
}
