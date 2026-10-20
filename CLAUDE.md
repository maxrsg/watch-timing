# watch-timing

An app for tracking a mechanical watch's accuracy over time. The user takes a photo of the watch dial. The backend reads the time shown on the dial using classical computer vision and compares it to the moment the photo was taken (the device clock for in-app captures, EXIF for photos picked from the library). Each photo becomes a measurement. A series of measurements gives the watch's rate (seconds gained or lost per day).

## Status

Milestone 1 (scaffolding + capture timestamp spike) is done: `exif.py` + `reference.py` + `POST /api/probe`, and a spike page in the frontend. Milestone 2 (synthetic dials + debug CLI) is done. Milestone 3 (the dial-reading pipeline, steps 1–9) is in place: `pipeline.read_dial(gray, tap)` reads every synthetic scenario within ±0.02 s or withholds the seconds and asks for confirmation. **Real photos (an Orient diver, 2026-10-18; 4 local fixtures):** dial detection and the marker-based perspective correction work (also when a hand covers the tapped 12). Hands are found as bars (step 5–6), so sword hands, lettering, the date window and a red seconds hand are handled on synthetic dials; on the real photos 2 of 4 read the right hour and minute, the other two are wrong but flagged, none is confidently wrong, and seconds are mostly withheld (the minute hand sits ~20 s off the seconds hand on this watch). Unconfirmed readings ask for confirmation, and the user can drag the hands into place on the photo (`/api/read` with `hour_*`/`minute_*`/`second_*` tips; the angles go through the same rectification). Even when no hands are found, the dial's geometry is returned so the hands can be placed. Try it with the app's "Read dial" page (`ReadTest.tsx` → `POST /api/read`, `uv run watchtiming-dev --save-uploads` keeps the photos for debugging); nothing is stored otherwise. Persistence, the measurement API and the real app UI don't exist yet. Update this file when the stack, commands or structure change.

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
uv run watchtiming-dev                  # dev server with auto-reload (= fastapi dev watchtiming/api.py)
uv run watchtiming-dev --save-uploads   # dev only: keep each /api/read upload + debug stages in debug-out/uploads/
uv run pytest
uv run ruff check . && uv run ruff format .
uv run python -m watchtiming.debug <image>   # dumps intermediate CV images to debug-out/<name>/
uv run python -m tests.synthetic.render 10:08:37 --tilt 25 -o dial.png   # render a synthetic dial
uv run python -m tests.fixtures.add_local debug-out/uploads/<upload> 2:08:14.0 --name <name>   # local real-photo fixture

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
  upload_log.py # dev only: saves /api/read uploads when WATCHTIMING_SAVE_UPLOADS is set
  devserver.py  # `watchtiming-dev` command: uvicorn with reload, --save-uploads sets that variable
  imaging.py    # decoding image bytes (HEIC opener, pixel limit), shared
  dial.py       # steps 1–2: preprocess, concentric rings, ring-based perspective rectification
  markers.py    # steps 2–3 preferred: perspective, center and 12 o'clock from the hour markers
  hands.py      # steps 3–6: 12 o'clock from markers, pivot, polar unwrap, hand candidates
  reading.py    # steps 7–9: hand assignment, angles → h:m:s, AM/PM, confidence
  pipeline.py   # read_dial(gray, tap): wires the steps, keeps intermediates for debug/overlays
  accuracy.py   # (planned) deviation, regression rate, sessions
  debug.py      # CLI that writes intermediate images (--tap X,Y for the full pipeline)
backend/tests/
  helpers.py    # shared test helpers (make_image, capture)
  synthetic/    # render.py: dials with exact known angles; scenarios.py: named variations;
                # gallery.py: renders all scenarios + a contact sheet to debug-out/synthetic/
  malformed/    # images with corrupt EXIF found by fuzzing (regression inputs)
  fixtures/     # add_local.py; local/ (gitignored): real photos + the time the hands show
  test_real_photos.py  # accuracy on the local real photos (skipped without them)
