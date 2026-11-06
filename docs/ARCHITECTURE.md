# Architecture

RecPro is three cooperating parts that all run on the user's PC:

```
Electron window (React UI) --token--> Python engine (FastAPI on 127.0.0.1, random port)
  native: folder picker, drag-out,       |- Library: folders, scanner, watcher
  notifications, Show in Explorer        |- Indexer: staged background analysis (resumable)
  <-- WebSocket: progress, live results -|- AI pipeline (ONNX Runtime, CUDA when available)
                                         |- Review engine: tiers, calibration, learning
                                         |- File operations: copy -> verify -> Bin, journal, undo
  recpro-media:// thumbnails/videos <----|- SQLite (WAL) + FTS5 + vector search  @ data folder
```

## Desktop shell (`desktop/`)

- `main.ts` starts the engine, creates the window and registers two privileged protocols:
  - `app://ui/…` serves the built UI with a strict Content-Security-Policy (production).
  - `recpro-media://e/…` proxies thumbnails, previews, face crops and original videos from the engine, adding the secret token so it never appears in `<img>` URLs. Range requests are forwarded for video seeking.
- `engine.ts` spawns the engine (`uv run python -m recpro.server` in development, a bundled executable in production), reads its `RECPRO_READY {"port": N}` line and stops it by closing stdin. The engine exits on its own if the desktop app dies.
- `preload.ts` exposes a minimal bridge (`window.recpro`) to the sandboxed renderer: engine address, folder/file pickers, Show in Explorer, drag-out of files, notifications, and Windows lock events (used to lock Private).
- Hardening: `contextIsolation`, `sandbox`, no Node integration, navigation and new windows blocked, IPC accepted only from the app's own origin.

## UI (`ui/`)

React 19 + TypeScript, built with Vite and Tailwind CSS 4. Data via TanStack Query; live updates (indexing progress, operation progress, review counts, private state) arrive over one WebSocket (`lib/live.ts`) and invalidate the matching queries.

Key pieces: `app/AppShell.tsx` (top bar, sidebar, status bar), `app/CommandPalette.tsx` (Ctrl+K), `features/*` (find and move, review, people, private, file operations), `pages/*`.

## Engine (`engine/recpro`)

| Module | Responsibility |
|---|---|
| `server.py` | Binds 127.0.0.1 on a free port, prints the ready line, watches stdin |
| `bootstrap.py`, `context.py` | Builds services in order and starts/stops them |
| `db/` | SQLite with one connection per thread, serialized writes, WAL, migrations (`PRAGMA user_version`) |
| `api/` | FastAPI routers. `security.py` requires the per-launch token on every request and WebSocket. Host header must be 127.0.0.1/localhost (DNS-rebinding protection). |
| `library/` | Folders, scanning, metadata (EXIF/ffprobe), thumbnails, perceptual hashes, face crops |
| `jobs/` | Indexer and its stages |
| `ops/` | Copy/verify/remove/undo engine |
| `ml/`, `review/`, `private.py` | Recognition, ask-when-unsure tiers and learning, Private lock *(see Roadmap)* |

### Library scanning

- Folders are walked with `os.scandir`. System folders, `.RecPro-Bin`, junctions and RecPro's own data folder are skipped.
- **Cloud-only files are skipped.** OneDrive/Dropbox placeholders (`RECALL_ON_DATA_ACCESS`, `RECALL_ON_OPEN`, `OFFLINE` attributes) are counted and reported, never read, because reading them would download them from the cloud.
- Changes are detected by size + mtime. A file that disappears and reappears elsewhere with the same *quick hash* (size + first/last 64 KB) keeps its row, so faces, labels and your answers survive renames and moves.
- `watchdog` watches folders; events are debounced (3 s) into a rescan.

### Indexing pipeline

Each stage owns a version column on `media`. A row needs a stage while its column is below the stage version. All state is in the database, so indexing resumes after a restart, and changing a stage's version re-runs just that stage.

1. **Quick pass** (`jobs/quick.py`, CPU, parallel): EXIF date (with filename and file-time fallbacks), dimensions after rotation, camera, GPS, video duration/codec, a 400 px WebP thumbnail (JPEG draft decoding for speed), a 64-bit DCT perceptual hash and the quick hash.
2. **Private pre-check**: a fast sensitivity check on the thumbnail before it is shown *(M3)*.
3. **Deep pass**: decode once, run every model batched on the GPU: faces, embeddings, attributes, SigLIP 2, sensitive ensemble, objects, quality *(M2–M4)*.
4. **Text pass**: OCR gated by a document/screenshot score, then IDs and screenshot apps *(M5)*.
5. **Video pass**: frames, face tracks, per-person time segments, sensitive segments, speech *(M6)*.
6. **Grouping**: clustering, person matching, tiers, review queue, duplicates, events *(M2, M7)*.

The UI's status bar and Home page show per-stage progress and rate; folders being searched right now are processed first (`Indexer.focus`).

### Data model (SQLite)

`folders` · `media` (path, size, mtime, hashes, dimensions, taken_at, GPS, kind, duration, stage versions, private state) · `people` · `faces` (box, landmarks, quality, embedding, person, state, score) · `face_votes` (your yes/no answers) · `ref_faces` (faces from photos you dropped in) · `labels` (taxonomy, prompts, thresholds) · `media_labels` (score, tier, state, time range) · `embeddings` · `texts` (FTS5, trigram) · `operations` + `op_items` (file-operation journal) · `settings`.

Your answers (`face_votes`, confirmed/rejected states) are never overwritten by re-indexing or model upgrades.

## File operations (`ops/service.py`)

The copy-and-move engine is the part that must never lose a file. Its guarantees, each covered by `engine/tests/test_ops.py`:

1. **Planning first.** Destination paths follow the chosen layout (same folders, all together, year/month, by person). Free space, missing originals, files already in place, name conflicts and identical files are reported before anything starts.
2. **Copy with checksum.** Data is hashed with BLAKE3 while reading, written to `name.recpro-part`, flushed and fsynced, timestamps copied, then renamed into place (never overwriting). The copy is read back and must hash identically, or it is deleted and marked failed.
3. **Identical files count.** If an identical file is already at the destination, it counts as a verified copy; a different file with the same name is kept and the new one is saved as `name (1).ext` (or skipped, if chosen).
4. **Journaled.** Every file's state (`pending → verified/identical/skipped/failed → removed`) is committed as it happens. After a crash or power cut, interrupted operations come back *paused*, leftover `.recpro-part` files are removed, and *Resume* continues where it stopped.
5. **Removal only after verification.** Only verified/identical items can be removed, and only if the original is unchanged since it was copied (size + mtime) and the copy still exists. A source that changes *during* the copy is marked failed.
6. **The RecPro Bin.** Removing moves the original to `<drive>\.RecPro-Bin\op-N\<original path>` on the same drive (an instant rename; no extra space). The folder is hidden and contains a README. If the drive root isn't writable, the bin goes in the library folder's root. *Undo* puts every file back exactly where it was; if nothing was removed, undo moves the copies into the bin instead.
7. **Permanent deletion is explicit.** Only *Empty bin*, confirmed by the user, deletes files, and it refuses to delete anything outside a `.RecPro-Bin` folder.

## Security model

- The engine listens on 127.0.0.1 only, on a random port, and requires a 256-bit token generated by the desktop app at every launch.
- The UI's CSP allows only its own origin, the app protocols and 127.0.0.1. Fonts and icons are bundled; there are no CDNs.
- The only outbound network use is the one-time model download, which the user starts and can block with *Strict offline*.
- Private content: see [PRIVACY.md](PRIVACY.md).
