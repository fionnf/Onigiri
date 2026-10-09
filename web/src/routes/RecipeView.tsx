import { api } from "@/api/client";
import {
  IconAlert,
  IconClock,
  IconDownload,
  IconEdit,
  IconFlame,
  IconLink,
  IconRefresh,
  IconStar,
  IconTrash,
} from "@/components/Icons";
import { Confirm, ErrorBox, Spinner, Stars, StatusBadge } from "@/components/ui";
import { fullDate, hostOf, minutes, prettyNumber, sourceLabel } from "@/lib/format";
import { useLocal, useShortcuts } from "@/lib/hooks";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

type Panel = "recipe" | "source";

/** One serving up or down; below one serving, step in halves. */
function stepServings(current: number | null, direction: 1 | -1): number {
  const value = current ?? 1;
  const step = value + direction * 1 < 1 || value < 1 ? 0.5 : 1;
  return Math.max(0.5, Math.round((value + direction * step) * 2) / 2);
}

export function RecipeView() {
  const { recipeId } = useParams<{ recipeId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [panel, setPanel] = useState<Panel>("recipe");
  const [units, setUnits] = useLocal<"original" | "metric" | "us">("onigiri.units", "original");
  const [servings, setServings] = useState<number | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [logOpen, setLogOpen] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);

  const recipe = useQuery({
    queryKey: ["recipe", recipeId],
    queryFn: () => api.recipe(recipeId as string),
    enabled: Boolean(recipeId),
  });

  const target = servings ?? recipe.data?.servings ?? null;

  const scaled = useQuery({
    queryKey: ["scaled", recipeId, target, units],
    // Ask with no parameters unless something changed, so the request matches the
    // copy the background offline pass saved.
    queryFn: () =>
      api.scaled(
        recipeId as string,
        servings !== null && servings !== recipe.data?.servings ? servings : undefined,
        units === "original" ? undefined : units,
      ),
    enabled: Boolean(recipeId && recipe.data),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["recipe", recipeId] });
    queryClient.invalidateQueries({ queryKey: ["recipes"] });
    queryClient.invalidateQueries({ queryKey: ["stats"] });
  };

  const favourite = useMutation({
    mutationFn: (next: boolean) => api.updateRecipe(recipeId as string, { favorite: next }),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: () => api.deleteRecipe(recipeId as string),
    onSuccess: () => {
      invalidate();
      navigate("/");
    },
  });
  const reextract = useMutation({
    mutationFn: () => api.reextract(recipeId as string),
    onSuccess: invalidate,
  });
  const markReviewed = useMutation({
    mutationFn: () => api.updateRecipe(recipeId as string, { status: "ready" }),
    onSuccess: invalidate,
  });

  useShortcuts({
    e: () => navigate(`/r/${recipeId}/edit`),
    c: () => navigate(`/r/${recipeId}/cook`),
    s: () => setPanel(panel === "recipe" ? "source" : "recipe"),
  });

  if (recipe.isLoading) return <Spinner label="Opening…" />;
  if (recipe.isError) return <ErrorBox error={recipe.error} onRetry={() => recipe.refetch()} />;
  if (!recipe.data) return null;

  const r = recipe.data;
  const hasSource = Boolean(
    r.source &&
      (r.source.caption ||
        r.source.page_text ||
        r.source.transcript_text ||
        r.source.onscreen_text ||
        r.source.photo_text),
  );

  const toggleChecked = (id: string) => {
    const next = new Set(checked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChecked(next);
  };

  return (
    <div className="space-y-4">
      {/* Phone: photo across the top, title, then a row of three big buttons.
          Wider screens: small photo left, actions right. */}
      <div className="space-y-3 sm:flex sm:items-start sm:gap-3 sm:space-y-0">
        {r.hero_url && (
          <img
            src={r.hero_url}
            alt=""
            className="aspect-[16/10] w-full rounded-lg border border-line object-cover sm:aspect-square sm:h-24 sm:w-24"
          />
        )}
        <div className="min-w-0 flex-1 space-y-1">
          <h1 className="text-xl font-semibold leading-tight sm:text-lg">{r.title}</h1>
          {r.title_original && r.title_original !== r.title && (
            <p className="text-sm italic text-muted">{r.title_original}</p>
          )}
          {r.description && <p className="text-sm text-muted">{r.description}</p>}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-1 text-xs text-faint">
            {r.total_min && (
              <span className="inline-flex items-center gap-1">
                <IconClock className="h-3 w-3" />
                {minutes(r.total_min)}
              </span>
            )}
            {r.prep_min && <span>Prep {minutes(r.prep_min)}</span>}
            {r.cook_min && <span>Cook {minutes(r.cook_min)}</span>}
            {r.source?.url && (
              <a
                href={r.source.url}
                target="_blank"
                rel="noreferrer"
                className="link inline-flex items-center gap-1"
              >
                <IconLink className="h-3 w-3" />
                {hostOf(r.source.url)}
              </a>
            )}
            {!r.source?.url && r.source_kind && <span>{sourceLabel(r.source_kind)}</span>}
            <StatusBadge status={r.status} />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-2 no-print sm:flex sm:shrink-0 sm:gap-1.5">
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => favourite.mutate(!r.favorite)}
            aria-pressed={r.favorite}
          >
            <IconStar filled={r.favorite} className="h-3.5 w-3.5" />
            {r.favorite ? "Saved" : "Save"}
          </button>
          <Link to={`/r/${r.id}/cook`} className="btn btn-primary btn-sm">
            <IconFlame className="h-3.5 w-3.5" />
            Cook
          </Link>
          <Link to={`/r/${r.id}/edit`} className="btn btn-sm">
            <IconEdit className="h-3.5 w-3.5" />
            Edit
          </Link>
        </div>
      </div>

      {r.profile_flags.length > 0 && (
        <div className="card flex items-start gap-2 border-warn/40 px-3 py-2">
          <IconAlert className="mt-0.5 h-4 w-4 text-warn" />
          <ul className="flex-1 space-y-0.5 text-sm">
            {r.profile_flags.map((flag) => (
              <li key={flag}>{flag}</li>
            ))}
          </ul>
        </div>
      )}

      {r.status === "needs_review" && r.review_reason && (
        <div className="card space-y-2 border-warn/40 px-3 py-2">
          <div className="flex items-start gap-2">
            <IconAlert className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
            <div className="flex-1">
              <p className={`text-sm ${reviewOpen ? "" : "line-clamp-3"}`}>{r.review_reason}</p>
              {r.review_reason.length > 160 && (
                <button
                  type="button"
                  className="mt-1 text-xs text-faint underline"
                  onClick={() => setReviewOpen(!reviewOpen)}
                >
                  {reviewOpen ? "Show less" : "Show all"}
                </button>
              )}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:flex sm:justify-end">
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => markReviewed.mutate()}
              disabled={markReviewed.isPending}
            >
              Looks right
            </button>
            {r.source && (
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => reextract.mutate()}
                disabled={reextract.isPending}
              >
                <IconRefresh className="h-3.5 w-3.5" />
                {reextract.isPending ? "Re-reading…" : "Read it again"}
              </button>
            )}
          </div>
        </div>
      )}

      {r.status !== "needs_review" && r.review_reason && (
        <details className="text-sm text-muted">
          <summary className="cursor-pointer py-1 text-xs text-faint">
            What the source left out
          </summary>
          <p className="mt-1">{r.review_reason}</p>
        </details>
      )}

      {hasSource && (
        <div className="flex gap-1 border-b border-line no-print lg:hidden">
          {(["recipe", "source"] as Panel[]).map((value) => (
            <button
              key={value}
              type="button"
              className={`px-3 py-1.5 text-sm ${
                panel === value ? "border-b-2 border-ink text-ink" : "text-muted"
              }`}
              onClick={() => setPanel(value)}
            >
              {value === "recipe" ? "Recipe" : "What the source said"}
            </button>
          ))}
        </div>
      )}

      <div className={`grid gap-4 ${hasSource ? "lg:grid-cols-[1fr_20rem]" : ""}`}>
        <div className={`space-y-5 ${panel === "source" ? "hidden lg:block" : ""}`}>
          <section className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="label flex-1 basis-full sm:basis-auto">Ingredients</h2>
              <div className="flex w-full flex-wrap items-center gap-1.5 no-print sm:w-auto">
                <button
                  type="button"
                  className="btn btn-sm w-11"
                  aria-label="One serving fewer"
                  onClick={() => setServings(stepServings(target, -1))}
                  disabled={!r.servings || (target ?? 0) <= 0.5}
                >
                  −
                </button>
                <span className="min-w-24 text-center text-sm tabular-nums">
                  {prettyNumber(target)} {r.servings_unit ?? "servings"}
                </span>
                <button
                  type="button"
                  className="btn btn-sm w-11"
                  aria-label="One serving more"
                  onClick={() => setServings(stepServings(target, 1))}
                  disabled={!r.servings}
                >
                  +
                </button>
                {servings !== null && servings !== r.servings && (
                  <button type="button" className="btn btn-sm" onClick={() => setServings(null)}>
                    Reset
                  </button>
                )}
                <select
                  aria-label="Units"
                  className="field ml-auto w-auto py-1 text-xs"
                  value={units}
                  onChange={(event) => setUnits(event.target.value as "original" | "metric" | "us")}
                >
                  <option value="original">As written</option>
                  <option value="metric">Metric</option>
                  <option value="us">US cups</option>
                </select>
              </div>
            </div>

            {!r.servings && (
              <p className="text-xs text-faint">
                The source did not say how many this serves, so amounts cannot be scaled.
              </p>
            )}

            {scaled.data?.groups.map((group) => (
              <div key={group.id} className="space-y-1">
                {group.name && <h3 className="text-sm font-medium">{group.name}</h3>}
                <ul className="space-y-0.5">
                  {group.ingredients.map((ing) => (
                    <li key={ing.id}>
                      <button
                        type="button"
                        className={`flex w-full items-baseline gap-2 rounded px-1 py-2 text-left text-[15px] hover:bg-surface sm:py-0.5 sm:text-sm ${
                          checked.has(ing.id) ? "text-faint line-through" : ""
                        }`}
                        onClick={() => toggleChecked(ing.id)}
                      >
                        <span
                          className={`mt-1 h-3 w-3 shrink-0 rounded-sm border ${
                            checked.has(ing.id) ? "border-muted bg-muted" : "border-line"
                          }`}
                        />
                        <span className="flex-1">{ing.display}</span>
                        {ing.converted && (
                          <span className="shrink-0 text-[10px] text-faint" title={ing.raw}>
                            was {ing.raw}
                          </span>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </section>

          <section className="space-y-2">
            <h2 className="label">Method</h2>
            <ol className="space-y-2">
              {r.steps.map((step, index) => (
                <li key={step.id} className="flex gap-3 text-sm">
                  <span className="w-5 shrink-0 tabular-nums text-faint">{index + 1}</span>
                  <span className="flex-1">
                    {step.section && (
                      <span className="mb-0.5 block text-xs font-medium text-muted">
                        {step.section}
                      </span>
                    )}
                    {step.text}
                  </span>
                </li>
              ))}
            </ol>
            {r.steps.length === 0 && (
              <p className="text-sm text-muted">
                The source never gave a method. Add one by editing this recipe.
              </p>
            )}
          </section>

          {r.equipment.length > 0 && (
            <section className="space-y-1">
              <h2 className="label">Equipment</h2>
              <p className="text-sm text-muted">{r.equipment.join(", ")}</p>
            </section>
          )}

          {r.notes && (
            <section className="space-y-1">
              <h2 className="label">Notes</h2>
              <p className="whitespace-pre-wrap text-sm">{r.notes}</p>
            </section>
          )}

          <section className="space-y-2">
            <div className="flex items-center gap-2">
              <h2 className="label flex-1">Cook log</h2>
              <button
                type="button"
                className="btn btn-sm no-print"
                onClick={() => setLogOpen(!logOpen)}
              >
                I cooked this
              </button>
            </div>
            {logOpen && (
              <CookLogForm
                recipeId={r.id}
                defaultServings={target}
                onDone={() => {
                  setLogOpen(false);
                  invalidate();
                }}
              />
            )}
            {r.cook_log.length === 0 && !logOpen && (
              <p className="text-sm text-muted">Not cooked yet.</p>
            )}
            <ul className="space-y-1">
              {r.cook_log.map((entry) => (
                <li key={entry.id} className="flex items-baseline gap-2 text-sm">
                  <span className="w-28 shrink-0 text-xs text-faint">
                    {fullDate(entry.cooked_at)}
                  </span>
                  {entry.rating && <Stars value={entry.rating} size="h-3 w-3" />}
                  {entry.notes && <span className="flex-1 text-muted">{entry.notes}</span>}
                </li>
              ))}
            </ul>
          </section>

          <section className="flex flex-wrap items-center gap-1.5 no-print">
            {r.tags.map((tag) => (
              <Link key={tag.id} to={`/?tag=${tag.id}`} className="chip">
                {tag.name}
              </Link>
            ))}
            <span className="flex-1" />
            <a href={`/api/recipes/${r.id}/export.md`} className="btn btn-sm">
              <IconDownload className="h-3.5 w-3.5" />
              Markdown
            </a>
            <Confirm
              message={`Delete "${r.title}"? This cannot be undone.`}
              onConfirm={() => remove.mutate()}
            >
              <IconTrash className="h-3.5 w-3.5" />
              Delete
            </Confirm>
          </section>
        </div>

        {hasSource && r.source && (
          <aside
            className={`space-y-3 text-sm lg:sticky lg:top-16 lg:self-start ${
              panel === "recipe" ? "hidden lg:block" : ""
            }`}
          >
            <h2 className="label">What the source said</h2>
            <p className="text-xs text-faint">
              Kept exactly as captured, so you can check anything that looks off.
            </p>
            {r.source.author && <p className="text-xs text-muted">by {r.source.author}</p>}

            <SourceBlock title="Caption" body={r.source.caption} />
            <SourceBlock title="Page text" body={r.source.page_text} />
            <SourceBlock
              title="Spoken"
              body={r.source.transcript_text}
              hint="Automatic transcription; numbers can be misheard."
            />
            <SourceBlock
              title="On screen"
              body={r.source.onscreen_text}
              hint="Read off the video frames."
            />
            <SourceBlock title="From the photo" body={r.source.photo_text} />

            {r.source.media.filter((m) => m.kind === "image").length > 0 && (
              <div className="grid grid-cols-3 gap-1">
                {r.source.media
                  .filter((m) => m.kind === "image")
                  .slice(0, 6)
                  .map((m) => (
                    <a key={m.id} href={m.url ?? "#"} target="_blank" rel="noreferrer">
                      <img
                        src={m.url ?? ""}
                        alt=""
                        loading="lazy"
                        className="aspect-square w-full rounded border border-line object-cover"
                      />
                    </a>
                  ))}
              </div>
            )}

            {r.source.media
              .filter((m) => m.kind === "video")
              .map((m) => (
                <video
                  key={m.id}
                  src={m.url ?? ""}
                  controls
                  className="w-full rounded border border-line"
                >
                  <track kind="captions" />
                </video>
              ))}
          </aside>
        )}
      </div>
    </div>
  );
}

function SourceBlock({
  title,
  body,
  hint,
}: {
  title: string;
  body: string | null;
  hint?: string;
}) {
  const [open, setOpen] = useState(false);
  if (!body?.trim()) return null;
  const long = body.length > 320;
  return (
    <div className="card p-2">
      <p className="label mb-1">{title}</p>
      {hint && <p className="mb-1 text-[11px] text-faint">{hint}</p>}
      <p className="whitespace-pre-wrap text-xs leading-relaxed text-muted">
        {open || !long ? body : `${body.slice(0, 320)}…`}
      </p>
      {long && (
        <button
          type="button"
          className="mt-1 text-xs text-faint underline"
          onClick={() => setOpen(!open)}
        >
          {open ? "Show less" : "Show all"}
        </button>
      )}
    </div>
  );
}

function CookLogForm({
  recipeId,
  defaultServings,
  onDone,
}: {
  recipeId: string;
  defaultServings: number | null;
  onDone: () => void;
}) {
  const [rating, setRating] = useState<number | null>(null);
  const [notes, setNotes] = useState("");

  const save = useMutation({
    mutationFn: () =>
      api.addCookLog(recipeId, {
        rating: rating ?? undefined,
        notes: notes.trim() || undefined,
        servings_made: defaultServings ?? undefined,
      }),
    onSuccess: onDone,
  });

  return (
    <div className="card space-y-2 p-3">
      <div className="flex items-center gap-2">
        <span className="label">How was it</span>
        <Stars value={rating} onChange={setRating} />
      </div>
      <textarea
        className="field min-h-16 text-sm"
        placeholder="What you changed, what to do differently…"
        value={notes}
        onChange={(event) => setNotes(event.target.value)}
      />
      <div className="flex justify-end gap-2">
        <button type="button" className="btn btn-sm" onClick={onDone}>
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={() => save.mutate()}
          disabled={save.isPending}
        >
          Save
        </button>
      </div>
      {save.isError && <ErrorBox error={save.error} />}
    </div>
  );
}
