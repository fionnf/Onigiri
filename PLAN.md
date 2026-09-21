# Onigiri — Recipe Bank Plan

A personal, single-user web app that captures recipes from Instagram, websites, and photos into a searchable, well-structured recipe bank, and remembers your taste. Modelled on the Miso app, built to be fast and keyboard-friendly.

This document is the agreed plan from the planning session. Decisions in **Section 1** were confirmed by the owner; everything else follows from them.

---

## 1. Decisions (confirmed)

| Area | Decision |
|---|---|
| Users | Single owner account. No signup, no sharing in v1. |
| Stack | Python-first: FastAPI backend + worker, React frontend (TypeScript). |
| Database | Postgres (managed), `pgvector` + `pg_trgm` extensions. |
| Hosting | Fly.io (or Railway) for API + worker, managed Postgres, Cloudflare R2 for media. Frontend served as static files by the API or on Vercel. |
| Instagram capture | Paid scraping API (Apify). No self-scraping. |
| AI provider | OpenAI API: structured extraction (text + vision) and speech-to-text. |
| Memory | Persistent recipe bank **plus** a personal taste profile that informs extraction, tagging, and suggestions. No chat assistant in v1. |
| Phone capture | Installable PWA with Web Share Target (share a post, URL, or photo straight into the app). |
| v1 features | Cooking mode, scaling + unit conversion, search/tags/collections. Meal planning and grocery list are **out of scope** for v1. |
| Languages | Keep original text as-is; structured recipe is produced in English; original title/language kept visible; search covers both. |
| Photos | Cookbook/magazine pages, handwritten cards, screenshots. |
| Design | Minimal utility: monochrome, dense, fast, keyboard shortcuts, dark mode. |

---

## 2. Product scope

### 2.1 Capture ("Add")

One entry point, `Add`, that accepts any of:

| Input | How it arrives | Pipeline |
|---|---|---|
| Instagram post / reel URL | Share sheet, paste | Apify → caption + media → (video: transcript + on-screen text) → extract |
| TikTok / YouTube Shorts URL | Share sheet, paste | `yt-dlp` → caption + media → transcript + on-screen text → extract |
| Any web page URL | Share sheet, paste | `recipe-scrapers` (schema.org Recipe) → fallback readable text → extract |
| Photo(s) | Share sheet, file picker, camera | Vision model reads page/card/screenshot → extract |
| Video file | File picker | ffmpeg → transcript + keyframe OCR → extract |
| Plain text | Paste | extract |

Every capture becomes an **ingest job** with visible stages (fetching → transcribing → extracting → done/needs review) so the user always sees what is happening and can intervene (e.g. paste a caption when a fetch fails).

### 2.2 Recipe bank

- Structured recipe: title, description, servings, times, ingredient groups with parsed quantity/unit/item/note, ordered steps, equipment, tags, source link, hero image.
- Source panel: the original caption, transcript, page text, or photo, side by side with the extracted recipe, so hallucinations are easy to spot and fix.
- Every extraction carries a confidence flag; low-confidence recipes land in a **Needs review** inbox.
- Inline editing of every field, undoable.

### 2.3 Cooking mode

- Full-screen step view, one step at a time, large type.
- Screen Wake Lock so the phone stays on.
- Timers auto-detected from step text ("simmer 20 min") with a tap-to-start button; multiple concurrent timers.
- Ingredient checklist for the current step and the whole recipe.
- Works offline for already-opened recipes (service worker cache).

### 2.4 Scaling and units

- Change servings; all parsed quantities recalculate with sensible rounding and fraction display.
- Toggle metric ⇄ US customary, per ingredient class.
- Going metric, a bulk volume crosses to weight whenever the density table knows the
  ingredient: two cups of flour become 250 g, not 473 ml. Spoon measures stay spoon
  measures, because both systems use them. Counts never convert.
