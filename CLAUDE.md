# watch-timing

An app for tracking a mechanical watch's accuracy over time. The user takes a photo of the watch dial. The backend reads the time shown on the dial using classical computer vision and compares it to the moment the photo was taken (the device clock for in-app captures, EXIF for photos picked from the library). Each photo becomes a measurement. A series of measurements gives the watch's rate (seconds gained or lost per day).

## Status

Milestone 1 (scaffolding + EXIF spike) is in place: `backend/watchtiming/exif.py` + `POST /api/probe`, and a spike page in the frontend. The CV pipeline, persistence and the real app UI don't exist yet; `watchtiming.debug` is planned for milestone 2. Update this file when the stack, commands or structure change.

**First task:** before building the CV pipeline, confirm that a photo taken through the PWA on a real iPhone and a real Android phone keeps `DateTimeOriginal`, `SubSecTimeOriginal` and `OffsetTimeOriginal`. Check this both when parsed in the browser and after upload. The design depends on it (see "Capture & timestamp"). **iPhone result:** `<input capture>` strips the timestamps; library picks keep them. Since in-app capture is required, the primary path is now a live in-app camera timestamped with the device clock (see "Capture & timestamp"). In-app camera timing verified on iPhone: constant ≈0.13 s lag, now corrected. Still to check: library byte match, installed PWA. Android: pending, no device available yet.

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
pnpm gen:api         # regenerate TS types from backend OpenAPI (backend must be running on :8000)
pnpm dlx shadcn@latest add <component>   # add a design-system component
```

To test on a phone: `pnpm dev` already serves HTTPS on the LAN (`@vitejs/plugin-basic-ssl`, `server.host: true`). Open the printed `Network:` URL and accept the self-signed certificate. Vite proxies `/api` to the backend on `localhost:8000`, so the phone only talks to one origin.

## Layout

```
backend/watchtiming/
  exif.py       # capture timestamp → UTC, with subseconds
  reference.py  # the reference time: EXIF or device clock + latency correction
  limits.py     # request body size limit (ASGI middleware)
  api.py        # FastAPI app
  dial.py       # (planned) dial ellipse detection + perspective rectification
  hands.py      # (planned) polar unwrap + per-angle hand profiles + peaks
  reading.py    # (planned) hand angles → h:m:s + confidence
  accuracy.py   # (planned) deviation, regression rate, sessions
  debug.py      # (planned) CLI that writes intermediate images
backend/tests/
  helpers.py    # shared test helpers (make_image, capture)
  synthetic/    # (planned) rendered dials with exact known times
  fixtures/     # (planned) real photos + known correct times
frontend/src/
  index.css            # Tailwind import + design tokens (the single source of truth)
  api/                 # generated schema.d.ts + typed fetch wrappers
  lib/                 # pure helpers (EXIF, clock offset, frame capture, formatting)
  components/ui/       # shadcn/ui components (generated, then owned by us)
  components/          # app components built from ui/
```

## UI & design system

shadcn/ui on Tailwind is the design system. Its components are copied into `components/ui/` and built on Radix (accessible), and its theming uses CSS-variable tokens.

- **Generated `ui/` code** may contain arbitrary values (`rounded-[min(…)]`, `bg-[color-mix(…)]`) and import `cn` from `"cn"` directly. Accept that there, but never copy those patterns into app components, which import `cn` from `@/lib/utils`.
- **Tokens only:** use semantic token classes (`bg-background`, `text-muted-foreground`, `border-border`, `bg-primary`, …). No raw palette classes (`bg-blue-500`), no arbitrary values (`p-[13px]`, `#hex`) and no inline styles. If a token is missing, add it to `index.css` (`:root`, `.dark` and `@theme inline`) instead of working around it.
- **Domain tokens:** `--fast` and `--slow` color the deviation and rate (positive = fast), so the meaning stays consistent across lists, badges and charts.
- **Use existing components first:** before writing a new component, check whether shadcn has it (`pnpm dlx shadcn@latest add …`). Customize `components/ui/` through tokens and `cva` variants. Don't fork the styles inside app components.
- **Icons:** `lucide-react` only. **Charts:** shadcn chart components (Recharts), using the same tokens.
- **Mobile first:** design for phone width first, with touch targets ≥ 44px and safe-area insets (`env(safe-area-inset-*)`) for the installed PWA. Use the light/dark theme via the `.dark` class, following the system setting.
- **Numbers:** show times, deviations and rates with `tabular-nums` and an explicit sign (`+3.2 s/d`).
- **Overlays:** the tap-12 and hand-correction overlays are SVGs drawn over the photo, using pointer events and token colors.

## Capture & timestamp

Two capture paths. Both go through `reference.reference_time()` (`backend/watchtiming/reference.py`), the single function for the reference time (a shutter-delay correction belongs there), and every measurement records its `reference_source` (`exif` or `device_clock`).

