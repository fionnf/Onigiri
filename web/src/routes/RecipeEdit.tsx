import { api } from "@/api/client";
import type { Recipe } from "@/api/types";
import { IconPlus, IconTrash } from "@/components/Icons";
import { ErrorBox, Field, Spinner } from "@/components/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

let rowCounter = 0;
const rowId = () => `row-${++rowCounter}`;

interface DraftIngredient {
  id: string;
  raw: string;
  optional: boolean;
}
interface DraftGroup {
  id: string;
  name: string;
  ingredients: DraftIngredient[];
}
interface DraftStep {
  id: string;
  text: string;
}
interface Draft {
  title: string;
  title_original: string;
  description: string;
  servings: string;
  servings_unit: string;
  prep_min: string;
  cook_min: string;
  total_min: string;
  equipment: string;
  notes: string;
  tags: string;
  groups: DraftGroup[];
  steps: DraftStep[];
}

function toDraft(r: Recipe): Draft {
  return {
    title: r.title,
    title_original: r.title_original ?? "",
    description: r.description ?? "",
    servings: r.servings != null ? String(r.servings) : "",
    servings_unit: r.servings_unit ?? "",
    prep_min: r.prep_min != null ? String(r.prep_min) : "",
    cook_min: r.cook_min != null ? String(r.cook_min) : "",
    total_min: r.total_min != null ? String(r.total_min) : "",
    equipment: r.equipment.join(", "),
    notes: r.notes,
    tags: r.tags.map((t) => t.name).join(", "),
    groups: r.groups.length
      ? r.groups.map((g) => ({
          id: rowId(),
          name: g.name ?? "",
          ingredients: [
            ...g.ingredients.map((i) => ({ id: rowId(), raw: i.raw, optional: i.optional })),
            { id: rowId(), raw: "", optional: false },
          ],
        }))
      : [{ id: rowId(), name: "", ingredients: [{ id: rowId(), raw: "", optional: false }] }],
    steps: [...r.steps.map((s) => ({ id: rowId(), text: s.text })), { id: rowId(), text: "" }],
  };
}

const num = (value: string): number | null => {
  const parsed = Number.parseFloat(value.replace(",", "."));
  return Number.isFinite(parsed) ? parsed : null;
};
const int = (value: string): number | null => {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : null;
};
const list = (value: string): string[] =>
  value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);