- Unparseable amounts ("a handful") are left untouched and shown as-is, and seasoning
  "to taste" or "for serving" is never multiplied.

### 2.5 Search, tags, collections

- Instant search across title, ingredients, steps, and original source text (both languages).
- Semantic search via embeddings ("something cozy with lentils").
- Auto-tags at extraction: cuisine, course, diet flags, main protein, total time bucket, technique. User can add/remove tags.
- Collections: manual lists ("Weeknight", "Bake for lab"). One recipe can be in many.
- Filters: tag, time, collection, source type, needs-review.

### 2.6 Memory (taste profile)

- A profile page with structured fields (diet, allergies, dislikes, likes, unit preference, default servings, pantry staples) and a free-text notes area.
- The profile is injected into the extraction prompt so that:
  - allergens and dislikes are flagged on new recipes,
  - substitution suggestions match your preferences,
  - auto-tags reflect your own categories.
- Ratings and edits feed back into the profile as suggestions ("You reduced sugar in 4 recipes — add 'prefers less sweet' to profile?").
- Cook log (date, rating, notes) per recipe. Simple in v1, extends later.

---

## 3. Architecture

```
┌────────────┐  share / paste  ┌──────────────┐   enqueue   ┌──────────────┐
│ React PWA  │ ──────────────▶ │  FastAPI API │ ──────────▶ │  Worker (arq)│
│ (Vite, TS) │ ◀────────────── │  (uvicorn)   │ ◀────────── │  Python      │
└────────────┘  JSON + SSE     └──────┬───────┘   status    └──────┬───────┘
                                      │                            │
                               ┌──────▼───────┐            ┌───────▼────────┐
                               │  Postgres    │            │ External APIs  │
                               │  pgvector    │            │ Apify, OpenAI, │
                               │  pg_trgm     │            │ yt-dlp, ffmpeg │
                               └──────────────┘            └───────┬────────┘
                                      ▲                            │
                               ┌──────┴───────┐                    │
                               │ Cloudflare R2│ ◀──────────────────┘
                               │ (media)      │
                               └──────────────┘
```

### 3.1 Backend

- **Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic.**
- **Worker:** `arq` on Redis (Fly Redis / Upstash). Long tasks (scrape, download, transcribe, extract) never run in a request.
- **Progress:** jobs publish stage updates; the API exposes them over Server-Sent Events so the UI shows live progress without polling.
- **Auth:** single owner. Password login (argon2) → httpOnly session cookie. Optional passkey (WebAuthn) in a later milestone. Rate limiting on login. Nothing else is reachable unauthenticated except the PWA manifest.
- **Storage:** R2 via S3 API. Originals (images, videos, audio) kept; derived assets (hero thumbnails, keyframes) generated by the worker.

### 3.2 Frontend

- **React 19, Vite, TypeScript, Tailwind, TanStack Query + Router, Zod.**
- **PWA:** `vite-plugin-pwa`, Web App Manifest with `share_target` (POST, multipart: `url`, `text`, `title`, `files`). Service worker handles the share POST, forwards to the API, and redirects to the new job page. Offline shell + cached recipe pages.
- **Keyboard:** `/` search, `n` add, `j`/`k` navigate, `e` edit, `c` cooking mode, `?` cheatsheet.
- **Design tokens:** monochrome grays, one accent for actions, Inter/system font, 4px grid, dark mode via `prefers-color-scheme` + manual toggle.

### 3.3 External services

