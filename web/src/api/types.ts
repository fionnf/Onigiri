export type RecipeStatus = "draft" | "needs_review" | "ready";
export type SourceKind = "instagram" | "short_video" | "web" | "photo" | "video_file" | "text";
export type JobStatus =
  | "queued"
  | "fetching"
  | "transcribing"
  | "reading"
  | "extracting"
  | "done"
  | "needs_input"
  | "failed";
export type TagKind = "cuisine" | "course" | "diet" | "protein" | "time" | "technique" | "custom";

export interface Tag {
  id: string;
  name: string;
  kind: TagKind;
  auto?: boolean;
}

export interface TagWithCount extends Tag {
  count: number;
}

export interface Ingredient {
  id: string;
  order_idx: number;
  raw: string;
  quantity: number | null;
  quantity_max: number | null;
  unit: string | null;
  unit_class: string;
  item: string | null;
  preparation: string | null;
  optional: boolean;
  scalable: boolean;
  display: string;
}

export interface IngredientGroup {
  id: string;
  name: string | null;
  order_idx: number;
  ingredients: Ingredient[];
}

export interface Step {
  id: string;
  order_idx: number;
  text: string;
  timer_seconds: number[];
  section: string | null;
}

export interface CookLogEntry {
  id: string;
  cooked_at: string;
  rating: number | null;
  notes: string | null;
  servings_made: number | null;
}

export interface MediaItem {
  id: string;
  kind: string;
  content_type: string | null;
  width: number | null;
  height: number | null;
  duration_s: number | null;
  url: string | null;
}

export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
}

export interface Source {
  id: string;
  kind: SourceKind;
  url: string | null;
  title: string | null;
  author: string | null;
  caption: string | null;
  page_text: string | null;
  onscreen_text: string | null;
  photo_text: string | null;
  transcript_text: string | null;
  transcript_segments: TranscriptSegment[];
  language: string | null;
  fetched_at: string | null;
  media: MediaItem[];
}

export interface RecipeSummary {
  id: string;
  title: string;
  title_original: string | null;
  description: string | null;
  language: string | null;
  status: RecipeStatus;
  confidence: number | null;
  review_reason: string | null;
  total_min: number | null;
  servings: number | null;
  favorite: boolean;
  hero_url: string | null;
  tags: Tag[];
  source_kind: SourceKind | null;
  source_url: string | null;
  updated_at: string;
  created_at: string;
}

export interface Recipe extends RecipeSummary {
  servings_unit: string | null;
  prep_min: number | null;
  cook_min: number | null;
  equipment: string[];
  notes: string;
  profile_flags: string[];
  groups: IngredientGroup[];
  steps: Step[];
  cook_log: CookLogEntry[];
  source: Source | null;
}

export interface RecipeList {
  items: RecipeSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface StageEntry {
  stage: string;
  note: string;
  at: string;
}

export interface Job {
  id: string;
  status: JobStatus;
  input_url: string | null;
  recipe_id: string | null;
  source_id: string | null;
  stage_log: StageEntry[];
  needs_input_reason: string | null;
  error: string | null;
  usage: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ScaledIngredient {
  id: string;
  raw: string;
  item: string;
  preparation: string | null;
  optional: boolean;
  quantity: number | null;
  quantity_max: number | null;
  unit: string | null;
  display: string;
  converted: boolean;
  scaled: boolean;
}

export interface ScaledRecipe {
  servings: number | null;
  factor: number;
  unit_system: string;
  groups: { id: string; name: string | null; ingredients: ScaledIngredient[] }[];
}

export interface Profile {
  diet: string[];
  allergies: string[];
  dislikes: string[];
  likes: string[];
  pantry_staples: string[];
  unit_system: "metric" | "us";
  default_servings: number | null;
  notes: string;
  updated_at: string | null;
}

export interface Suggestion {
  id: string;
  text: string;
  field: string | null;
  value: string | null;
  evidence: Record<string, unknown>;
  status: string;
  created_at: string;
}

export interface Collection {
  id: string;
  name: string;
  order_idx: number;
  count: number;
}

export interface Stats {
  total: number;
  needs_review: number;
  ready: number;
  favorites: number;
  jobs_running: number;
  jobs_last_30_days: number;
  usage_last_30_days: {
    input_tokens: number;
    output_tokens: number;
    audio_seconds: number;
    calls: Record<string, number>;
  };
}

export interface Me {
  id: string;
  email: string;
}