export function RecipeEdit() {
  const { recipeId } = useParams<{ recipeId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft | null>(null);

  const recipe = useQuery({
    queryKey: ["recipe", recipeId],
    queryFn: () => api.recipe(recipeId as string),
    enabled: Boolean(recipeId),
  });

  useEffect(() => {
    if (recipe.data && !draft) setDraft(toDraft(recipe.data));
  }, [recipe.data, draft]);

  const save = useMutation({
    mutationFn: () => {
      if (!draft) throw new Error("Nothing to save");
      return api.updateRecipe(recipeId as string, {
        title: draft.title.trim() || "Untitled recipe",
        title_original: draft.title_original.trim() || null,
        description: draft.description.trim() || null,
        servings: num(draft.servings),
        servings_unit: draft.servings_unit.trim() || null,
        prep_min: int(draft.prep_min),
        cook_min: int(draft.cook_min),
        total_min: int(draft.total_min),
        equipment: list(draft.equipment),
        notes: draft.notes,
        tags: list(draft.tags),
        groups: draft.groups
          .map((group) => ({
            name: group.name.trim() || null,
            ingredients: group.ingredients
              .filter((i) => i.raw.trim())
              .map((i) => ({ raw: i.raw.trim(), optional: i.optional })),
          }))
          .filter((group) => group.ingredients.length > 0),
        steps: draft.steps.filter((s) => s.text.trim()).map((s) => ({ text: s.text.trim() })),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["recipe", recipeId] });
      queryClient.invalidateQueries({ queryKey: ["recipes"] });
      queryClient.invalidateQueries({ queryKey: ["scaled", recipeId] });
      navigate(`/r/${recipeId}`);
    },
  });

  if (recipe.isLoading || !draft) return <Spinner label="Opening the editor…" />;
  if (recipe.isError) return <ErrorBox error={recipe.error} />;

  const update = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch });

  const updateGroup = (index: number, patch: Partial<DraftGroup>) => {
    const groups = [...draft.groups];
    groups[index] = { ...groups[index], ...patch };
    update({ groups });
  };

  const updateIngredient = (gi: number, ii: number, raw: string) => {
    const groups = [...draft.groups];
    const ingredients = [...groups[gi].ingredients];
    ingredients[ii] = { ...ingredients[ii], raw };
    if (ii === ingredients.length - 1 && raw.trim()) {
      ingredients.push({ id: rowId(), raw: "", optional: false });
    }
    groups[gi] = { ...groups[gi], ingredients };
    update({ groups });
  };

  const moveStep = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= draft.steps.length) return;
    const steps = [...draft.steps];
    [steps[index], steps[target]] = [steps[target], steps[index]];
    update({ steps });
  };

  return (
    <form
      className="mx-auto max-w-3xl space-y-5"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <div className="flex items-center gap-2">
        <h1 className="flex-1 text-base font-semibold">Edit</h1>
        <button type="button" className="btn btn-sm" onClick={() => navigate(`/r/${recipeId}`)}>
          Cancel
        </button>
        <button type="submit" className="btn btn-primary btn-sm" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </button>
      </div>

      {save.isError && <ErrorBox error={save.error} />}

      <div className="card space-y-3 p-3">
        <Field label="Title">
          <input
            className="field"
            value={draft.title}
            onChange={(e) => update({ title: e.target.value })}
          />
        </Field>
        <Field label="Title in the original language" hint="Leave blank if the source was English.">
          <input
            className="field"
            value={draft.title_original}
            onChange={(e) => update({ title_original: e.target.value })}
          />
        </Field>
        <Field label="Description">
          <textarea
            className="field min-h-16"
            value={draft.description}
            onChange={(e) => update({ description: e.target.value })}
          />
        </Field>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <Field label="Serves">
            <input
              className="field"
              inputMode="decimal"
              value={draft.servings}
              onChange={(e) => update({ servings: e.target.value })}
            />
          </Field>
          <Field label="Unit">
            <input
              className="field"
              placeholder="servings"
              value={draft.servings_unit}
              onChange={(e) => update({ servings_unit: e.target.value })}
            />
          </Field>
          <Field label="Prep min">
            <input
              className="field"
              inputMode="numeric"
              value={draft.prep_min}
              onChange={(e) => update({ prep_min: e.target.value })}
            />
          </Field>
          <Field label="Cook min">
            <input
              className="field"
              inputMode="numeric"
              value={draft.cook_min}
              onChange={(e) => update({ cook_min: e.target.value })}
            />
          </Field>
          <Field label="Total min">
            <input
              className="field"
              inputMode="numeric"
              value={draft.total_min}
              onChange={(e) => update({ total_min: e.target.value })}
            />
          </Field>
        </div>
      </div>

      <section className="space-y-2">
        <h2 className="label">Ingredients</h2>
        <p className="text-xs text-faint">
          One per line, as you would write them: “2 cloves garlic, finely chopped”. Amounts and
          units are parsed for scaling.
        </p>
        {draft.groups.map((group, gi) => (
          <div key={group.id} className="card space-y-2 p-3">
            <div className="flex items-center gap-2">
              <input
                className="field flex-1"
                placeholder="Group heading, e.g. For the sauce (optional)"
                value={group.name}
                onChange={(e) => updateGroup(gi, { name: e.target.value })}
              />
              {draft.groups.length > 1 && (
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => update({ groups: draft.groups.filter((_, i) => i !== gi) })}
                  aria-label="Remove group"
                >
                  <IconTrash className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            {group.ingredients.map((ing, ii) => (
              <div key={ing.id} className="flex items-center gap-2">
                <input
                  className="field flex-1 font-mono text-[13px]"
                  placeholder="250 g red lentils"
                  value={ing.raw}
                  onChange={(e) => updateIngredient(gi, ii, e.target.value)}
                />
                <button
                  type="button"
                  className="btn btn-ghost btn-sm text-faint"
                  onClick={() => {
                    const groups = [...draft.groups];
                    groups[gi] = {
                      ...group,
                      ingredients: group.ingredients.filter((_, i) => i !== ii),
                    };
                    update({ groups });
                  }}
                  aria-label="Remove ingredient"
                >
                  <IconTrash className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        ))}
        <button
          type="button"
          className="btn btn-sm"
          onClick={() =>
            update({
              groups: [
                ...draft.groups,
                {
                  id: rowId(),
                  name: "",
                  ingredients: [{ id: rowId(), raw: "", optional: false }],
                },
              ],
            })
          }
        >
          <IconPlus className="h-3.5 w-3.5" />
          Add a group
        </button>
      </section>

      <section className="space-y-2">
        <h2 className="label">Method</h2>
        {draft.steps.map((step, index) => (
          <div key={step.id} className="flex items-start gap-2">
            <span className="mt-2 w-5 shrink-0 text-right text-xs tabular-nums text-faint">
              {index + 1}
            </span>
            <textarea
              className="field min-h-16 flex-1"
              value={step.text}
              onChange={(e) => {
                const steps = [...draft.steps];
                steps[index] = { ...step, text: e.target.value };
                if (index === steps.length - 1 && e.target.value.trim()) {
                  steps.push({ id: rowId(), text: "" });
                }
                update({ steps });
              }}
            />
            <div className="flex flex-col gap-1">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => moveStep(index, -1)}
                aria-label="Move step up"
              >
                ↑
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => moveStep(index, 1)}
                aria-label="Move step down"
              >
                ↓
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm text-faint"
                onClick={() => update({ steps: draft.steps.filter((_, i) => i !== index) })}
                aria-label="Remove step"
              >
                <IconTrash className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        ))}
      </section>

      <div className="card space-y-3 p-3">
        <Field label="Tags" hint="Comma separated.">
          <input
            className="field"
            value={draft.tags}
            onChange={(e) => update({ tags: e.target.value })}
          />
        </Field>
        <Field label="Equipment" hint="Comma separated.">
          <input
            className="field"
            value={draft.equipment}
            onChange={(e) => update({ equipment: e.target.value })}
          />
        </Field>
        <Field label="Your notes">
          <textarea
            className="field min-h-20"
            value={draft.notes}
            onChange={(e) => update({ notes: e.target.value })}
          />
        </Field>
      </div>

      <div className="flex justify-end gap-2 pb-8">
        <button type="button" className="btn" onClick={() => navigate(`/r/${recipeId}`)}>
          Cancel
        </button>
        <button type="submit" className="btn btn-primary" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </button>
      </div>
    </form>
  );
}
