# watch-timing

Track a mechanical watch's accuracy from photos of its dial. The app reads the time on the dial with classical computer vision, compares it to the moment the photo was taken (device clock for in-app photos, EXIF for library photos), and works out how many seconds per day the watch gains or loses.

> **Status:** early. What exists today: the dial-reading pipeline and a **Read dial** page to try it. Take a photo in the app (or pick one), tap 12 o'clock, and see the reading, the detected hands drawn over the photo and the watch's deviation. Nothing is stored yet. Also: a capture timestamp check at `/#probe` and a reference clock at `/#clock`.

## Prerequisites

- **Node.js** 22+ and **pnpm** 11 (`corepack enable` picks up the pinned version)
- **uv** (`brew install uv`). It installs Python 3.12 for you.

## Run it

You need two terminals.

```bash
# 1. Backend: FastAPI on http://localhost:8000
cd backend
uv sync
uv run watchtiming-dev            # add --save-uploads to keep test photos for debugging
```

```bash
# 2. Frontend: Vite on https://localhost:5173
pnpm install
cd frontend
pnpm dev
```

Open **https://localhost:5173** and accept the self-signed certificate warning. The frontend forwards `/api` requests to the backend, so you only need to open the frontend.

### On your phone

Camera capture and PWA features need HTTPS, so the dev server already serves HTTPS on your local network.

1. Connect the phone to the same Wi-Fi as your computer.
2. Open the `Network:` URL that `pnpm dev` prints (e.g. `https://192.168.0.149:5173`).
3. Accept the certificate warning.
4. Optional: install it as an app (iOS: Share → *Add to Home Screen*).

> **Note:** while `pnpm dev` runs, anyone on the same network can reach the backend through the dev server, and there's no authentication yet. Only run it on networks you trust.

## Develop

| Task | Backend (`backend/`) | Frontend (`frontend/`) |
|---|---|---|
| Tests | `uv run pytest` | `pnpm test` |
| Lint / format | `uv run ruff check . && uv run ruff format .` | `pnpm lint` |
| Build | — | `pnpm build` |

- **API types:** the backend's OpenAPI schema is the source of truth. With the backend running, `pnpm gen:api` (in `frontend/`) regenerates `src/api/schema.d.ts`.
- **UI components:** `pnpm dlx shadcn@latest add <component>` (in `frontend/`).
- **Package manager:** use pnpm only, never npm or yarn. New dependencies are pinned to exact versions (`pnpm add -E`).

## Project layout

```
backend/    FastAPI + Python (EXIF, later the CV pipeline)
frontend/   React + TypeScript PWA (Vite, Tailwind, shadcn/ui)
CLAUDE.md   Design decisions and conventions
```