**1. In-app camera (primary).** Taking photos directly in the app is a hard UX requirement.
- Live viewfinder with `getUserMedia` (rear camera, ideally 4K). On tap, grab the frame to a canvas **inside `requestVideoFrameCallback`**, so the pixels and the timing metadata belong to the same frame. Timestamp = device clock for that frame (`captureTime`, else `presentationTime`, else the tap time). Convert the high-res timestamp with the current `Date.now()`/`performance.now()` pair, not `performance.timeOrigin`.
- The frame has no EXIF, so the timestamp is sent next to the image as `device_capture_time` (ISO, UTC). This is the only path where canvas encoding is allowed.
- Measure the device-vs-server clock offset (`GET /api/time`, shortest of several round trips) at capture and store it. EXIF is also just the phone's clock, so this path is no less trustworthy than EXIF.
- The upload sends `device_capture_time`, `frame_timing` (`capture_time`, `presentation_time` or `tap`) and a coarse `platform` (`ios`, `android` or `other`, detected on the client) **together**; any partial set is rejected. The latency correction is looked up per `(platform, frame_timing)` (`FRAME_LATENCY` in `reference.py`). Unmeasured combinations are not corrected and are flagged as uncalibrated (`latency_correction_ms: null`). Store the timing source and platform on the measurement.
- **Measured on iPhone, Firefox/WebKit (2026-10-14):** `(ios, capture_time)` lags the real exposure by a constant ≈0.132 s (±7 ms over 3 captures, measured by photographing the reference clock page `/#clock`). To calibrate another platform, compare the photo with **Server time at capture (raw)**, not the corrected time.

**2. Library pick (secondary).** Photos taken earlier with the Camera app.
- `<input type="file" accept="image/*">` **without `capture`**. Parse EXIF in the browser with `exifr` for immediate feedback **and** upload the original bytes unchanged (no canvas, resize or crop).
- The backend re-reads EXIF and treats it as authoritative: `DateTimeOriginal` + `SubSecTimeOriginal` + `OffsetTimeOriginal` → UTC. Never use file modified/created times.

**Rules for both:**
- **Never use `<input capture>`.** Verified on iPhone, Firefox/WebKit (2026-10-14): it strips every timestamp tag (only Orientation survives). Library picks keep them.
- If the image has an EXIF `DateTimeOriginal`, EXIF wins. A broken EXIF timestamp is rejected, never patched with the device time. No timestamp at all → reject with a clear message. Never fall back silently.
- Capture times from either source must be plausible: from 2020-01-01 up to 5 minutes ahead of server time (`EARLIEST_CAPTURE`, `MAX_CLOCK_AHEAD`). The lower bound is loose on purpose, for offline-queued uploads.
- Offline: queue captures in IndexedDB together with their timestamp (and clock offset, if one was measured) and upload when back online. Because the timestamp is recorded at capture, delayed processing stays correct.

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
- **Measurement**: dial reading (h:m:s), reference time (UTC), reference source (`exif` or `device_clock`), frame timing source and latency correction (device clock only), device-vs-server clock offset if measured, deviation, confidence, whether the user corrected it, status (`pending` until confident or confirmed, then `final`), the detected geometry (dial ellipse, pivot, hand angles, tap-12 point) and the image's SHA-256.
- **Images are not stored.** The backend processes an upload in memory and discards it once the reading is returned. The hand-correction overlay is drawn on the frontend's local copy using the stored geometry, and the correction is sent as angles or h:m:s. The frontend deletes its local copy from IndexedDB once the measurement is final. Only `final` measurements count toward the rate. Consequence: old measurements can't be re-read when the CV improves.
- **Deviation** = `dial_time - reference_time` in seconds. **Positive = fast.** Use this sign convention everywhere.
- **Rate** (s/d) = slope of a **linear regression** of deviation against reference time within a session. Do not take the difference between just two points. Measurements should be at least about 24h apart.
- **Mixed sources:** each reference source (`exif`, or `device_clock` per platform and frame timing) can have its own constant offset. Within one source that offset doesn't affect the rate, but mixing sources in a session puts a step in the deviations, and a plain regression turns that step into a rate error. Fit one slope with a separate intercept per source (or regress per source and warn), and unit-test the mixed case.

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
- **Release delay:** packages published in the last 3 days can't be installed (this protects against hijacked releases). Frontend: `minimumReleaseAge` in `pnpm-workspace.yaml`. Backend: `[tool.uv] exclude-newer = "3 days"` in `backend/pyproject.toml`. Don't lower or bypass either. If a resolve fails because a required version is too new, lower the version floor; don't override the window.
- **Lockfiles:** commit `pnpm-lock.yaml` and `uv.lock`. In CI, install with `pnpm install --frozen-lockfile` and `uv sync --locked`.
- **Version ranges:** pin exact versions for new dependencies (`pnpm add -E`). Check `pnpm audit` after dependency changes.