| Service | Use | Notes |
|---|---|---|
| Apify (`instagram-scraper` actor) | Instagram post/reel metadata, caption, media URLs | Run per URL, sync mode, ~seconds. Result cached in `sources.raw_payload`. |
| `yt-dlp` | TikTok, YouTube Shorts, generic video pages | Also fallback for Instagram if Apify fails and the user opts in. |
| `ffmpeg` | Audio extraction, keyframe sampling | Installed in worker image. |
| OpenAI speech-to-text | Video audio → transcript with timestamps | Model via env var (`OPENAI_STT_MODEL`). Language auto-detect. |
| OpenAI text + vision (Responses API, structured outputs) | Caption/page/transcript/photo → Recipe JSON | Model via env var (`OPENAI_EXTRACT_MODEL`). JSON schema enforced. |
| OpenAI embeddings | Semantic search | `text-embedding-3-small`, 1536 dims, stored in `pgvector`. |
| `recipe-scrapers` | Structured recipes from ~500 known sites | Zero-cost path; LLM only fills gaps. |
| `trafilatura` | Readable text from arbitrary pages | Fallback when no schema.org data. |

---

## 4. Ingest pipeline (worker)

Each job runs through stages; every stage writes its output to the `sources` row so a failure can resume from the last good stage.

```
detect_kind(url | files | text)
  ├─ instagram  → apify_fetch → caption, media[] ─┐
  ├─ short_video→ ytdlp_fetch → caption, media[] ─┤
  ├─ web        → recipe_scrapers | trafilatura ──┤
  ├─ photo      → vision_read (per image) ────────┤
  ├─ video_file → (media[]) ──────────────────────┤
  └─ text       → (as-is) ────────────────────────┤
                                                  ▼
                      for each video: ffmpeg → audio → STT → transcript
                                      ffmpeg → keyframes (1 per 2s, dedup) → vision OCR → on-screen text
                                                  ▼
                      assemble context: caption + transcript + on-screen text + page text + photo text
                                                  ▼
                      extract (structured output, taste profile injected) → Recipe JSON + confidence + tags
                                                  ▼
                      parse ingredients (already structured by extractor; validate with unit table)
                      pick hero image (first image / best keyframe) → thumbnail → R2
                      embed (title + ingredients + tags) → pgvector
                      save recipe (status = draft | needs_review | ready)
```

**Design rules**

- The extractor is told what it does **not** know. If steps are only in the video and the transcript is empty, the recipe is marked `needs_review` with a reason, never invented.
- Carousel posts: all slides go through vision; slide text is concatenated in order.
- Long videos (>10 min) are transcribed in chunks; on-screen OCR is capped at 60 frames.
- Every external call is retried with backoff; Apify failures fall back to a UI prompt: "Paste the caption or upload the video".
- Original language is detected from the assembled context; the extractor outputs English fields plus `title_original` and `language`.

---

## 5. Data model

```sql
users            (id, email, password_hash, created_at)
profile          (user_id PK, diet[], allergies[], dislikes[], likes[], unit_system,
                  default_servings, pantry_staples[], notes text, updated_at)

sources          (id, user_id, kind ENUM(instagram, short_video, web, photo, video_file, text),
                  url, title, author, caption text, page_text text, transcript jsonb,
                  onscreen_text text, photo_text text, language,
                  raw_payload jsonb, fetched_at)
media            (id, source_id, kind ENUM(image, video, audio, keyframe, thumbnail),
                  r2_key, width, height, duration_s, order_idx)

ingest_jobs      (id, user_id, source_id, recipe_id, status ENUM(queued, fetching, transcribing,
                  reading, extracting, done, needs_input, failed),
                  stage_log jsonb, error text, created_at, updated_at)

recipes          (id, user_id, source_id, title, title_original, language, description,
                  servings int, servings_unit, prep_min, cook_min, total_min,
                  hero_media_id, status ENUM(draft, needs_review, ready),
                  confidence real, review_reason text, notes text,
                  search_tsv tsvector GENERATED, embedding vector(1536),
                  created_at, updated_at)
ingredient_groups(id, recipe_id, name, order_idx)
ingredients      (id, group_id, order_idx, raw text, quantity numeric, quantity_max numeric,
                  unit, item, preparation, optional bool, scalable bool,
                  unit_class ENUM(volume, weight, count, length, none))
steps            (id, recipe_id, order_idx, text, timer_seconds int[], ingredient_ids uuid[])
equipment        (recipe_id, name)

tags             (id, user_id, name, kind ENUM(cuisine, course, diet, protein, time, technique, custom))
recipe_tags      (recipe_id, tag_id, auto bool)
collections      (id, user_id, name, order_idx)
collection_items (collection_id, recipe_id, added_at)

cook_log         (id, recipe_id, cooked_at, rating smallint, notes, servings_made)
observations     (id, user_id, recipe_id, kind ENUM(edit, rating, note, cooked),
                  text, created_at)   -- what the suggester reasons from
profile_suggestions (id, user_id, text, evidence jsonb, status ENUM(open, accepted, dismissed))
```

