# watch-timing

[![CI](https://github.com/maxrsg/watch-timing/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/maxrsg/watch-timing/actions/workflows/ci.yml)

Measures how many seconds a day a mechanical watch gains or loses, from photos of its dial, so you don't have to compare it to a reference clock by hand.

**Live:** https://watch-timing.fly.dev

## What it does

You photograph the watch in the app (or pick a photo from the library) and tap the 12 o'clock marker. The backend reads the time on the dial with classical computer vision and compares it to the moment the photo was taken (the device clock for in-app photos, EXIF for library photos). Each saved photo becomes a measurement for one of your watches. The Watches page shows the deviation over time and the rate in s/d. When the seconds can't be read reliably, the app says so and lets you drag the hands into place or type the time. It never guesses.

## Getting started

### Requirements

- **Node.js** 22+ and **pnpm** 11 (`corepack enable` picks up the version pinned in `package.json`)
- **uv** (`brew install uv`). It installs Python 3.12 for you.
- No external services or API keys.
- The camera needs HTTPS. The dev server provides it with a self-signed certificate.
- Optional: Docker (to check the production image) and `flyctl` (to deploy by hand).

### Installation

```bash
git clone https://github.com/maxrsg/watch-timing
cd watch-timing
pnpm install                 # frontend (pnpm workspace)
cd backend && uv sync        # backend
```

Use pnpm only, never npm or yarn. Dependency install scripts are blocked except for an allowlist, and packages published in the last 3 days can't be installed (both package managers).

### Configuration

Nothing needs to be configured, so there's no `.env` or `.env.example`. The backend reads these optional environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `WATCHTIMING_DB` | `backend/data/watchtiming.sqlite` | SQLite file for watches, sessions and measurements |
| `WATCHTIMING_DB_MAX_MB` | `500` | Above this size nothing new is stored (507) |
| `WATCHTIMING_STATIC_DIR` | unset | Folder with the built PWA to serve at `/` (set in the Docker image) |
| `WATCHTIMING_SAVE_UPLOADS` | unset | Dev only: keep each `/api/read` upload for debugging. Set it with `--save-uploads` |
| `WATCHTIMING_TRUST_FLY_IP` | unset | Use the `Fly-Client-IP` header for rate limits. Only behind Fly (set in the Docker image), since anyone can send that header |

### Running the project

You need two terminals.

```bash
# 1. Backend: FastAPI on http://localhost:8000
cd backend
uv run watchtiming-dev            # add --save-uploads to keep test photos for debugging
```

```bash
# 2. Frontend: Vite on https://localhost:5173
cd frontend
pnpm dev
```

Open **https://localhost:5173** and accept the certificate warning. The frontend forwards `/api` to the backend, so you only open the frontend.

#### On your phone

1. Connect the phone to the same Wi-Fi as your computer.
2. Open the `Network:` URL that `pnpm dev` prints (e.g. `https://192.168.x.x:5173`).
3. Accept the certificate warning.
4. Optional: install it as an app (iOS: Share → *Add to Home Screen*).

> **Note:** while `pnpm dev` runs, anyone on the same network can reach the backend through the dev server, and there's no login. Only run it on networks you trust.

#### Production image and deploy

```bash
docker build -t watchtiming .
docker run --rm -p 8080:8080 -v "$PWD/backend/data:/data" watchtiming   # http://localhost:8080
```

One Docker image builds the PWA and serves it next to `/api`. It runs on fly.io as a single machine that stops when idle, with SQLite on a volume. A push to `main` that passes CI deploys it (`flyctl deploy --remote-only --ha=false`). To deploy by hand: `fly deploy --ha=false` (always one machine, since SQLite lives on one volume).

### Develop

| Task | Backend (`backend/`) | Frontend (`frontend/`) |
|---|---|---|
| Tests | `uv run pytest` | `pnpm test` |
| Lint / format | `uv run ruff check . && uv run ruff format .` | `pnpm lint` |
| Build | — | `pnpm build` |

CI (`.github/workflows/ci.yml`) runs all of these on every pull request and push to `main`.

- **API types:** the backend's OpenAPI schema is the source of truth. With the backend running, `pnpm gen:api` (in `frontend/`) regenerates `src/api/schema.d.ts`. Don't hand-write API types.
- **UI components:** `pnpm dlx shadcn@latest add <component>` (in `frontend/`).
- **Debugging the CV** (in `backend/`):
  ```bash
  uv run python -m watchtiming.debug <image> --tap X,Y      # intermediate images in debug-out/<name>/
  uv run python -m tests.synthetic.render 10:08:37 --tilt 25 -o dial.png   # a synthetic dial
  uv run python -m tests.fixtures.add_local debug-out/uploads/<upload> 2:08:14.0 --name <name>
  ```
  The last one turns a saved upload into a local real-photo fixture (gitignored, the photos stay on your machine) for `tests/test_real_photos.py`.

## Architecture

The frontend is a React PWA. It handles the camera (a live viewfinder; the frame is grabbed with its device-clock timestamp, and the device-vs-server clock offset is measured via `/api/time`), the tap on 12 o'clock, the hand overlays and the watch pages. Everything else happens in the FastAPI backend. `reference.py` is the one place that decides the reference time (EXIF or device clock plus a per-platform latency correction). The dial-reading pipeline (`pipeline.read_dial`) is a chain of pure functions: find the dial and correct the perspective from the hour markers or rings, find the pivot and hand candidates from line segments, then work out which hand is which and turn the angles into h:m:s with a confidence. `accuracy.py` fits the rate, and `store.py` keeps watches, sessions and measurements in SQLite, keyed by an anonymous owner ID. Photos are processed in memory and never stored.

```
watch-timing/
├── backend/
│   ├── watchtiming/        # FastAPI app, reference time, CV pipeline, rate math, SQLite store
│   └── tests/              # pytest; synthetic/ renders dials with exact angles, fixtures/ real photos (local)
├── frontend/
│   └── src/
│       ├── api/            # generated OpenAPI types + typed fetch wrappers
│       ├── components/     # pages (Read dial, Watches) and ui/ (shadcn/ui)
│       └── lib/            # pure helpers: camera, clock offset, EXIF, crop, owner ID, rate notes
├── .github/workflows/      # CI and deploy
├── Dockerfile, fly.toml    # one image for PWA + API, deployed to fly.io
└── CLAUDE.md               # design decisions and conventions (the detailed spec)
```

## Tech stack

| Component | Choice | Reason |
|---|---|---|
| Frontend | React + TypeScript, Vite, `vite-plugin-pwa` | Camera access and an installable app from one web codebase, no app stores |
| UI | Tailwind CSS v4 + shadcn/ui, `lucide-react` | Accessible Radix components we own, themed through CSS-variable tokens |
| Charts | shadcn chart (Recharts) | Same tokens as the rest of the UI |
| EXIF in the browser | `exifr` | Instant feedback on a library photo's timestamp before upload |
| Backend | Python 3.12, FastAPI | Quick to build, validation built in, and its OpenAPI schema generates the frontend's types (`openapi-typescript`) |
| Dial reading | OpenCV + NumPy, classical CV (no ML) | Every step can be explained and debugged, and tested against synthetic dials with exactly known hand angles |
| Images | Pillow + `pillow-heif` | iPhones save HEIC; EXIF is read from the original bytes |
| Database | SQLite | No infrastructure; one machine is enough for a POC |
| Package managers | pnpm, uv | Committed lockfiles, blocked install scripts, a 3-day release delay against hijacked packages |
| Hosting | fly.io | HTTPS (needed for the camera), scales to zero, a volume for SQLite |
| CI/CD | GitHub Actions | Checks on every push, deploy from `main`; actions pinned to commit SHAs |

## Limitations

- **No login.** The browser makes up an anonymous owner ID and keeps it in localStorage. Anyone who has your "copy link to my watches" link can see and change your watches. Per-owner caps and per-IP rate limits keep abuse bounded, but this is a demo, not a secure service.
- **Seconds aren't always read.** Hours and minutes are usually read reliably, but on many real photos the seconds are withheld, for example when the hour markers aren't recognised or the seconds hand isn't found. The pipeline has only been tuned on a few dial designs, so other dials, hands and lighting may fail.
- **You have to tap 12 o'clock.** Automatic detection of the dial's orientation isn't built.
- **Camera timing is calibrated for iOS only.** The in-app camera's small, constant lag is corrected on iOS. Other platforms aren't calibrated yet, so their readings are flagged as uncalibrated.
- **No offline queue yet.** Saving a measurement needs a connection.
- **Photos aren't stored**, by design. Old measurements can't be re-read when the CV improves.
- **One machine, one SQLite file.** No redundancy, and the first request after the machine has stopped waits a few seconds for a cold start.
- **Taking photos through `<input capture>` strips the timestamps** on iPhone, so the app uses its own viewfinder instead. A photo with no usable timestamp is rejected rather than guessed.

## Built with

Claude Code (agent-driven development) as part of the course *Next-Generation Software Development with AI*. The design decisions and conventions the agent works from are in `CLAUDE.md`.
