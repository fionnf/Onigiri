import { api } from "@/api/client";
import { IconPlus, IconSearch } from "@/components/Icons";
import { RecipeCard } from "@/components/RecipeCard";
import { Empty, ErrorBox, Spinner } from "@/components/ui";
import { useDebounced, useLocal, useShortcuts } from "@/lib/hooks";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

const SORTS = [
  { value: "recent", label: "Recently updated" },
  { value: "added", label: "Recently added" },
  { value: "title", label: "Title" },
  { value: "time", label: "Quickest" },
];

export function Library() {
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(params.get("q") ?? "");
  const debounced = useDebounced(query, 250);
  const [dense, setDense] = useLocal("onigiri.dense", false);
  const [cursor, setCursor] = useState(0);
  const searchRef = useRef<HTMLInputElement>(null);

  const status = params.get("status") ?? undefined;
  const tag = params.getAll("tag");
  const collection = params.get("collection") ?? undefined;
  const sort = params.get("sort") ?? "recent";
  const favorite = params.get("favorite") === "1" ? true : undefined;

  useEffect(() => {
    const next = new URLSearchParams(params);
    if (debounced) next.set("q", debounced);
    else next.delete("q");
    if (next.toString() !== params.toString()) setParams(next, { replace: true });
  }, [debounced, params, setParams]);

  const recipes = useQuery({
    queryKey: ["recipes", debounced, status, tag, collection, sort, favorite],
    queryFn: () =>
      api.recipes({
        q: debounced || undefined,
        status,
        tag: tag.length ? tag : undefined,
        collection,
        sort,
        favorite,
        limit: 60,
      }),
  });

  const tags = useQuery({ queryKey: ["tags"], queryFn: api.tags });
  const collections = useQuery({ queryKey: ["collections"], queryFn: api.collections });

  const items = recipes.data?.items ?? [];

  useShortcuts({
    "/": () => searchRef.current?.focus(),
    j: () => setCursor((c) => Math.min(c + 1, items.length - 1)),
    k: () => setCursor((c) => Math.max(c - 1, 0)),
    Enter: () => {
      const rows = document.querySelectorAll<HTMLElement>("[data-recipe-row]");
      rows[cursor]?.click();
    },
    Escape: () => {
      setQuery("");
      searchRef.current?.blur();
    },
  });

  useEffect(() => {
    const rows = document.querySelectorAll<HTMLElement>("[data-recipe-row]");
    rows[cursor]?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  const toggleParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    const existing = next.getAll(key);
    if (existing.includes(value)) {
      next.delete(key);
      for (const v of existing.filter((x) => x !== value)) next.append(key, v);
    } else {
      next.append(key, value);
    }
    setParams(next);
  };

  const setParam = (key: string, value?: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {/* On a phone the search gets the whole first row; the rest wraps below it. */}
        <div className="relative w-full min-w-0 sm:w-auto sm:flex-1">
          <IconSearch className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" />
          <input
            ref={searchRef}
            type="search"
            enterKeyHint="search"
            autoCapitalize="off"
            autoCorrect="off"
            className="field pl-9"
            placeholder="Search recipes or ingredients"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {!query && (
            <span className="kbd pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2">
              /
            </span>
          )}
        </div>

        <select
          aria-label="Sort"
          className="field w-auto flex-1 sm:flex-none"
          value={sort}
          onChange={(e) => setParam("sort", e.target.value)}
        >
          {SORTS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>

        <button type="button" className="btn btn-sm" onClick={() => setDense(!dense)}>
          {dense ? "Cards" : "List"}
        </button>

        <Link to="/add" className="btn btn-primary btn-sm hidden sm:inline-flex">
          <IconPlus className="h-3.5 w-3.5" />
          Add
        </Link>
      </div>

      <div className="scroll-row -mx-4 px-4 sm:mx-0 sm:flex-wrap sm:px-0">
        <button
          type="button"
          className={`chip ${status === "needs_review" ? "chip-on" : ""}`}
          onClick={() => setParam("status", status === "needs_review" ? undefined : "needs_review")}
        >
          Needs review
        </button>
        <button
          type="button"
          className={`chip ${favorite ? "chip-on" : ""}`}
          onClick={() => setParam("favorite", favorite ? undefined : "1")}
        >
          Favourites
        </button>
        {collections.data
          ?.filter((c) => c.count > 0 || collection === c.id)
          .map((c) => (
            <button
              key={c.id}
              type="button"
              className={`chip ${collection === c.id ? "chip-on" : ""}`}
              onClick={() => setParam("collection", collection === c.id ? undefined : c.id)}
            >
              {c.name}
              <span className={collection === c.id ? "" : "text-faint"}>{c.count}</span>
            </button>
          ))}
        {tags.data
          ?.filter((t) => t.count > 0)
          .slice(0, 20)
          .map((t) => (
            <button
              key={t.id}
              type="button"
              className={`chip ${tag.includes(t.id) ? "chip-on" : ""}`}
              onClick={() => toggleParam("tag", t.id)}
            >
              {t.name}
            </button>
          ))}
      </div>

      {recipes.isLoading && <Spinner label="Loading your bank…" />}
      {recipes.isError && <ErrorBox error={recipes.error} onRetry={() => recipes.refetch()} />}

      {recipes.data && items.length === 0 && (
        <Empty
          title={debounced ? `Nothing matches “${debounced}”` : "Your bank is empty"}
          hint={
            debounced
              ? "Try fewer words, or a single ingredient."
              : "Share a link from Instagram, paste a recipe, or photograph a cookbook page."
          }
          action={
            <Link to="/add" className="btn btn-primary btn-sm mt-2">
              Add your first recipe
            </Link>
          }
        />
      )}

      {items.length > 0 &&
        (dense ? (
          <div className="card overflow-hidden">
            {items.map((recipe, index) => (
              <RecipeCard key={recipe.id} recipe={recipe} dense selected={index === cursor} />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {items.map((recipe, index) => (
              <RecipeCard key={recipe.id} recipe={recipe} selected={index === cursor} />
            ))}
          </div>
        ))}

      {recipes.data && recipes.data.total > items.length && (
        <p className="text-center text-xs text-faint">
          Showing {items.length} of {recipes.data.total}
        </p>
      )}
    </div>
  );
}
