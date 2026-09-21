export function minutes(total: number | null | undefined): string {
  if (!total) return "";
  if (total < 60) return `${total} min`;
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

export function clock(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

export function durationLabel(seconds: number): string {
  if (seconds % 3600 === 0) return `${seconds / 3600} h`;
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds}s`;
}

export function relativeDate(iso: string): string {
  const then = new Date(iso).getTime();
  const days = Math.floor((Date.now() - then) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  if (days < 365) return `${Math.floor(days / 30)} months ago`;
  return `${Math.floor(days / 365)} years ago`;
}

export function fullDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const SOURCE_LABELS: Record<string, string> = {
  instagram: "Instagram",
  short_video: "Video",
  web: "Web",
  photo: "Photo",
  video_file: "Video file",
  text: "Typed in",
};

export function sourceLabel(kind: string | null | undefined): string {
  return kind ? (SOURCE_LABELS[kind] ?? kind) : "";
}

const STAGE_LABELS: Record<string, string> = {
  queued: "Queued",
  fetching: "Fetching",
  transcribing: "Listening",
  reading: "Reading",
  extracting: "Writing it out",
  done: "Done",
  needs_input: "Needs you",
  failed: "Failed",
};

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage;
}

export function hostOf(url: string | null | undefined): string {
  if (!url) return "";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** 1.5 becomes one and a half, the way a recipe writes it. */
const FRACTIONS: [number, string][] = [
  [1 / 8, "⅛"],
  [1 / 4, "¼"],
  [1 / 3, "⅓"],
  [3 / 8, "⅜"],
  [1 / 2, "½"],
  [5 / 8, "⅝"],
  [2 / 3, "⅔"],
  [3 / 4, "¾"],
  [7 / 8, "⅞"],
];

export function prettyNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  if (Math.abs(value - Math.round(value)) < 1e-6) return String(Math.round(value));
  const whole = Math.floor(value);
  const rest = value - whole;
  for (const [amount, glyph] of FRACTIONS) {
    if (Math.abs(rest - amount) < 0.02) return whole ? `${whole}${glyph}` : glyph;
  }
  return value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}
