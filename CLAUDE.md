# watch-timing

An app for tracking a mechanical watch's accuracy over time. The user takes a photo of the watch dial. The backend reads the time shown on the dial using classical computer vision and compares it to the photo's capture timestamp from EXIF. Each photo becomes a measurement. A series of measurements gives the watch's rate (seconds gained or lost per day).

## Status

New project with no code yet. The commands below are what we intend to use. Update this file when the stack, commands or structure change.

**First task:** before building the CV pipeline, confirm that a photo taken through the PWA on a real iPhone and a real Android phone keeps `DateTimeOriginal`, `SubSecTimeOriginal` and `OffsetTimeOriginal`. Check this both when parsed in the browser and after upload. The design depends on it (see "Capture & timestamp").

## Stack

- **Frontend** (`frontend/`): React + TypeScript PWA using Vite + `vite-plugin-pwa` (Workbox). Reads EXIF in the browser with `exifr`. Stores data offline in IndexedDB. Styling: Tailwind CSS v4 (`@tailwindcss/vite`) + shadcn/ui as the design system (see "UI & design system").
- **Backend** (`backend/`): Python 3.12+, FastAPI, OpenCV (`opencv-python-headless`), NumPy, Pillow + `pillow-heif`, SQLite. Managed with `uv`.
- **Package manager:** **pnpm only** (version pinned via `packageManager` in `package.json`). Never use `npm`/`npx`/`yarn`. Use `pnpm dlx` for one-off commands.
- **API contract:** FastAPI's OpenAPI schema is the source of truth. TS types are generated from it with `openapi-typescript`. Never hand-write API types in the frontend.

## Commands

```bash
# backend
cd backend && uv sync
uv run fastapi dev watchtiming/api.py
uv run pytest
uv run ruff check . && uv run ruff format .
uv run python -m watchtiming.debug <image>   # dumps intermediate CV images

# frontend
cd frontend && pnpm install
pnpm dev             # served over HTTPS; camera/PWA features need a secure context
pnpm build
pnpm test
pnpm lint
pnpm gen:api         # regenerate TS types from backend OpenAPI
pnpm dlx shadcn@latest add <component>   # add a design-system component
```

To test on a phone, the dev server must be reachable over HTTPS on the LAN (for example with `@vitejs/plugin-basic-ssl` + `--host`) or through a tunnel.

## Layout

```
backend/watchtiming/
  exif.py       # capture timestamp → UTC, with subseconds
  dial.py       # dial ellipse detection + perspective rectification
  hands.py      # polar unwrap + per-angle hand profiles + peaks
  reading.py    # hand angles → h:m:s + confidence
  accuracy.py   # deviation, regression rate, sessions
  api.py        # FastAPI app
  debug.py      # CLI that writes intermediate images
backend/tests/
  synthetic/    # rendered dials with exact known times
  fixtures/     # real photos + known correct times
frontend/src/
  index.css            # Tailwind import + design tokens (the single source of truth)
  components/ui/       # shadcn/ui components (generated, then owned by us)
  components/          # app components built from ui/
```

## UI & design system

shadcn/ui on Tailwind is the design system. Its components are copied into `components/ui/` and built on Radix (accessible), and its theming uses CSS-variable tokens.

- **Tokens only:** use semantic token classes (`bg-background`, `text-muted-foreground`, `border-border`, `bg-primary`, …). No raw palette classes (`bg-blue-500`), no arbitrary values (`p-[13px]`, `#hex`) and no inline styles. If a token is missing, add it to `index.css` (`:root`, `.dark` and `@theme inline`) instead of working around it.
- **Domain tokens:** `--fast` and `--slow` color the deviation and rate (positive = fast), so the meaning stays consistent across lists, badges and charts.
- **Use existing components first:** before writing a new component, check whether shadcn has it (`pnpm dlx shadcn@latest add …`). Customize `components/ui/` through tokens and `cva` variants. Don't fork the styles inside app components.
- **Icons:** `lucide-react` only. **Charts:** shadcn chart components (Recharts), using the same tokens.
- **Mobile first:** design for phone width first, with touch targets ≥ 44px and safe-area insets (`env(safe-area-inset-*)`) for the installed PWA. Use the light/dark theme via the `.dark` class, following the system setting.
- **Numbers:** show times, deviations and rates with `tabular-nums` and an explicit sign (`+3.2 s/d`).
- **Overlays:** the tap-12 and hand-correction overlays are SVGs drawn over the photo, using pointer events and token colors.

## Capture & timestamp

