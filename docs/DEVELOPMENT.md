# Development

## Requirements

- Windows 10/11 (macOS/Linux work for the engine and UI, but the shell targets Windows)
- Node.js 20.19+ and npm
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

### Keep downloads and caches on D:

This project keeps every download off C:. Before installing Python packages, point uv's cache and temp folders into the repository (npm already uses `.cache/npm` through the project `.npmrc`):

```bash
export UV_CACHE_DIR='D:\Claude\github\RecPro\.cache\uv' TEMP='D:\Claude\github\RecPro\.cache\tmp' TMP='D:\Claude\github\RecPro\.cache\tmp'
```

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
npm run test:engine        # pytest: file-operation guarantees and more
npm run typecheck          # UI and desktop TypeScript
npm run test:ui            # vitest
```

## Building

```bash
npm run build              # UI production build + desktop bundle
```

Packaging (electron-builder + PyInstaller engine) arrives in milestone M8.

## Conventions

- **Engine:** Python 3.12, type hints, no global state beyond the `Context`. Long work runs in services/threads; API handlers stay quick. Anything that touches user files goes through `ops/` and keeps its guarantees tested.
- **UI:** function components, TanStack Query for server state, Zustand for UI state, Tailwind tokens from `styles.css` (never raw colors). Copy is sentence case, verb-first buttons, no "please".
- **Privacy:** no network calls from the engine except the model downloader; no remote assets in the UI.

## Commits

- One logical change per commit, in plain English: what the user gets, then a short body explaining how.
  Example: `Safe copy and move: every copy verified by checksum, originals go to a restorable bin`
- Commits are authored as **buildcool** (`331665223+buildcool@users.noreply.github.com`), set in this repository's local git config. No co-author trailers.
- `main` holds releases; day-to-day work happens on `dev`.
