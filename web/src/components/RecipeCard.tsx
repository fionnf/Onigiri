import type { RecipeSummary } from "@/api/types";
import { minutes, sourceLabel } from "@/lib/format";
import { Link } from "react-router-dom";
import { IconClock, IconStar } from "./Icons";
import { StatusBadge } from "./ui";

export function RecipeCard({
  recipe,
  dense,
  selected,
}: {
  recipe: RecipeSummary;
  dense?: boolean;
  selected?: boolean;
}) {
  const meta = [minutes(recipe.total_min), sourceLabel(recipe.source_kind)].filter(Boolean);

  if (dense) {
    return (
      <Link
        to={`/r/${recipe.id}`}
        data-recipe-row
        className={`flex items-center gap-3 border-b border-line px-3 py-2 transition hover:bg-surface ${
          selected ? "bg-surface" : ""
        }`}
      >
        {recipe.hero_url ? (
          <img
            src={recipe.hero_url}
            alt=""
            loading="lazy"
            className="h-9 w-9 rounded object-cover"
          />
        ) : (
          <span className="h-9 w-9 rounded bg-surface" />
        )}
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5">
            {recipe.favorite && <IconStar filled className="h-3 w-3 text-muted" />}
            <span className="truncate text-sm text-ink">{recipe.title}</span>
          </span>
          {recipe.tags.length > 0 && (
            <span className="truncate text-xs text-faint">
              {recipe.tags
                .slice(0, 4)
                .map((t) => t.name)
                .join(" · ")}
            </span>
          )}
        </span>
        {recipe.status === "needs_review" && <StatusBadge status={recipe.status} />}
        {recipe.total_min && (
          <span className="hidden shrink-0 text-xs text-faint sm:inline">
            {minutes(recipe.total_min)}
          </span>
        )}
      </Link>
    );
  }

  return (
    <Link
      to={`/r/${recipe.id}`}
      data-recipe-row
      className={`card group flex flex-col overflow-hidden transition hover:border-muted ${
        selected ? "border-muted" : ""
      }`}
    >
      <div className="aspect-[4/3] w-full overflow-hidden bg-surface">
        {recipe.hero_url ? (
          <img
            src={recipe.hero_url}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover transition group-hover:scale-[1.02]"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-xs text-faint">
            {sourceLabel(recipe.source_kind) || "No image"}
          </div>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-1.5 p-3">
        <div className="flex items-start gap-1.5">
          {recipe.favorite && <IconStar filled className="mt-1 h-3 w-3 text-muted" />}
          <h3 className="flex-1 text-sm font-medium leading-snug text-ink">{recipe.title}</h3>
        </div>
        {recipe.title_original && recipe.title_original !== recipe.title && (
          <p className="truncate text-xs italic text-faint">{recipe.title_original}</p>
        )}
        <div className="mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 pt-1 text-xs text-faint">
          {recipe.total_min && (
            <span className="inline-flex items-center gap-1">
              <IconClock className="h-3 w-3" />
              {minutes(recipe.total_min)}
            </span>
          )}
          {meta.length > 1 && <span>{sourceLabel(recipe.source_kind)}</span>}
          {recipe.status === "needs_review" && <StatusBadge status={recipe.status} />}
        </div>
      </div>
    </Link>
  );
}