Indexes: GIN on `search_tsv`, `pg_trgm` GIN on `recipes.title` and `ingredients.item`, HNSW on `embedding`, btree on `(user_id, status)`, `(user_id, updated_at desc)`.

---

## 6. API surface (v1)

```
POST   /auth/login                 POST /auth/logout
GET    /me/profile                 PUT  /me/profile
GET    /me/profile/suggestions     POST /me/profile/suggestions/{id}:accept|dismiss

POST   /ingest                     { url | text | files[] }  → job
POST   /share-target               multipart from PWA share sheet → job (redirect)
GET    /jobs/{id}                  GET /jobs/{id}/events (SSE)
POST   /jobs/{id}/input            { caption | files[] } when status = needs_input
POST   /jobs/{id}/retry

GET    /recipes?q=&tag=&collection=&status=&sort=   (hybrid FTS + trigram + vector)
POST   /recipes                    (manual create)
GET    /recipes/{id}               PATCH /recipes/{id}     DELETE /recipes/{id}
POST   /recipes/{id}/reextract     (re-run extraction with current source + profile)
GET    /recipes/{id}/scaled?servings=&units=
POST   /recipes/{id}/cooklog

GET/POST/PATCH/DELETE /tags        GET/POST/PATCH/DELETE /collections
POST   /collections/{id}/items     DELETE /collections/{id}/items/{recipeId}
GET    /media/{id}                 (signed R2 redirect)
```

---

## 7. Frontend screens

1. **Library** — dense list or grid toggle, search bar always focused via `/`, filter chips, `Needs review` badge count.
2. **Add** — single input; detects URL vs text vs files; drag-and-drop; camera on mobile. Shows the job timeline live.
3. **Job** — stage timeline; when `needs_input`, an inline form to paste caption or upload media.
4. **Recipe** — two-pane on desktop (recipe | source), tabs on mobile. Servings stepper and unit toggle in the header. Tags, collections, cook log, notes.
5. **Edit** — inline editing of every field, ingredient rows with parsed columns, step reorder by drag or `alt+↑/↓`.
6. **Cook** — full-screen step view, timers drawer, ingredient checklist, wake lock.
7. **Profile** — taste profile fields, notes, pending suggestions.
8. **Settings** — password, API usage counters, export (JSON + Markdown zip).

---

## 8. Repository layout

Built as two deployables from one image, rather than the four-package monorepo first
sketched. A single Python package keeps the pipeline, API and worker sharing one set of
models with no path dependencies to wire up.

```
server/
  pyproject.toml
  onigiri/
    config.py          settings from the environment
    db.py              async engine and session scope
    models.py          the whole data model
    units.py           unit table, ingredient parsing, conversion, timer detection
    recipe_schema.py   the contract the model must return
    schemas.py         HTTP request and response shapes
    serializers.py     ORM to DTO
    security.py        argon2 passwords, signed session cookie
    main.py            the app; worker.py  the arq entry point
    pipeline/          detect, fetch_web, fetch_instagram, fetch_video,
                       media, vision, prompts, extract, run
    routers/           auth, ingest, recipes, library, profile, media
    services/          llm, search, scaling, storage, memory, jobs
  alembic/             migrations
  tests/               122 tests, against real Postgres and real ffmpeg
web/
  src/api/             typed client and types
  src/lib/             hooks, formatters, share handoff
  src/components/      shell, recipe card, icons, shared UI
  src/routes/          library, add, job, recipe, edit, cook, profile, settings
  src/sw.ts            service worker, including the share target
infra/                 Dockerfile, docker-compose.yml, fly.api.toml, fly.worker.toml
.github/workflows/     lint, types, migrations, tests, container build
```

