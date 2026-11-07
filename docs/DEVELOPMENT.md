# Development

## Requirements

- Windows 10/11 (macOS/Linux work for the engine and UI, but the shell targets Windows)
- Node.js 22.12+ and npm (Electron's install tooling needs it; CI uses Node 22)
- [uv](https://docs.astral.sh/uv/) 0.5+ (it provisions Python 3.12)
- ffmpeg and ffprobe on `PATH`
- Optional: NVIDIA GPU with a recent driver (CUDA 12 runtime libraries are installed as Python packages)

## Setup

```bash
npm install
cd engine && uv sync && cd ..
```

## Running

```bash
npm run dev
```

starts:

1. the Vite dev server for the UI on http://localhost:5173
2. esbuild in watch mode for the desktop shell
3. Electron, which launches the engine with `uv run python -m recpro.server`

Development data lives in `.devdata/` (git-ignored). Delete it to start fresh. Press **Ctrl+Shift+I** in the window for DevTools.

### UI in a browser (without Electron)

Useful for quick UI work. Start the engine on a fixed port with a known token, then the UI:

```bash
cd engine && RECPRO_TOKEN=devtoken uv run python -m recpro.server --data-dir ../.devdata --port 47321
```

```bash
npm run dev:ui
```

The UI falls back to `http://127.0.0.1:47321` with token `devtoken` when it isn't running inside the desktop app (`VITE_ENGINE_URL` and `VITE_ENGINE_TOKEN` override this). Folder picking then uses the built-in folder browser.

### Keeping the bin out of drive roots

In normal use, removed originals go to `<drive>\.RecPro-Bin`. When you experiment with the sample library, set `RECPRO_BIN_ROOT` to a folder on the same drive so the bin stays inside the repository:

```bash
cd engine && RECPRO_TOKEN=devtoken RECPRO_BIN_ROOT='D:\path\to\RecPro\.testdata' uv run python -m recpro.server --data-dir ../.devdata --port 47321
```

Tests do the same automatically with a temporary folder.

### Sample library

`scripts/make_samples.py` creates a synthetic library (dated JPEGs, rotated images, a screenshot, a WhatsApp-style file, a duplicate, two short videos) with no personal data:

```bash
engine/.venv/Scripts/python scripts/make_samples.py .testdata/samples
```

### Text samples

`scripts/make_text_samples.py` draws synthetic images for the text pass: SPECIMEN Aadhaar- and PAN-style cards with random checksum-valid numbers, a WhatsApp-style chat, a UPI payment screen, an invoice and a Hindi line. `truth.txt` records the numbers it drew. Add the folder to the library to see ID documents, screenshot apps and text search.

```bash
engine/.venv/Scripts/python -I scripts/make_text_samples.py .testdata/text-samples
```

### Video samples

`scripts/make_video_samples.py` makes an 18 s slideshow from LFW photos (Colin Powell, George W Bush, Powell again), in H.264 and HEVC, with a sentence spoken by Windows text-to-speech from about 1 s. `truth.json` records who is on screen when and what is said. Add the folder to see video people lanes, moments in search and speech search:

```bash
engine/.venv/Scripts/python -I scripts/make_video_samples.py .testdata/lfw/lfw.tgz .testdata/video-samples
```

The video and speech tests make their own small videos with ffmpeg (CI installs it). Speech needs the speech model (Settings → AI models, 1.6 GB from Hugging Face into the data folder).

### Cleanup samples

`scripts/make_cleanup_samples.py` makes, from LFW photos, a camera burst (one shot shaken), exact copies in `Backup/`, a smaller WhatsApp copy and a forward, and very dark and very blurred photos, with `truth.json` saying what each group should be:

```bash
engine/.venv/Scripts/python -I scripts/make_cleanup_samples.py .testdata/lfw/lfw.tgz .testdata/cleanup-samples
```

### Places samples

`scripts/make_places_samples.py` writes LFW photos with camera EXIF, capture times and GPS positions into one `Camera/` folder, the way a phone keeps them: home in Pune over 18 months, trips to Goa, Jaipur, Paris and Lonavala, two photos on today's date one and three years back (for On this day), and in `Odd/` a 0,0 position and one at sea. LFW photos already in the third folder are skipped so nothing shows up as a duplicate. `truth.json` has each photo's town and the trips:

```bash
engine/.venv/Scripts/python -I scripts/make_places_samples.py .testdata/lfw/lfw.tgz .testdata/places-samples .testdata/lfw-lib
```

### Place table

`engine/recpro/data/places.npz` is built from three GeoNames files (CC BY 4.0). To rebuild it, download them into `.cache/geonames`, then:

```bash
for f in cities1000.zip admin1CodesASCII.txt countryInfo.txt; do curl -sSfL -o ".cache/geonames/$f" "https://download.geonames.org/export/dump/$f"; done
```

```bash
engine/.venv/Scripts/python -I scripts/build_places.py .cache/geonames engine/recpro/data/places.npz
```

The map's country outlines come from the `world-atlas` npm package (Natural Earth). The d3 packages are pinned to their 2021-2024 releases in the root `package.json` (`overrides`): new versions of all of them appeared together in November 2026, and nothing here needs them.

### Keep downloads and caches on D:

This project keeps every download off C:. Before installing Python packages, point uv's cache, its own Python installs and the temp folders into the repository (npm already uses `.cache/npm` through the project `.npmrc`):

```bash
export UV_CACHE_DIR='D:\Claude\github\RecPro\.cache\uv' UV_PYTHON_INSTALL_DIR='D:\Claude\github\RecPro\.cache\uv-python' UV_PYTHON_INSTALL_BIN=0 TEMP='D:\Claude\github\RecPro\.cache\tmp' TMP='D:\Claude\github\RecPro\.cache\tmp'
```

`UV_PYTHON_INSTALL_DIR` puts the Python that uv downloads (3.12) on D: too, and `UV_PYTHON_INSTALL_BIN=0` stops it adding `python3.12.exe` to `%USERPROFILE%\.local\bin`. An `engine/.venv` made before should be made again so it uses that Python: delete it, then `uv sync`.

Electron fetches its own program (about 150 MB, checked against the checksums in the `electron` package) the first time something starts it, such as `npm run dev` (Electron 42 no longer does it during `npm install`). Keep it in the repository's cache too:

```bash
export electron_config_cache='D:\Claude\github\RecPro\.cache\electron'
```

If that download fails on a slow connection, fetch the zip with curl into the folder it looks in (`<cache>\<sha256 of the release URL's folder>\electron-vX.Y.Z-win32-x64.zip`, for example `https://github.com/electron/electron/releases/download/v42.11.18`), check its SHA-256 against `node_modules/electron/checksums.json`, then start it again: it unpacks the cached file.

AI models download into the engine's data folder (`.devdata\models` in development), never to a user cache.

### AI models

Open Settings → AI models and choose Download, or call the API:

```bash
curl -s -H "X-RecPro-Token: devtoken" -H "Content-Type: application/json" -X POST http://127.0.0.1:47321/api/models/download -d '{"profile":"best"}'
```

### Accuracy check (LFW)

`scripts/lfw_subset.py` builds a two-folder library from the public LFW archive (10 people × 40 photos plus 300 strangers) and `scripts/eval_lfw.py` measures grouping completeness/purity and Find recall/precision before and after answering the Review questions with the ground truth:

```bash
engine/.venv/Scripts/python -I scripts/lfw_subset.py .testdata/lfw/lfw.tgz .testdata/lfw-lib
```

Add `.testdata/lfw-lib/FolderA` and `FolderB` as library folders, then:

```bash
engine/.venv/Scripts/python -I scripts/eval_lfw.py http://127.0.0.1:47321 devtoken .testdata/lfw-lib .devdata/recpro.db
```

LFW labels only the centered face, so a match on a person standing in the background of someone else's photo counts as a "mistake" in the raw numbers even when it's right.

## Tests

```bash
npm run test:engine        # pytest: file-operation guarantees, offline, places, trips and more
npm run typecheck          # UI and desktop TypeScript
npm run test:ui            # vitest: error screens
```

### Accessibility check

axe-core runs in the page, from a copy outside the project (the app doesn't depend on it). With the engine and `npm run dev:ui` running:

```bash
mkdir -p .cache/tmp/axe && cd .cache/tmp/axe && npm pack axe-core@4.13.0 && tar -xzf axe-core-4.13.0.tgz
```

Then, in the browser's console on a screen of the app:

```js
eval(await (await fetch('/@fs/D:/Claude/github/RecPro/.cache/tmp/axe/package/axe.min.js')).text());
(await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'] } })).violations;
```

Every screen should return an empty list, in the light and the dark theme.

## Building the installer

CI builds it on every release (see [Releasing](#releasing)). To build it on this PC, keep electron-builder's downloads on D: and freeze the engine in its own environment (without the CUDA libraries, exactly like CI):

```bash
export ELECTRON_CACHE='D:\Claude\github\RecPro\.cache\electron' ELECTRON_BUILDER_CACHE='D:\Claude\github\RecPro\.cache\electron-builder'
cd engine
UV_PROJECT_ENVIRONMENT='D:\Claude\github\RecPro\.cache\buildenv' uv sync --frozen --no-default-groups --group build
UV_PROJECT_ENVIRONMENT='D:\Claude\github\RecPro\.cache\buildenv' uv run --no-sync python ../scripts/build_engine.py
cd ..
mkdir -p dist/recpro-engine/bin   # put ffmpeg.exe and ffprobe.exe from a full build here (CI bundles gyan.dev's essentials build)
engine/.venv/Scripts/python -I scripts/smoke_engine.py dist/recpro-engine/recpro-engine.exe .cache/tmp/smoke-data --expect-ffmpeg
npm run build
cd desktop && npx electron-builder --win nsis --publish never   # or --win dir for an unpacked app
```

- Copy the real `ffmpeg.exe` and `ffprobe.exe`, not a package manager's small launcher (a few hundred KB) that only works on this PC.
- `dist/recpro-engine/` is the frozen engine (PyInstaller, one folder, about 540 MB). `scripts/smoke_engine.py` starts it the way the app does (piped output in the system code page) and checks the ready line, `/api/health`, `/api/models`, the bundled ffmpeg and that it exits when stdin closes.
- The installer is `desktop/release/RecPro-X.Y.Z-win-x64.exe`, with `latest.yml` and a blockmap for the updater.
- A frozen engine that seems stuck can print every thread's stack: set `RECPRO_DUMP_STACKS=30` before starting it.
- The CUDA libraries live in the `cuda` dependency group (installed by default for development). The installed app downloads the same wheels from PyPI as its **GPU pack** (`ml/models.py`, `GPU_WHEELS`); a test fails when they drift from `uv.lock`.

## Releasing

Versions follow `X.Y.Z`. Day-to-day work is on `dev`; a release is `dev` pushed to `main`.

1. `node scripts/release.mjs set X.Y.Z`: writes the version into `engine/pyproject.toml`, `engine/recpro/__init__.py`, `engine/uv.lock`, the three `package.json` files and `package-lock.json`; turns the changelog's *Unreleased* into `## [X.Y.Z] — <date>`; drafts `docs/releases/vX.Y.Z.md`.
2. Write the release notes in `docs/releases/vX.Y.Z.md` for people using RecPro (remove the draft line), then `node scripts/release.mjs check X.Y.Z`.
3. Commit and push `dev`; wait for **ci** (engine tests on Windows, UI and shell build) to be green.
4. `git push origin dev:main`. The **release** workflow checks the versions and notes, creates the tag and the GitHub release, and the **desktop** workflow builds the installer and attaches it with `latest.yml`. Check that both runs succeeded and that the release has the `.exe`.

Run status is public: `https://api.github.com/repos/buildcool/RecPro/actions/runs`.

## Conventions

- **Engine:** Python 3.12, type hints, no global state beyond the `Context`. Long work runs in services/threads; API handlers stay quick. Anything that touches user files goes through `ops/` and keeps its guarantees tested.
- **UI:** function components, TanStack Query for server state, Zustand for UI state, Tailwind tokens from `styles.css` (never raw colors). Copy is sentence case, verb-first buttons, no "please".
- **Privacy:** no network calls from the engine except the model downloader (and the GPU pack from PyPI); the desktop shell's update check is the only other one, and it obeys *Strict offline*. No remote assets in the UI.

## Commits

- One logical change per commit, in plain English: what the user gets, then a short body explaining how.
  Example: `Safe copy and move: every copy verified by checksum, originals go to a restorable bin`
- Commits are authored as **buildcool** (`331665223+buildcool@users.noreply.github.com`), set in this repository's local git config. No co-author trailers.
- `main` holds releases; day-to-day work happens on `dev`.
