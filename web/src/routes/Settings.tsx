import { api } from "@/api/client";
import { IconDownload, IconTrash } from "@/components/Icons";
import { Confirm, ErrorBox, Spinner } from "@/components/ui";
import { type Theme, useTheme } from "@/lib/hooks";
import { clearOfflineCache, warmOfflineCache } from "@/lib/offline";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

const SHORTCUTS: [string, string][] = [
  ["/", "Focus search"],
  ["j / k", "Move down and up the list"],
  ["Enter", "Open the highlighted recipe"],
  ["n", "Add a recipe"],
  ["g", "Go to the library"],
  ["e", "Edit the open recipe"],
  ["c", "Cook the open recipe"],
  ["s", "Toggle the source panel"],
  ["← / → / space", "Move between steps while cooking"],
  ["Esc", "Leave cooking mode, or clear search"],
];

export function Settings({ onSignedOut }: { onSignedOut: () => void }) {
  const queryClient = useQueryClient();
  const [theme, setTheme] = useTheme();
  const [newCollection, setNewCollection] = useState("");

  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats });
  const tags = useQuery({ queryKey: ["tags"], queryFn: api.tags });
  const collections = useQuery({ queryKey: ["collections"], queryFn: api.collections });
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });

  const createCollection = useMutation({
    mutationFn: () => api.createCollection(newCollection.trim()),
    onSuccess: () => {
      setNewCollection("");
      queryClient.invalidateQueries({ queryKey: ["collections"] });
    },
  });
  const deleteCollection = useMutation({
    mutationFn: api.deleteCollection,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["collections"] }),
  });
  const deleteTag = useMutation({
    mutationFn: api.deleteTag,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tags"] }),
  });
  const saveOffline = useMutation({ mutationFn: () => warmOfflineCache(true) });
  const signOut = useMutation({
    mutationFn: async () => {
      await api.logout();
      await clearOfflineCache();
    },
    onSuccess: onSignedOut,
  });

  const usage = stats.data?.usage_last_30_days;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="text-base font-semibold">Settings</h1>

      <section className="card space-y-2 p-3">
        <h2 className="label">Your bank</h2>
        {stats.isLoading && <Spinner />}
        {stats.data && (
          <table className="w-full text-sm">
            <tbody className="divide-y divide-line">
              <tr>
                <td className="py-1 text-muted">Recipes</td>
                <td className="py-1 text-right tabular-nums">{stats.data.total}</td>
              </tr>
              <tr>
                <td className="py-1 text-muted">Needs review</td>
                <td className="py-1 text-right tabular-nums">{stats.data.needs_review}</td>
              </tr>
              <tr>
                <td className="py-1 text-muted">Favourites</td>
                <td className="py-1 text-right tabular-nums">{stats.data.favorites}</td>
              </tr>
              <tr>
                <td className="py-1 text-muted">Captures in 30 days</td>
                <td className="py-1 text-right tabular-nums">{stats.data.jobs_last_30_days}</td>
              </tr>
            </tbody>
          </table>
        )}
      </section>

      {usage && (
        <section className="card space-y-2 p-3">
          <h2 className="label">What it cost in 30 days</h2>
          <table className="w-full text-sm">
            <tbody className="divide-y divide-line">
              <tr>
                <td className="py-1 text-muted">Tokens in</td>
                <td className="py-1 text-right tabular-nums">
                  {usage.input_tokens.toLocaleString()}
                </td>
              </tr>
              <tr>
                <td className="py-1 text-muted">Tokens out</td>
                <td className="py-1 text-right tabular-nums">
                  {usage.output_tokens.toLocaleString()}
                </td>
              </tr>
              <tr>
                <td className="py-1 text-muted">Audio transcribed</td>
                <td className="py-1 text-right tabular-nums">
                  {Math.round(usage.audio_seconds / 60)} min
                </td>
              </tr>
            </tbody>
          </table>
        </section>
      )}

      <section className="card space-y-2 p-3">
        <h2 className="label">Collections</h2>
        <ul className="divide-y divide-line">
          {collections.data?.map((collection) => (
            <li key={collection.id} className="flex items-center gap-2 py-1.5 text-sm">
              <span className="flex-1">{collection.name}</span>
              <span className="text-xs text-faint">{collection.count}</span>
              <Confirm
                message={`Delete the collection "${collection.name}"? The recipes stay.`}
                onConfirm={() => deleteCollection.mutate(collection.id)}
              >
                <IconTrash className="h-3.5 w-3.5" />
              </Confirm>
            </li>
          ))}
        </ul>
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (newCollection.trim()) createCollection.mutate();
          }}
        >
          <input
            className="field"
            placeholder="New collection, e.g. Weeknight"
            value={newCollection}
            onChange={(event) => setNewCollection(event.target.value)}
          />
          <button type="submit" className="btn btn-sm" disabled={!newCollection.trim()}>
            Add
          </button>
        </form>
        {createCollection.isError && <ErrorBox error={createCollection.error} />}
      </section>

      <section className="card space-y-2 p-3">
        <h2 className="label">Tags</h2>
        <div className="flex flex-wrap gap-1.5">
          {tags.data?.map((tag) => (
            <span key={tag.id} className="chip">
              {tag.name}
              <span className="text-faint">{tag.count}</span>
              <button
                type="button"
                className="-my-1 -mr-2 inline-flex h-8 w-8 items-center justify-center rounded-full text-base text-faint hover:text-danger"
                onClick={() => {
                  if (window.confirm(`Delete the tag "${tag.name}" everywhere?`)) {
                    deleteTag.mutate(tag.id);
                  }
                }}
                aria-label={`Delete tag ${tag.name}`}
              >
                ×
              </button>
            </span>
          ))}
          {tags.data?.length === 0 && <p className="text-sm text-muted">No tags yet.</p>}
        </div>
      </section>

      <section className="card space-y-2 p-3">
        <h2 className="label">Appearance</h2>
        <div className="flex gap-1.5">
          {(["system", "light", "dark"] as Theme[]).map((value) => (
            <button
              key={value}
              type="button"
              className={`chip ${theme === value ? "chip-on" : ""}`}
              onClick={() => setTheme(value)}
            >
              {value}
            </button>
          ))}
        </div>
      </section>

      <section className="card space-y-2 p-3" id="shortcuts">
        <h2 className="label">Keyboard</h2>
        <table className="w-full text-sm">
          <tbody className="divide-y divide-line">
            {SHORTCUTS.map(([keys, what]) => (
              <tr key={keys}>
                <td className="w-40 py-1">
                  <span className="kbd">{keys}</span>
                </td>
                <td className="py-1 text-muted">{what}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card space-y-2 p-3">
        <h2 className="label">On this phone</h2>
        <p className="text-sm text-muted">
          Your 100 most recent recipes and their photos are kept on this device, so they open in the
          kitchen without signal. This refreshes on its own every few hours.
        </p>
        <button
          type="button"
          className="btn btn-sm w-fit"
          onClick={() => saveOffline.mutate()}
          disabled={saveOffline.isPending}
        >
          <IconDownload className="h-3.5 w-3.5" />
          {saveOffline.isPending ? "Saving…" : "Save recipes for offline now"}
        </button>
        {saveOffline.isSuccess && (
          <p className="text-xs text-muted">Saved {saveOffline.data} recipes on this phone.</p>
        )}
        {saveOffline.isError && <ErrorBox error={saveOffline.error} />}
      </section>

      <section className="card space-y-2 p-3">
        <h2 className="label">Your data</h2>
        <p className="text-sm text-muted">
          Every recipe as Markdown, plus one JSON file with everything.
        </p>
        <a href="/api/export" className="btn btn-sm w-fit">
          <IconDownload className="h-3.5 w-3.5" />
          Export everything
        </a>
      </section>

      <section className="card space-y-2 p-3">
        <h2 className="label">Account</h2>
        <p className="text-sm text-muted">{me.data?.email}</p>
        <button
          type="button"
          className="btn btn-sm w-fit"
          onClick={() => signOut.mutate()}
          disabled={signOut.isPending}
        >
          Sign out
        </button>
      </section>
    </div>
  );
}