Tooling: `uv` and `ruff` for Python, `pytest` with a stubbed model client, `pnpm`,
`biome`, `vitest` and `tsc` for the web app.

## 9. Milestones

Each milestone ends with something you can use.

All eight are built.

| # | Milestone | Delivered |
|---|---|---|
| M0 | Scaffold | Package, Compose, Dockerfile, Fly configs, CI, argon2 login, session cookie, migration that applies from scratch. |
| M1 | Web + text capture | `recipe-scrapers` fast path that costs no model call, readable-text fallback, strict structured extraction, needs-review inbox. |
| M2 | Instagram + video | Apify client, `yt-dlp`, ffmpeg audio and keyframes with perceptual-hash dedup, transcription, on-screen text, `needs_input` rescue. |
| M3 | Photos | Vision reading for pages, handwritten cards and screenshots, with hard-to-read lines called out. |
| M4 | PWA + cooking | Installable app, service-worker share target, cooking mode with wake lock and timers, scaling and unit conversion. |
| M5 | Find things | Full text, trigram and vector retrieval fused by reciprocal rank, auto-tags with kinds, collections, filters, keyboard navigation. |
| M6 | Memory | Taste profile injected into every prompt, allergy flags, cook log, observations, suggestions to accept or dismiss. |
| M7 | Polish | Dark mode, Markdown and zip export, usage counters, error states, 122 server tests, browser-verified UI. |

Two choices changed during the build, both recorded above: the repository layout in
section 8, and the metric conversion rule in section 2.4, which now crosses bulk volumes
to weight because "235 ml of flour" is not what a metric cook wants.

---

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Apify actor breaks or Instagram changes | Actor pinned by version; `needs_input` fallback always available; optional `yt-dlp` fallback flag. |
| Extraction hallucinates steps or amounts | Source panel side by side; confidence flag; explicit "unknown" instruction in prompt; re-extract button. |
| Transcription misses quantities said quickly | Combine transcript with on-screen OCR; both are shown in the source panel. |
| Handwritten cards misread | Vision model returns per-line confidence; low-confidence lines highlighted for review. |
| Cost creep | Per-job token/second accounting stored on the job; usage counter in Settings; caps in config. |
| Copyright | Personal use only, single user, no public sharing, source attribution kept on every recipe. |
| Data loss | Managed Postgres daily backups + nightly JSON export to R2. |

---

## 11. Cost estimate (personal use, ~40 captures/month)

| Item | Approx. monthly |
|---|---|
| Fly.io API + worker (shared-cpu) + Redis | 5–10 USD |
| Managed Postgres (smallest tier) | 0–15 USD |
| Cloudflare R2 | < 1 USD |
| Apify (Instagram actor) | 5–10 USD at low volume |
| OpenAI extraction + vision + STT + embeddings | 2–6 USD |
| **Total** | **~15–40 USD** |

---

## 12. Open questions for implementation start

All three are now settings rather than open questions, so they can be changed without
touching code:

1. `APIFY_INSTAGRAM_ACTOR` defaults to `apify~instagram-scraper`. Point it at
   `apify~instagram-post-scraper` to trade breadth for a lower price per post.
2. `YTDLP_INSTAGRAM_FALLBACK` defaults to false. Turn it on to let the open downloader
   try when Apify fails, before the capture asks you to paste.
3. Suggestions are generated on demand from the Profile screen, never automatically, and
   need at least six observations before they will propose anything.