- Capture with `<input type="file" accept="image/*" capture="environment">`, which opens the native camera, so the photo has real EXIF. **Do not use `getUserMedia` + canvas for capture.** Canvas frames have no EXIF. This is the fallback only if the first task shows that EXIF doesn't survive (in that case, timestamp the frame with the device clock).
- Parse EXIF in the browser with `exifr` so the user gets immediate feedback, **and** upload the original file bytes unchanged. Never re-encode, resize or crop through a canvas before upload, because that strips metadata.
- The backend re-reads EXIF from the uploaded file and treats that as the authoritative value. Use `DateTimeOriginal` + `SubSecTimeOriginal` + `OffsetTimeOriginal` and store the result as UTC. Never use file modified/created times.
- Missing EXIF timestamp → reject with a clear message (screenshots, images from messaging apps, edited exports). Never fall back silently.
- Keep the source of the reference time behind one function so a correction for shutter delay can be added later.
- Offline: queue captured photos in IndexedDB and upload them when back online. The EXIF timestamp makes delayed processing correct.

## Dial-reading pipeline (backend, classical CV, no ML models)

1. Apply EXIF orientation, convert to grayscale and downscale to about 1000px on the long side.
2. Find the dial edge as an ellipse (`findContours` + `fitEllipse`; `HoughCircles` as a first attempt). Apply a perspective correction so the ellipse becomes a circle. This also reduces seconds-hand parallax.
3. **Orientation (v1):** after capture, the user taps the 12 o'clock marker on the photo, and the frontend sends that point with the upload. Automatic detection of 12 o'clock comes later.
4. Refine the pivot center (it can differ from the center of the dial edge) using where the hand lines intersect.
5. Unwrap the dial with `cv2.warpPolar`. For each radius, subtract that ring's median brightness and take the absolute value, so both dark and light hands show up. Leave out the outer ring where the hour markers sit.
6. Add up the result per angle over an inner, middle and outer band of radii and find the peaks. Hour hand: short and wide. Minute hand: long. Seconds hand: longest and thinnest, possibly with a counterweight tail pointing the opposite way (take the longer side).
7. Work out which peak is which hand by trying each assignment and minimizing the inconsistency between hands: `θ_hour ≈ (h + m/60)·30°`, and the minute hand should match the seconds. This also covers overlapping hands, which give fewer peaks.
8. Angles → time. Resolve AM/PM by choosing the reading closest to the reference time (wrap around at 12h).
9. Compute confidence from how sharp the peaks are and how consistent the hands are with each other. Below the threshold → the frontend shows the detected hands drawn over the photo and asks the user to confirm or correct.

Precision target: about ±0.2s for the hand reading and about ±0.5s for the whole measurement. If the seconds hand can't be read confidently, say so. Never guess the seconds.

## Domain model

- **Watch**: a user can track several watches.
- **Session**: a series of measurements since the watch was last set. Setting the watch starts a new session. Never compute a rate across sessions.
- **Measurement**: dial reading (h:m:s), reference time (UTC), deviation, confidence, whether the user corrected it, and a reference to the image.
- **Deviation** = `dial_time - reference_time` in seconds. **Positive = fast.** Use this sign convention everywhere.
- **Rate** (s/d) = slope of a **linear regression** of deviation against reference time within a session. Do not take the difference between just two points. Measurements should be at least about 24h apart.

## Testing

- **Synthetic dials:** CV logic is test-driven with dials drawn in OpenCV with hands at exact known angles, varied for rotation, tilt, noise, glare, dial and hand polarity, and overlapping hands.
- **Real photos:** the fixtures in `backend/tests/fixtures/` measure accuracy (report the error in seconds, not just pass/fail).
- **Rate math:** deviation and rate math have their own unit tests: 12h wrap-around, sign convention, sessions, regression.
- **Debugging CV:** when debugging CV, run `watchtiming.debug` and look at the intermediate images before changing any thresholds.

## Conventions

- Keep the CV pipeline as pure functions (`image → result`), with no I/O or framework code inside `dial/hands/reading`.
- Ask before adding new dependencies.
- Never commit secrets. `.env` is gitignored.

## Dependency security

- **Install scripts:** pnpm blocks dependency install scripts by default. Only packages listed in `onlyBuiltDependencies` in `pnpm-workspace.yaml` may run them (for example `esbuild`). Never add to that list or run `pnpm approve-builds` without asking.
- **Release delay:** `minimumReleaseAge` in `pnpm-workspace.yaml` stops packages published in the last few days from being installed (this protects against hijacked releases). Don't lower it or bypass it.
- **Lockfiles:** commit `pnpm-lock.yaml` and `uv.lock`. In CI, install with `pnpm install --frozen-lockfile` and `uv sync --locked`.
- **Version ranges:** pin exact versions for new dependencies (`pnpm add -E`). Check `pnpm audit` after dependency changes.
