# Onigiri

A personal recipe bank. Share a link from Instagram, paste a web page, or photograph a
cookbook spread, and Onigiri turns it into a structured recipe you can search, scale and
cook from. It keeps the original caption, transcript or page text beside every recipe, so
you can always check what the source actually said.

Single owner, single account. Nothing is public.

---

## What it does

**Captures from wherever the recipe lives.**

| Source | How it is read |
|---|---|
| Instagram post or reel | Apify fetches the caption and media; the video is transcribed and its on-screen text is read |
| TikTok, YouTube, and other video pages | `yt-dlp` downloads it, then the same transcription and frame reading |
| Any web page | `recipe-scrapers` uses published structured data when a site has it, which costs nothing; otherwise the readable text goes to the model |
| Photos | Cookbook pages, magazine spreads, handwritten cards and screenshots, read by a vision model |
| Video files | Uploaded directly, then transcribed and read |
| Plain text | Pasted or typed |

**Never invents.** The extractor is told to leave a field empty rather than guess. Anything
the source did not state is listed on the recipe, and low-confidence captures land in a
**Needs review** inbox with the source shown side by side.

**Always recoverable.** When Instagram blocks a fetch or a page will not load, the capture
stops at `needs_input` and asks you to paste the caption or upload the video. It never
silently produces an empty recipe.

**Scales and converts properly.** Change the serving count and every measured amount
recalculates. Switch to metric and two cups of flour become 250 g, not 473 ml, because
bulk volumes cross to weight through a density table. Teaspoons stay teaspoons in both
systems. Seasoning "to taste" and garnishes are never multiplied.

**Remembers who it is cooking for.** A taste profile of allergies, diet, dislikes, likes
and pantry staples goes into every extraction prompt. Recipes get flagged when they touch
an allergy. The profile never changes a recipe: what the source said is kept as it was.
Onigiri also watches your edits and ratings and proposes profile changes, which you accept
or dismiss.

**Cooks.** A full-screen step view that keeps the screen awake, detects durations in the
step text and offers them as timers, and lets you tick ingredients off.

---

## Running it locally

You need Python 3.11+, Node 22, and Postgres 16 with the `vector` and `pg_trgm`
extensions. `ffmpeg` is needed for video; everything else works without it.

```bash
# 1. Database
createdb onigiri
psql onigiri -c 'create extension if not exists vector; create extension if not exists pg_trgm;'

# 2. Configuration
cp .env.example .env     # set OWNER_EMAIL, OWNER_PASSWORD, OPENAI_API_KEY, APIFY_TOKEN

# 3. Server
cd server
uv venv && uv pip install -e ".[dev]"
.venv/bin/alembic upgrade head
.venv/bin/uvicorn onigiri.main:app --reload

# 4. Web app, in another terminal
cd web
pnpm install
pnpm dev          # http://localhost:5173, proxying the API
```

For a production-shaped build, `pnpm build` in `web/` writes `web/dist`, which the API
serves at `/`. Then the whole app is on <http://localhost:8000>.

Everything at once, including Redis and MinIO:

```bash
docker compose -f infra/docker-compose.yml up --build
```

### Configuration

All settings come from the environment; `.env.example` lists every one. The ones that
matter:

| Variable | What it does |
|---|---|
| `OWNER_EMAIL`, `OWNER_PASSWORD` | The single account, created on first boot |
| `DATABASE_URL` | Postgres. A plain `postgres://` URL from a host is accepted |
| `OPENAI_API_KEY` | Extraction, vision, transcription and embeddings |
| `APIFY_TOKEN` | Instagram. Without it, Instagram captures ask you to paste instead |
| `JOB_BACKEND` | `inline` runs captures in the API process; `arq` uses Redis and the worker |
| `S3_*` | Object storage. Left blank, media goes to `MEDIA_DIR` on local disk |
| `MONTHLY_JOB_CAP` | Refuses new captures past this many in 30 days |

Without `OPENAI_API_KEY` the app still runs: web pages that publish structured recipe data
are captured for free, and everything else fails with a clear message rather than a
half-made recipe.

---

## How a capture works

```
detect what was shared
  ├─ instagram   → Apify: caption, images, video
  ├─ short video → yt-dlp: description, video
  ├─ web         → recipe-scrapers, else readable text
  ├─ photo       → vision model reads the page or card
  └─ text        → used as is
        │
        ├─ video present → ffmpeg → audio → transcript
        │                → ffmpeg → keyframes, deduplicated → on-screen text
        │
        └─ assemble every part, labelled, with the taste profile
              → one structured recipe, or an honest "needs review"
              → hero image, tags, search vector, embedding
```

Each stage writes a line to the job, so the capture screen shows what is happening and why
it stopped. Frames are deduplicated by perceptual hash before they reach the vision model,
because a talking-head reel is mostly the same frame and reading it sixty times is the
easiest way to waste money here.

---

## Layout

```
server/            FastAPI app, worker and pipeline
  onigiri/
    config.py        settings from the environment
    models.py        the whole data model
    units.py         unit table, ingredient parsing, conversion, timer detection
    recipe_schema.py the contract the model must return
    pipeline/        detect, fetch, media, vision, extract, run
    routers/         auth, ingest, recipes, library, profile, media
    services/        llm, search, scaling, storage, memory, jobs
  alembic/         migrations
  tests/           122 tests
web/               React PWA
  src/routes/        library, add, job, recipe, edit, cook, profile, settings
  src/sw.ts          service worker, including the share target
infra/             Dockerfile, compose, Fly configs
```

## Tests

```bash
cd server && .venv/bin/pytest          # 122 tests
cd web && pnpm test && pnpm build
```

The server tests run against a real Postgres and real `ffmpeg`, with only the model calls
stubbed. They cover unit conversion and ingredient parsing, the whole capture pipeline for
text, web, Instagram, video and photos, the rescue path when a fetch fails, search, tags,
collections, scaling, the cook log and export.

## Notes on cost and privacy

Captures are metered: every job records the tokens and audio seconds it used, and Settings
totals the last thirty days. For roughly forty captures a month the running cost is about
15 to 40 USD including hosting.

This is a personal tool for a single person. Recipes keep a link to their source and are
never published. Nothing is shared with anyone.
