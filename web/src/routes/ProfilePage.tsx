import { api } from "@/api/client";
import type { Profile } from "@/api/types";
import { IconCheck, IconSparkle, IconX } from "@/components/Icons";
import { ErrorBox, Field, Spinner } from "@/components/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

const LISTS: { key: keyof Profile; label: string; hint: string }[] = [
  {
    key: "allergies",
    label: "Allergies",
    hint: "Flagged on every recipe that contains them. Never ignored.",
  },
  { key: "diet", label: "Diet", hint: "Vegetarian, pescatarian, gluten-free…" },
  { key: "dislikes", label: "Dislikes", hint: "Things you would rather not cook with." },
  { key: "likes", label: "Likes", hint: "What you reach for. Used for tagging and suggestions." },
  { key: "pantry_staples", label: "Always in the pantry", hint: "Assumed to be on hand." },
];

export function ProfilePage() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState("");
  const [unitSystem, setUnitSystem] = useState<"metric" | "us">("metric");
  const [servings, setServings] = useState("");

  const profile = useQuery({ queryKey: ["profile"], queryFn: api.profile });
  const suggestions = useQuery({ queryKey: ["suggestions"], queryFn: api.suggestions });

  useEffect(() => {
    if (!profile.data) return;
    const next: Record<string, string> = {};
    for (const { key } of LISTS) {
      next[key as string] = ((profile.data[key] as string[]) ?? []).join(", ");
    }
    setForm(next);
    setNotes(profile.data.notes);
    setUnitSystem(profile.data.unit_system);
    setServings(profile.data.default_servings ? String(profile.data.default_servings) : "");
  }, [profile.data]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["profile"] });
    queryClient.invalidateQueries({ queryKey: ["suggestions"] });
  };

  const save = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = {
        notes,
        unit_system: unitSystem,
        default_servings: servings ? Number.parseInt(servings, 10) : null,
      };
      for (const { key } of LISTS) {
        payload[key as string] = (form[key as string] ?? "")
          .split(",")
          .map((part) => part.trim())
          .filter(Boolean);
      }
      return api.updateProfile(payload as Partial<Profile>);
    },
    onSuccess: invalidate,
  });

  const refresh = useMutation({ mutationFn: api.refreshSuggestions, onSuccess: invalidate });
  const accept = useMutation({ mutationFn: api.acceptSuggestion, onSuccess: invalidate });
  const dismiss = useMutation({ mutationFn: api.dismissSuggestion, onSuccess: invalidate });

  if (profile.isLoading) return <Spinner label="Loading your profile…" />;
  if (profile.isError) return <ErrorBox error={profile.error} />;

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div>
        <h1 className="text-base font-semibold">Your taste profile</h1>
        <p className="text-sm text-muted">
          This is what Onigiri remembers about you. It shapes how recipes are tagged and flagged. It
          never changes a recipe: what the source said is kept as it was.
        </p>
      </div>

      {suggestions.data && suggestions.data.length > 0 && (
        <section className="card space-y-2 p-3">
          <h2 className="label flex items-center gap-1">
            <IconSparkle className="h-3.5 w-3.5" />
            Noticed about you
          </h2>
          <ul className="space-y-2">
            {suggestions.data.map((s) => (
              <li key={s.id} className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <p className="text-sm">{s.text}</p>
                  {Array.isArray((s.evidence as { lines?: string[] })?.lines) && (
                    <ul className="mt-0.5 text-xs text-faint">
                      {((s.evidence as { lines: string[] }).lines ?? []).slice(0, 3).map((line) => (
                        <li key={line}>· {line}</li>
                      ))}
                    </ul>
                  )}
                </div>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => accept.mutate(s.id)}
                  aria-label="Add to profile"
                >
                  <IconCheck className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => dismiss.mutate(s.id)}
                  aria-label="Dismiss"
                >
                  <IconX className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <div className="card space-y-3 p-3">
          {LISTS.map(({ key, label, hint }) => (
            <Field key={key as string} label={label} hint={hint}>
              <input
                className="field"
                placeholder="Comma separated"
                value={form[key as string] ?? ""}
                onChange={(e) => setForm({ ...form, [key as string]: e.target.value })}
              />
            </Field>
          ))}
        </div>

        <div className="card grid gap-3 p-3 sm:grid-cols-2">
          <Field label="Preferred units">
            <select
              className="field"
              value={unitSystem}
              onChange={(e) => setUnitSystem(e.target.value as "metric" | "us")}
            >
              <option value="metric">Metric</option>
              <option value="us">US cups</option>
            </select>
          </Field>
          <Field label="Usually cooking for">
            <input
              className="field"
              inputMode="numeric"
              placeholder="2"
              value={servings}
              onChange={(e) => setServings(e.target.value)}
            />
          </Field>
        </div>

        <Field label="Anything else" hint="Free text. Goes into every extraction prompt.">
          <textarea
            className="field min-h-24"
            placeholder="Cooks on a gas hob. Prefers less sugar in bakes. No microwave."
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </Field>

        {save.isError && <ErrorBox error={save.error} />}

        <div className="flex items-center gap-2">
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
          >
            <IconSparkle className="h-3.5 w-3.5" />
            {refresh.isPending ? "Looking…" : "Look for new patterns"}
          </button>
          <span className="flex-1" />
          <button type="submit" className="btn btn-primary" disabled={save.isPending}>
            {save.isPending ? "Saving…" : save.isSuccess ? "Saved" : "Save"}
          </button>
        </div>
        {refresh.isSuccess && refresh.data?.length === 0 && (
          <p className="text-xs text-faint">
            Nothing new yet. Suggestions need a few cooked recipes or edits to go on.
          </p>
        )}
      </form>
    </div>
  );
}