frontend/src/
  index.css            # Tailwind import + design tokens (the single source of truth)
  api/                 # generated schema.d.ts + typed fetch wrappers
  components/ReadTest.tsx      # main page for now: capture → tap 12 → reading + overlay
  components/PhotoOverlay.tsx  # photo + SVG layer in photo pixels (tap, dial, hands)
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
2. Find the dial and correct the perspective so it becomes a circle (this also reduces seconds-hand parallax).
   - **Rings, not contours:** on real dials no edge is a clean closed contour (ticks, rehaut and bezel touch it). A rough `HoughCircles` center, then RANSAC over the strongest edge radii per 5° sector gives one ring's shape, and the edge points' radii under that shape separate the concentric rings (dial edge, minute track, bezel, case), each fitted robustly (`dial_rings`). The scale comes from the tapped marker, not the ring (`MARKER_RADIUS`).
   - **Preferred: from the hour markers** (`markers.py`). Blobs of marker size, the RANSAC ellipse through the most of them (including the tapped one), numbered by angle from the tap, then a homography putting each at k·30° on a circle. This fixes perspective, center and 12 o'clock at once and is independent of the bezel and case, which sit *above* the dial and shift against it under an angle (parallax). Used directly when the markers' sideways error is ≤ 0.3°; otherwise compared with the ring-based reading by confidence (glare can bias marker centroids).
   - **Fallback: a ring plus the pivot.** The ellipse alone is not enough: an affine ellipse→circle correction leaves up to ~10° of angle error under strong tilt. The exact correction needs where the dial *center* appears: its polar line w.r.t. the ellipse is the image of the line at infinity. The pivot (step 4) is used as that center, clamped to the offset the ellipse's tilt allows (`plausible_center`), because a head-on dial with an off-center pivot looks the same as a tilted one.
3. **Orientation (v1):** after capture, the user taps the 12 o'clock marker on the photo, and the frontend sends that point with the upload. The tap only picks *which* marker is 12: the exact angle comes from the phase of the hour markers' 12-fold pattern (`refine_twelve`), so a tap 15 px off costs nothing. Without clear markers, the hands' consistency solves the remaining rotation, and the seconds are withheld. Automatic detection of 12 o'clock comes later.
4. Refine the pivot center (it can differ from the center of the dial edge) using where the hand lines intersect: trace each hand as a bar (step 5–6), fit its centerline, then a least-squares intersection weighted by each line's precision at the pivot (short hands extrapolate worse), dropping lines that miss the common point (outline edges, lettering). Traced loosely first, then tightly around the estimate. Hands along one line can't locate it (`well_determined = False`). Exclude the marker ring relative to the *dial* center, not the pivot estimate.
5. Unwrap the dial with `cv2.warpPolar` around the pivot, in brightness and color (Lab a, b: a red seconds hand on a black dial is faint in gray). **Bar evidence:** a hand is a straight bar on a ray through the pivot, so at each angle and radius look for both of its edges (a rising and a falling tangential gradient, either polarity, per channel) at a range of widths; keep the best. Contrast summed per angle can't tell hands from lettering or a date window; bar evidence along an unbroken run from the pivot can. Leave out the outer ring where the hour markers sit.
6. Seed directions from the evidence near the pivot and further out; trace each outward: the first run of some length (gaps where hands cross don't end it), starting near the pivot (or later only where another hand covers the ray), ending where a wide hand steadily gets wider well away from the pivot (it ran into the date window: `blocked`, its length is only a lower bound). Reject plain dial between two hands (it's a dark bar too) and traces as wide as the widest bar tried; merge the two facets of a faceted sword hand. Hour hand: shorter and not much thinner than the minute hand. Minute and seconds hands reach ≥ 0.6 R. Seconds hand: thinnest, possibly with a counterweight tail pointing the opposite way (a tail is short and never a hand).
7. Work out which candidate is which hand by trying each assignment and minimizing the inconsistency between hands: `θ_hour ≈ (h + m/60)·30°`, and the minute hand should match the seconds, within real watches' misalignment (a minute hand can sit ~20 s off the seconds hand). Leaving a candidate unexplained costs in proportion to its strength. This also covers overlapping hands, which give fewer candidates.
8. Angles → time. The seconds hand fixes the minute boundary and the minute hand the hour boundary (`angles_to_time`). Resolve AM/PM by choosing the reading closest to the reference time (wrap around at 12h); the reference must be in the watch's local time zone (`nearest_to_reference`).
9. Compute confidence from how consistent the hands are with each other, how far ahead the best assignment is of the best one giving a different time, and whether the pivot was well determined. Seconds get their own confidence; they're withheld (`seconds = None`) when the seconds hand overlaps another hand or 12 o'clock came only from the tap. Below the threshold → the frontend shows the detected hands drawn over the photo and asks the user to confirm or correct. Each lowered confidence comes with a reason for the user.

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
- **Real photos:** local fixtures in `backend/tests/fixtures/local/` (gitignored, photos stay on this machine; add with `tests.fixtures.add_local` from a `--save-uploads` folder, with the time the hands show read carefully off the photo, not the reference time). `test_real_photos.py` reports the error in seconds and angles per photo; its hard rule is that no reading is confidently wrong.
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
- **Version ranges:** frontend: pin exact versions for new dependencies (`pnpm add -E`). Backend: `>=` floors in `pyproject.toml` (what `uv add` writes); the exact versions come from the committed `uv.lock`, within the release delay. Check `pnpm audit` after frontend dependency changes.
