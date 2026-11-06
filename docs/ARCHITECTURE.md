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
4. **Text pass** (`jobs/text.py`): reads the words in photos whose stored category scores say document, ID card, screenshot or meme (or whose file looks like a screenshot), then finds ID documents and screenshot apps. See [Text in photos](#text-in-photos-mlocrpy-jobstextpy-idspy-screenspy).
5. **Video pass**: frames, face tracks, per-person time segments, sensitive segments, speech *(M6)*.
6. **Grouping**: clustering, person matching, tiers, review queue, duplicates, events *(M2, M7)*.

The UI's status bar and Home page show per-stage progress and rate; folders being searched right now are processed first (`Indexer.focus`).

### Data model (SQLite)

`folders` · `media` (path, size, mtime, hashes, dimensions, taken_at, GPS, kind, duration, stage versions, private state) · `people` · `faces` (box, landmarks, quality, embedding, person, state, score) · `face_votes` (your yes/no answers) · `ref_faces` (faces from photos you dropped in) · `labels` (taxonomy, prompts, thresholds) · `media_labels` (score, tier, state, time range) · `embeddings` · `texts` (FTS5, trigram) · `operations` + `op_items` (file-operation journal) · `settings`.

Your answers (`face_votes`, confirmed/rejected states) are never overwritten by re-indexing or model upgrades.

## AI models (`ml/models.py`)

Models are listed in a manifest with their purpose, license and profiles (*best* or *fast*). The downloader writes `.part` files into the data folder, resumes after dropped connections (HTTP Range, five attempts), rejects HTML responses (sign-in pages), and verifies every file: a pinned SHA-256 for release assets, the LFS SHA-256 or git blob SHA-1 from the Hugging Face API for repository files. A `.verified` marker records a complete install. *Strict offline* blocks the downloader entirely.

`ml/runtime.py` creates ONNX Runtime sessions on CUDA (cuDNN 9, CUDA libraries installed as Python packages and preloaded) with CPU fallback.

## Faces and people (`ml/faces.py`, `review/`)

**Pipeline (deep pass).** Each photo is decoded once at up to 2048 px. SCRFD-10G detects faces at 640 px and, for larger photos, at 1280 px for small faces in group shots; detections are merged with NMS and kept down to a 0.40 score, so weak faces are asked about instead of dropped. Each face is aligned from its 5 landmarks (Umeyama similarity transform) and embedded with ArcFace R100 (antelopev2 `glintr100`), averaging the face and its mirror image. Age/gender come from `genderage.onnx`, and a quality score combines size, detector confidence, pose (yaw/roll from landmarks) and sharpness (Laplacian variance). When a photo is analyzed again, confirmed answers move to the re-detected face at the same spot.

**Matching.** A person is the set of their confirmed, sure and grouped faces (up to 200, best first) plus reference photos you provided. A face's score for a person is the mean of its 3 highest cosine similarities to those faces, so childhood and adult photos both match. Thresholds come from *How often RecPro asks you*:

| Setting | Sure ≥ | Please check ≥ |
|---|---|---|
| Never miss | 0.50 | 0.22 |
| Balanced | 0.47 | 0.28 |
| Fewer questions | 0.44 | 0.34 |

A face is never *Sure* when its quality is below 0.35 or when a second person scores within 0.06. There's only one face per person per photo, and a face you confirmed for someone is never offered for anyone else. Once there are enough answers (8 yes, 5 no), a logistic fit of your answers against the score shifts the thresholds; *Never miss* can only become more careful.

**Grouping.** Unassigned faces of reasonable quality are linked to their mutual nearest neighbours above 0.48 similarity (never two faces of the same photo). Connected groups of at least 3 faces become *unnamed people*, keeping one face per photo. Unnamed groups whose centres are above 0.62 merge automatically; pairs above 0.40 become "Same person?" questions. New faces join an unnamed group above 0.50.

**Answers.** Yes confirms and records a vote; No records a vote that is never overridden and frees the face for other people. After each answer the person is re-scored across the whole library, which is how one answer settles similar photos. The last 30 answers can be undone. Review shows the faces closest to a coin flip first, one per near-duplicate photo.

**Find** (`review/search.py`) scores every face in the chosen folders against each chosen person (or reference photo), combines them for *any*, *all together* or *alone*, and returns *Sure* and *Please check* tiers grouped by folder, plus the number of hidden private matches. Folders still being analyzed are processed first.

**Index.** Face embeddings live in a growable in-memory float16 index (`review/faceindex.py`) loaded at startup, so matching a person against the library is a chunked matrix multiplication.

## Private content (`jobs/sens.py`, `jobs/semantic.py`, `labels.py`, `private.py`)

**Stages.** The indexer runs `quick → sens → deep → semantic → text`, so the private check happens right after thumbnails and before faces. `sens` runs NudeNet 640m on each photo decoded at up to 1280 px (plus 4 overlapping tiles for photos of 1400 px or more) and on 3 frames of each video. It decodes boxes, applies per-class NMS, and drops exposed-part detections centered on a face (NudeNet's own face boxes plus SCRFD). `semantic` embeds each photo with SigLIP 2 (stored in `embeddings` for search) and scores prompt ensembles with SigLIP's own sigmoid (`logit_scale`/`logit_bias` read from the official checkpoint).

**Labels and tiers.** Every source has its own (check, sure) thresholds per sensitivity (`labels.THRESHOLDS`); a label's tier is the best tier any source reaches, and the per-source values are stored, so `retier()` can apply new thresholds or a new sensitivity without re-analysis. `update_sens_state` derives `clear`, `review` or `private` from the sensitive labels: a confirmed label means private; all rejected means clear; otherwise AI *Sure* means private and AI *Please check* means review. Both `private` and `review` are hidden like private content. With *Treat ID documents as private* on, an ID document that is AI *Sure* or confirmed is private too (ID documents the AI isn't sure about stay visible and wait in their category); answering an ID category or changing the setting updates the state.

**Absolute scores only.** Private content counts SigLIP's absolute probability and NudeNet, never the relative (group softmax) score the categories use: a softmax against a handful of "ordinary photo" prompts can't cover every kind of photo, and on 733 safe photos it put 158 in Private and 354 in *Please check* (absolute scores: 0 and 8). `source_key` ignores a stored relative score for private content, and taxonomy v3 drops the ones stored before.

**Lock.** The PIN or password is stored as an Argon2id hash. An X25519 key pair is created at setup; the private key is encrypted with a key derived from the secret (Argon2id raw, 64 MiB) and only decrypted in memory on unlock. When an item becomes private, its plain thumbnail, preview and face crops are deleted, and thumbnails and previews are written as sealed boxes, which the engine can create while locked but only read while unlocked. While locked, thumbnails return a lock placeholder, details/previews/originals return 423, private listings are refused, and every listing and search leaves private items out (Find reports how many). After unlocking, *Blur* and *Show private items everywhere* are in-memory toggles reset by every lock. Auto-lock fires after the chosen idle time (the UI sends activity pings), on Windows lock or sleep, on Ctrl+L and on restart. Five wrong tries within 5 minutes impose a 30-second wait. *Forgot your PIN?* deletes the keys, private labels and sealed images, then re-checks everything.

## Categories and search (`taxonomy.py`, `semindex.py`, `review/query.py`)

**Embeddings once, categories any time.** The semantic stage stores one SigLIP 2 embedding per photo (`embeddings`, float16) and an in-memory index (`semindex.py`) loads them at startup. Built-in categories (`taxonomy.BUILTIN`, about 90 prompt ensembles in 9 groups) and your own categories are scored from those embeddings, so a new category or a new taxonomy version re-scores the whole library in seconds with no photo decoding.

**Relative scoring.** SigLIP's own sigmoid stays low for short prompts (a real chat screenshot scores 0.12 for "a chat screenshot"), so each category competes in a softmax at SigLIP's temperature against the other categories of its group and a few "nothing special" background prompts (`taxonomy.BACKGROUND`). Photo groups also get "it's text" alternatives (`TEXT_BG`: a page of printed text, a chat screenshot, a bill, a plain background, an ID card), so documents and chats aren't forced into a photo category (before, a chat about a party was *Party* and a white ID card *Snow*); People keeps its own list, since a headshot looks like an ID photo. Your own categories compete only with generic backgrounds. Private content isn't scored this way (see above). The absolute probability is stored as a second source. Moods, kinds of people and entertainment use stricter "sure" thresholds. After 8 confirmed and 8 rejected answers, a logistic regression on the embeddings becomes a third source ("personal").

**Expressions.** HSEmotion EfficientNet-B2 classifies each face into 8 expressions. Its probabilities are flat, so search uses per-expression confidence floors (stricter for angry, disgust and contempt, which AffectNet models over-predict on neutral faces).

**Universal search.** `query.parse` extracts named people (longest names first), years, months, photo/video, age and gender words, group size, expressions, folder names and an exact category name; the rest is free text. Words are split on spaces and punctuation rather than `\w`, which would cut Hindi and other Indic words at their vowel signs. `query.run` narrows by these filters (people via Find, expressions on the matched person's own face) and ranks free text by its relative SigLIP score against generic backgrounds, plus words found inside photos. A query mixing private content with children is refused.

## Text in photos (`ml/ocr.py`, `jobs/text.py`, `ids.py`, `screens.py`)

**Reading.** PaddleOCR PP-OCRv5 (ONNX exports, Apache-2.0): the server text detector and the English v5 and Devanagari v3 line recognizers. Detection runs on the image in BGR at 1280 px on the long side (1600 px for tall screenshots, whose text is small; again at 960 px if nothing is found, since big headings at high resolution merge into blobs), then DB post-processing: probability map above 0.3, boxes whose mean probability is at least 0.6, grown by area × 1.5 / perimeter. Each box is cut out with a perspective warp from the photo decoded at up to 2400 px (tall boxes are turned upright), and both recognizers read every line in batches; CTC greedy decoding gives the text and a mean confidence, the more confident script wins (English on near-ties), and lines below 0.5 are dropped. Lines are joined into rows in reading order. A likely document with almost no text is tried at 90°, 270° and 180°. Turning off *Also read Hindi and Marathi* skips the Devanagari recognizer.

**What gets read.** The text pass runs after the semantic pass and reads a photo when its stored scores reach 0.10 for a document or ID category, 0.15 for a screenshot category (video calls don't count: news and event photos score on them), 0.30 for memes and greeting images, or when the file looks like a screenshot. On 733 face photos this reads 81 and skips only scraps of background signage.

**ID documents.** Each rule pairs a structure check with the words printed on the card: both mean *Sure*, one means *Please check*, and words alone count only on something card-like (date of birth, gender, address, father's name), not on an SMS that mentions Aadhaar.

| Document | Structure | Words |
|---|---|---|
| Aadhaar | 12 digits passing the Verhoeff checksum (or `XXXX XXXX 1234` with its words) | Aadhaar, आधार, UIDAI, Unique Identification, or Government of India with a date of birth |
| PAN | 5 letters (4th = holder type P, C, H, F, A, T, B, L, J, G), 4 digits, 1 letter; not inside a GSTIN | Income Tax Department, Permanent Account Number |
| Passport | Machine-readable zone with valid ICAO 9303 check digits (enough on its own) or its first line with "passport" | Passport, पासपोर्ट, Republic of India |
| Driving licence | State code, RTO, year, 7-digit serial | Driving licence, DL no, Transport Department, Form 7 |
| Voter ID | EPIC: 3 letters, 7 digits | Election Commission of India, Elector |

Before text is stored in the `texts` FTS5 table (trigram tokenizer, so any 3+ characters match, in any script), `mask_ids` keeps only the last 4 characters of Aadhaar, PAN, licence, EPIC and passport numbers and of machine-readable lines. Any 12-digit number printed in groups of four is masked even when OCR misread a digit; an ungrouped reference number that fails the checksum (a UPI transaction ID) stays searchable.

**Screenshots.** `looks_like_screenshot` scores the file: named like one (0.9), or screen-sized without camera EXIF (0.75 for PNG, 0.6 for JPEG), or a phone-shaped PNG (0.55). App keywords on the screen sort screenshots by app: WhatsApp, Instagram, Telegram, Facebook, YouTube, X, payments (UPI), shopping, email, bank messages and maps; chat apps also count towards *Chat screenshots* and social apps towards *Social media posts*. Apps are only read from screenshots, so a payment QR standee photographed in a shop isn't a payment screenshot.

**Labels.** ID documents (`id.*`) and app screenshots are categories without prompts, filled by the sources `ocr` (rule scores: 1.0 sure, 0.6 please check) and `file` (screenshot file facts), next to SigLIP's own score where a category has one (*Payments*, *Maps*, *Screenshots*). Explore shows ID documents as their own group.

## File operations (`ops/service.py`)

The copy-and-move engine is the part that must never lose a file. Its guarantees, each covered by `engine/tests/test_ops.py`:

1. **Planning first.** Destination paths follow the chosen layout (same folders, all together, year/month, by person). Free space, missing originals, files already in place, name conflicts and identical files are reported before anything starts.
2. **Copy with checksum.** Data is hashed with BLAKE3 while reading, written to `name.recpro-part`, flushed and fsynced, timestamps copied, then renamed into place (never overwriting). The copy is read back and must hash identically, or it is deleted and marked failed.
3. **Identical files count.** If an identical file is already at the destination, it counts as a verified copy; a different file with the same name is kept and the new one is saved as `name (1).ext` (or skipped, if chosen).
4. **Journaled.** Every file's state (`pending → verified/identical/skipped/failed → removed`) is committed as it happens. After a crash or power cut, interrupted operations come back *paused*, leftover `.recpro-part` files are removed, and *Resume* continues where it stopped.
5. **Removal only after verification.** Only verified/identical items can be removed, and only if the original is unchanged since it was copied (size + mtime) and the copy still exists. A source that changes *during* the copy is marked failed.
6. **The RecPro Bin.** Removing moves the original to `<drive>\.RecPro-Bin\op-N\<original path>` on the same drive (an instant rename; no extra space). The folder is hidden and contains a README. If the drive root isn't writable, the bin goes in the library folder's root. *Undo* puts every file back exactly where it was; if nothing was removed, undo moves the copies into the bin instead.
7. **Permanent deletion is explicit.** Only *Empty bin*, confirmed by the user, deletes files, and it refuses to delete anything outside a `.RecPro-Bin` folder.

## Packaging, releases and updates (`scripts/build_engine.py`, `desktop/`, `.github/workflows/`)

**Installer.** The engine is frozen with PyInstaller into one folder (`recpro-engine.exe` plus its libraries, about 540 MB) with ffmpeg and ffprobe in `bin/`. electron-builder packs it with the built UI as resources next to the Electron shell into an NSIS installer: per user, with a choice of folder. The shell starts `resources/engine/recpro-engine.exe` and serves the UI from `resources/ui`. The engine finds the bundled ffmpeg before `PATH`.

**GPU pack.** The NVIDIA CUDA 13 and cuDNN 9 libraries (1.7 GB) would push the installer past NSIS's and GitHub's 2 GB limits, so the installed app leaves them out. On a PC with an NVIDIA driver (`nvcuda.dll`), the model list offers *GPU acceleration*: the Windows wheels of the same NVIDIA packages that development installs (`GPU_WHEELS`, kept in step with `uv.lock` by a test), downloaded from PyPI, checked against PyPI's SHA-256, with their DLLs unpacked into one folder. `ml/runtime.py` adds that folder to the DLL search path and has ONNX Runtime preload from it. Once it's installed, loaded models are dropped so they load again on the GPU. Without it everything runs on the processor.

**Thread-safe start-up.** Modules that load native libraries (SciPy's BLAS through `scipy.fft`, ONNX Runtime) are imported on the importing thread, never first from a worker thread: a frozen engine starts with nothing loaded, and SciPy's BLAS DLL never finished loading when the quick pass's 12 threads reached it first.

**Releases.** `ci` runs the engine tests on Windows (without the CUDA libraries) and type-checks and builds the UI and shell. A release is cut when `main` carries a version with no tag: `release` checks the versions and notes (`scripts/release.mjs check`), creates the tag and the GitHub release from `docs/releases/vX.Y.Z.md`, and calls `desktop`. `desktop` freezes and smoke-tests the engine, bundles checksum-verified ffmpeg, builds the installer and attaches it with `latest.yml`. It also runs on `dev` when packaging files change, keeping the installer as a build artifact.

**Updates** (`desktop/src/updater.ts`). electron-updater with the GitHub provider, in one of three modes: *auto* (check on start and daily, download in the background, ask to restart), *notify* (the default: check and show what's new) or *off*. It never restarts by itself. *Strict offline* stops every check, read from the engine's settings. A development run can't replace itself, so it asks GitHub's API and opens the release page.

## Security model

- The engine listens on 127.0.0.1 only, on a random port, and requires a 256-bit token generated by the desktop app at every launch.
- The UI's CSP allows only its own origin, the app protocols and 127.0.0.1. Fonts and icons are bundled; there are no CDNs.
- Outbound network use is limited to the one-time model and GPU pack downloads, which the user starts, and the update check (Settings → Updates). *Strict offline* blocks all of them.
- Private content: see [PRIVACY.md](PRIVACY.md).
