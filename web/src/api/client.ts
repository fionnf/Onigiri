import type {
  Collection,
  Job,
  Me,
  Profile,
  Recipe,
  RecipeList,
  ScaledRecipe,
  Stats,
  Suggestion,
  TagWithCount,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const OFFLINE_MESSAGE = "You're offline. This needs a connection.";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      credentials: "same-origin",
      ...init,
      headers: {
        ...(init.body && !(init.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new ApiError(0, OFFLINE_MESSAGE);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* the body was not JSON; the status text will do */
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export type Progress = (sent: number, total: number) => void;

/**
 * POST a form with upload progress. fetch cannot report upload progress, and a
 * phone sending a video over mobile data needs to show that something is moving.
 */
function uploadForm<T>(path: string, form: FormData, onProgress?: Progress): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.withCredentials = true;
    xhr.responseType = "text";
    if (onProgress) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(event.loaded, event.total);
      };
    }
    xhr.onload = () => {
      let body: unknown;
      try {
        body = xhr.responseText ? JSON.parse(xhr.responseText) : undefined;
      } catch {
        body = undefined;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as T);
        return;
      }
      const detail = (body as { detail?: unknown } | undefined)?.detail;
      reject(
        new ApiError(
          xhr.status,
          typeof detail === "string" ? detail : xhr.statusText || "Upload failed",
        ),
      );
    };
    xhr.onerror = () =>
      reject(new ApiError(0, "The upload could not reach the server. Check your connection."));
    xhr.ontimeout = () => reject(new ApiError(0, "The upload timed out."));
    xhr.send(form);
  });
}

const qs = (params: Record<string, unknown>): string => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      for (const item of value) search.append(key, String(item));
    } else {
      search.set(key, String(value));
    }
  }
  const text = search.toString();
  return text ? `?${text}` : "";
};

export interface RecipeQuery {
  q?: string;
  tag?: string[];
  collection?: string;
  status?: string;
  favorite?: boolean;
  max_total_min?: number;
  sort?: string;
  limit?: number;
  offset?: number;
}

export const api = {
  // auth
  me: () => request<Me>("/api/auth/me"),
  login: (email: string, password: string) =>
    request<Me>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),

  // capture
  ingest: (payload: { url?: string; text?: string }) =>
    request<Job>("/api/ingest", { method: "POST", body: JSON.stringify(payload) }),
  ingestFiles: (
    files: File[],
    extra: { url?: string; text?: string } = {},
    onProgress?: Progress,
  ) => {
    const form = new FormData();
    for (const file of files) form.append("files", file, file.name);
    if (extra.url) form.append("url", extra.url);
    if (extra.text) form.append("text", extra.text);
    return uploadForm<Job>("/api/ingest/upload", form, onProgress);
  },
  jobs: (activeOnly = false) => request<Job[]>(`/api/jobs${qs({ active_only: activeOnly })}`),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  jobInput: (id: string, text: string) =>
    request<Job>(`/api/jobs/${id}/input`, { method: "POST", body: JSON.stringify({ text }) }),
  jobInputFiles: (id: string, files: File[], text?: string, onProgress?: Progress) => {
    const form = new FormData();
    for (const file of files) form.append("files", file, file.name);
    if (text) form.append("text", text);
    return uploadForm<Job>(`/api/jobs/${id}/input/upload`, form, onProgress);
  },
  retryJob: (id: string) => request<Job>(`/api/jobs/${id}/retry`, { method: "POST" }),
  deleteJob: (id: string) => request<void>(`/api/jobs/${id}`, { method: "DELETE" }),

  // recipes
  recipes: (query: RecipeQuery = {}) => request<RecipeList>(`/api/recipes${qs({ ...query })}`),
  recipe: (id: string) => request<Recipe>(`/api/recipes/${id}`),
  createRecipe: (payload: unknown) =>
    request<Recipe>("/api/recipes", { method: "POST", body: JSON.stringify(payload) }),
  updateRecipe: (id: string, payload: unknown) =>
    request<Recipe>(`/api/recipes/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteRecipe: (id: string) => request<void>(`/api/recipes/${id}`, { method: "DELETE" }),
  reextract: (id: string) => request<Recipe>(`/api/recipes/${id}/reextract`, { method: "POST" }),
  scaled: (id: string, servings?: number, units?: string) =>
    request<ScaledRecipe>(`/api/recipes/${id}/scaled${qs({ servings, units })}`),
  similar: (id: string) => request<Recipe[]>(`/api/recipes/${id}/similar`),
  addCookLog: (id: string, payload: { rating?: number; notes?: string; servings_made?: number }) =>
    request<unknown>(`/api/recipes/${id}/cooklog`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  addTag: (id: string, name: string) =>
    request<Recipe>(`/api/recipes/${id}/tags`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  removeTag: (id: string, tagId: string) =>
    request<Recipe>(`/api/recipes/${id}/tags/${tagId}`, { method: "DELETE" }),

  // library
  tags: () => request<TagWithCount[]>("/api/tags"),
  deleteTag: (id: string) => request<void>(`/api/tags/${id}`, { method: "DELETE" }),
  collections: () => request<Collection[]>("/api/collections"),
  createCollection: (name: string) =>
    request<Collection>("/api/collections", { method: "POST", body: JSON.stringify({ name }) }),
  deleteCollection: (id: string) => request<void>(`/api/collections/${id}`, { method: "DELETE" }),
  addToCollection: (collectionId: string, recipeId: string) =>
    request<void>(`/api/collections/${collectionId}/items/${recipeId}`, { method: "POST" }),
  removeFromCollection: (collectionId: string, recipeId: string) =>
    request<void>(`/api/collections/${collectionId}/items/${recipeId}`, { method: "DELETE" }),
  stats: () => request<Stats>("/api/stats"),

  // memory
  profile: () => request<Profile>("/api/me/profile"),
  updateProfile: (payload: Partial<Profile>) =>
    request<Profile>("/api/me/profile", { method: "PUT", body: JSON.stringify(payload) }),
  suggestions: () => request<Suggestion[]>("/api/me/profile/suggestions"),
  refreshSuggestions: () =>
    request<Suggestion[]>("/api/me/profile/suggestions/refresh", { method: "POST" }),
  acceptSuggestion: (id: string) =>
    request<Profile>(`/api/me/profile/suggestions/${id}/accept`, { method: "POST" }),
  dismissSuggestion: (id: string) =>
    request<void>(`/api/me/profile/suggestions/${id}/dismiss`, { method: "POST" }),
};
