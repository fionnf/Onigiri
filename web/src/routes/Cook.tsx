import { api } from "@/api/client";
import {
  IconArrowLeft,
  IconArrowRight,
  IconClock,
  IconPause,
  IconPlay,
  IconX,
} from "@/components/Icons";
import { ErrorBox, Spinner } from "@/components/ui";
import { clock, durationLabel, prettyNumber } from "@/lib/format";
import { useLocal, useShortcuts, useTimers, useWakeLock } from "@/lib/hooks";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

export function Cook() {
  const { recipeId } = useParams<{ recipeId: string }>();
  const navigate = useNavigate();
  const [index, setIndex] = useState(0);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [units] = useLocal<"original" | "metric" | "us">("onigiri.units", "original");
  const { timers, start, stop, toggle } = useTimers();
  const awake = useWakeLock(true);

  const recipe = useQuery({
    queryKey: ["recipe", recipeId],
    queryFn: () => api.recipe(recipeId as string),
    enabled: Boolean(recipeId),
  });
  const scaled = useQuery({
    queryKey: ["scaled", recipeId, recipe.data?.servings ?? null, units],
    queryFn: () => api.scaled(recipeId as string, undefined, units),
    enabled: Boolean(recipeId && recipe.data),
  });

  const steps = useMemo(() => recipe.data?.steps ?? [], [recipe.data]);
  const last = steps.length - 1;

  useShortcuts({
    ArrowRight: () => setIndex((i) => Math.min(i + 1, last)),
    ArrowLeft: () => setIndex((i) => Math.max(i - 1, 0)),
    " ": () => setIndex((i) => Math.min(i + 1, last)),
    Escape: () => navigate(`/r/${recipeId}`),
  });

  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, []);

  if (recipe.isLoading) return <Spinner label="Getting ready…" />;
  if (recipe.isError) return <ErrorBox error={recipe.error} />;
  if (!recipe.data) return null;

  const step = steps[index];
  const allIngredients = scaled.data?.groups.flatMap((g) => g.ingredients) ?? [];

  const toggleChecked = (id: string) => {
    const next = new Set(checked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChecked(next);
  };

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-page">
      <header className="flex items-center gap-2 border-b border-line px-3 py-2">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => navigate(`/r/${recipeId}`)}
          aria-label="Leave cooking mode"
        >
          <IconX className="h-4 w-4" />
        </button>
        <h1 className="min-w-0 flex-1 truncate text-sm font-medium">{recipe.data.title}</h1>
        {awake && <span className="chip hidden sm:inline-flex">Screen stays on</span>}
        <span className="text-xs tabular-nums text-faint">
          {steps.length ? `${index + 1} / ${steps.length}` : "no steps"}
        </span>
      </header>

      {timers.length > 0 && (
        <div className="flex gap-2 overflow-x-auto border-b border-line px-3 py-2">
          {timers.map((timer) => (
            <div
              key={timer.id}
              className={`card flex shrink-0 items-center gap-2 px-2 py-1 ${
                timer.remaining === 0 ? "border-warn" : ""
              }`}
            >
              <span className="font-mono text-sm tabular-nums">{clock(timer.remaining)}</span>
              <span className="max-w-32 truncate text-xs text-faint">{timer.label}</span>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => toggle(timer.id)}
                aria-label={timer.running ? "Pause timer" : "Resume timer"}
              >
                {timer.running ? (
                  <IconPause className="h-3 w-3" />
                ) : (
                  <IconPlay className="h-3 w-3" />
                )}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => stop(timer.id)}
                aria-label="Dismiss timer"
              >
                <IconX className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="cook-scroll flex flex-1 flex-col overflow-y-auto px-4 py-6 sm:px-8">
        {steps.length === 0 ? (
          <p className="text-muted">This recipe has no method yet. Edit it to add the steps.</p>
        ) : (
          <div className="mx-auto w-full max-w-2xl flex-1">
            {step.section && <p className="mb-2 text-sm font-medium text-muted">{step.section}</p>}
            <p className="text-xl leading-relaxed sm:text-2xl">{step.text}</p>

            {step.timer_seconds.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-2">
                {step.timer_seconds.map((seconds) => (
                  <button
                    key={seconds}
                    type="button"
                    className="btn"
                    onClick={() => start(seconds, `Step ${index + 1}`)}
                  >
                    <IconClock className="h-3.5 w-3.5" />
                    Start {durationLabel(seconds)}
                  </button>
                ))}
              </div>
            )}

            <details className="mt-8" open>
              <summary className="label cursor-pointer">Ingredients</summary>
              <ul className="mt-2 space-y-0.5">
                {allIngredients.map((ing) => (
                  <li key={ing.id}>
                    <button
                      type="button"
                      className={`flex w-full items-baseline gap-2 rounded px-1 py-1 text-left hover:bg-surface ${
                        checked.has(ing.id) ? "text-faint line-through" : ""
                      }`}
                      onClick={() => toggleChecked(ing.id)}
                    >
                      <span
                        className={`mt-1.5 h-3 w-3 shrink-0 rounded-sm border ${
                          checked.has(ing.id) ? "border-muted bg-muted" : "border-line"
                        }`}
                      />
                      <span>{ing.display}</span>
                    </button>
                  </li>
                ))}
              </ul>
              {scaled.data?.servings && (
                <p className="mt-2 text-xs text-faint">
                  For {prettyNumber(scaled.data.servings)} {recipe.data.servings_unit ?? "servings"}
                  {scaled.data.unit_system !== "original" && `, ${scaled.data.unit_system}`}
                </p>
              )}
            </details>
          </div>
        )}
      </div>

      <footer className="flex items-center gap-2 border-t border-line px-3 py-3">
        <button
          type="button"
          className="btn flex-1"
          onClick={() => setIndex(Math.max(0, index - 1))}
          disabled={index === 0}
        >
          <IconArrowLeft className="h-4 w-4" />
          Back
        </button>
        {index === last ? (
          <button
            type="button"
            className="btn btn-primary flex-1"
            onClick={() => navigate(`/r/${recipeId}`)}
          >
            Done
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-primary flex-1"
            onClick={() => setIndex(Math.min(last, index + 1))}
          >
            Next
            <IconArrowRight className="h-4 w-4" />
          </button>
        )}
      </footer>
    </div>
  );
}
