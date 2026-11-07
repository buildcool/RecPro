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
5. **Quality pass** (`jobs/quality.py`): brightness, highlights and sharpness of each photo, from its thumbnail, for Cleanup.
6. **Places pass** (`jobs/places.py`): the town, and the city it belongs to, of every photo and video with a GPS position, from the place table shipped with the engine. See [Places](#places-libraryplacespy-jobsplacespy-apiroutes_placespy).
7. **Video pass** (`jobs/video.py`): each video watched once: faces tracked into one face per person with the time spans they're on screen, private content and categories with their spans, and scene frames for searching moments. See [Videos](#videos-jobsvideopy-mltrackspy-framelabelspy-libraryvideopy).
8. **Speech pass** (`jobs/speech.py`): what is said in each video, with times. The last and slowest stage.
9. **Grouping**: clustering, person matching, tiers and the review queue run all the time *(M2)*. Duplicates, trips and events are worked out when asked for (see [Cleanup](#cleanup-cleanuppy-jobsqualitypy) and [Trips](#trips-events-and-on-this-day-memoriespy)).

The UI's status bar and Home page show per-stage progress and rate; folders being searched right now are processed first (`Indexer.focus`).

### Data model (SQLite)

`folders` · `media` (path, size, mtime, hashes, dimensions, taken_at, GPS, kind, duration, stage versions, private state, quality facts, town and city) · `people` · `faces` (box, landmarks, quality, embedding, person, state, score) · `face_votes` (your yes/no answers) · `media_people` (photos a person is in without a visible face) · `ref_faces` (faces from photos you dropped in) · `labels` (taxonomy, prompts, thresholds) · `media_labels` (score, tier, state, time range) · `embeddings` · `texts` and `speech` (FTS5, trigram) · `places` (the towns photos are in) · `saved_searches` · `pending_answers` (imported answers waiting for their photos) · `operations` + `op_items` (file-operation journal) · `settings`.

Your answers (`face_votes`, `media_people`, confirmed/rejected states) are never overwritten by re-indexing, model upgrades or an import.

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

## Videos (`jobs/video.py`, `ml/tracks.py`, `framelabels.py`, `library/video.py`)

**Frames.** One ffmpeg process decodes each video once and streams frames as raw RGB, upright (rotation metadata applied) and scaled to 1024 px on the long side: 1 a second, sparser past 10 minutes (at most 600 frames, at least one every 10 seconds). Frame *k* is at *k*/fps seconds. The pass runs after every photo stage, one video per batch, so new photos keep priority.

**People.** Faces are detected and embedded per frame, then linked into tracks: the same face in the next frames (cosine ≥ 0.40), or a weaker match (≥ 0.20) where the box barely moved, so a turned head or motion blur stays in its track; a face may be missing for up to 3 frames. Tracks of the same person that never share a frame are merged (cosine of their quality-weighted mean embeddings ≥ 0.45), so someone who leaves and comes back is one face of the video. That keeps the people logic's rule of one face per person per photo. Each face stores its best frame (for the crop), its mean embedding, and its time spans (`face_spans`). A single weak detection is dropped. Analysing a video again carries names, answers, votes and covers to the new face with the closest embedding.

**Private content and categories.** NudeNet checks every sampled frame. SigLIP 2 embeds a frame every 2 seconds and keeps it only when the picture changed (cosine < 0.92 to the last kept frame), so a static video costs a few vectors. A video's labels are the best score any frame reaches, and `label_spans` records where each label reaches *please check*. Each frame counts until the next kept one, and the ranges are joined across sources (`framelabels.py`). Private content anywhere in a video makes the whole video private. Category re-scoring (a new category, a taxonomy version) covers videos through their stored frames, and videos are watched again when a face, private-content or SigLIP model arrives.

**Search and viewer.** Find attaches every searched person's spans to a video and opens it at the first. Universal search does the same for people, categories, age, gender or expression filters (the matching faces' spans), and descriptions (every scene frame is scored and the best one is the match). The viewer draws one lane per person and per category or private label under the video, with a playhead; clicking a stretch jumps there.

**Playable copies** (`library/playable.py`). When the player can't open a video (HEVC without a decoder, AVI, old codecs), the engine makes an H.264 copy on demand: NVENC when available, else x264, the long side at most 1280 px, AAC sound, fast start. It's kept in `previews/` and served with range requests; the viewer shows progress and switches over. Private videos never get one, a copy is deleted when its video becomes private, and copies of removed or private videos are cleaned up at start-up.

## Speech (`jobs/speech.py`, `ml/speech.py`)

ffmpeg decodes a video's sound as 16 kHz mono float32 (up to 3 hours). faster-whisper runs Whisper large-v3 turbo (Whisper small in the *fast* set) with its Silero voice detector, so only speech is transcribed. Segments Whisper itself rates as non-speech (no-speech probability > 0.6 and log-probability < −1) are dropped, and segments are decoded independently (`condition_on_previous_text=False`), so one bad segment can't drag the rest into a loop. CTranslate2's GPU build needs CUDA 12's cuBLAS and RecPro carries CUDA 13, so speech runs on the processor (int8, all physical cores) unless CUDA 12 is present. That's roughly real time on a long talk, and about 13 s for the 18 s test video, whose sound is a 30 s window. Segments go into the `speech` FTS5 table (trigram, any script) with their times and ID numbers masked. Search counts them like words in photos and opens the video where they're said; the viewer lists them under *Said in this video*.

faster-whisper declares the CPU `onnxruntime`, which would overwrite `onnxruntime-gpu` (both install the `onnxruntime` module), so `[tool.uv] override-dependencies` drops it; the voice detector runs on `onnxruntime-gpu`.

## Faces that aren't visible (`review/hidden.py`)

For a named person, photos from the same directory within 3 hours of a photo where they were recognised are candidates, minus the ones that already show their face, were answered, or have a face you said isn't them. Two kinds are suggested:

- a face too unclear to recognise (quality < 0.45) that still looks a little like them (top-3 mean cosine ≥ 0.10 to their faces; strangers sit around 0 ± 0.1), ranked by resemblance;
- no face found, but SigLIP sees a person: a softmax of "a person seen from behind" and similar prompts against "no people" prompts, ≥ 0.4.

A photo whose faces are all clear and someone else's isn't suggested: the person isn't recognisable there, which is different from their face being hidden. Answers are stored in `media_people`. A yes counts in Find as a sure match without a face, a no is never asked again, and Find tells you how many are left for the person searched.

## Cleanup (`cleanup.py`, `jobs/quality.py`)

Cleanup proposes, you choose, and a removal is one operation in History that moves files to the RecPro Bin; Undo puts them back.

| Kind | Found by | What stays |
|---|---|---|
| Exact duplicates | the same quick hash (size and the first and last 64 KB); at removal both files' full BLAKE3 hashes must match | the original-looking one (as for copies) |
| Copies | perceptual hash within 6 bits (found through 4 bands of 16 bits) and SigLIP cosine ≥ 0.85, which rules out flat images | camera EXIF beats none, a forward loses, then pixels and size; a much blurrier file never wins |
| Similar shots | camera photos with an EXIF time, in one folder, < 60 s apart, SigLIP cosine ≥ 0.95. A file's modified time isn't a moment: a copied folder shares one | 0.5 × sharpness + 0.2 × exposure + 0.3 × best face quality |
| Too dark | thumbnail mean < 40 and 95th percentile < 110, so night shots with lights stay | — |
| Blurry or by accident | SigLIP *Sure* blurry and Laplacian variance < 45 on the thumbnail (SigLIP alone also calls small or soft photos blurry), *Sure* accidental shots, and your confirmations | — |
| WhatsApp forwards | no camera EXIF, and a WhatsApp file name or folder; greetings and memes first | — |

A group is never emptied: each removed file names the one it's removed for, and goes only while that one is still there and isn't being removed too. Results are cached for a minute per view (Private locked or open) and library size, so nothing private is listed after re-locking. The summary's total counts each file once.

## Places (`library/places.py`, `jobs/places.py`, `api/routes_places.py`)

The engine ships `data/places.npz`: GeoNames' `cities1000` (about 172,000 towns of 1,000+ people and every district seat, CC BY 4.0) with state, country, position and population, 3 MB, rebuilt by `scripts/build_places.py`. Nothing is looked up online.

- **Naming.** A KD-tree on unit vectors finds the nearest town (the locality). The city is the place in the same country and state, within 30 km, with the highest population / (1 + km/2)². So Shivaji Nagar is in Pune, Calangute (13 km from Panaji) keeps its name, and Kehl isn't Strasbourg. A position more than 150 km from any town (at sea) or at 0,0 gets no place. Where the local script isn't Latin the plain spelling is shown (Thane, not Thāne).
- **Map.** The UI draws Natural Earth country outlines (`world-atlas`, 50 m, bundled) with d3-geo in fixed Mercator coordinates; the zoom transform is the window, so resizing doesn't move the view. Dots are photos grouped on a grid about 64 px wide on screen, merged when closer than one cell, never with a private cover. Once you zoom in, the biggest towns from the same table label the map.
- **Search.** Town, state and country names with photos match without accents or case ("ile-de-france"), and next to a place "trip", "holiday" and the like are dropped ("Goa trip 2023").

## Trips, events and On this day (`memories.py`)

- **Home** is the town with photos on the most different days, or the one picked on the Places page (`places.home_city_id`).
- **Trips** are runs of 2 or more photos 50+ km from home, with no photo at home in between and never 2½ days without one. One is named after the town with 60% or more of its photos, else the state or country if they're all in one (other than home's), else its two main towns. Camera photos without a location taken during it belong to it.
- **Events** are sessions of camera photos (gaps under 3 hours, 6 or more photos) where wedding, birthday, festival, party or concert is *Sure* on at least a quarter of them, and at least 3.
- **On this day** lists photos from today's date in earlier years, leaving out screenshots, documents, IDs, greetings, memes, photo-quality labels and private items (always, even with Private open).

All of it is worked out when asked and cached for a minute, keyed by the view, the library size and home, so answers count straight away.

## Saved searches

A saved search keeps the words and the chips you removed (`saved_searches`). It runs again each time it's opened, so new photos join it.

## Names and answers in a file (`labels_io.py`)

**Export** writes JSON: people (name, birthdate, hidden), their face answers (photo, box, the frame for videos, yes or no), the photos they're in without a visible face, and category answers, with your own categories' descriptions. Photos are identified by the quick hash, never the path. Nothing about private photos or the private categories goes in.

**Import** makes the people and your categories that aren't there, then applies the answers. A face matches the face found at the same spot (IoU ≥ 0.6, and within 1.5 s in a video). An answer already given on this PC is never changed. Answers for photos not read yet, or faces not found yet, wait in `pending_answers`; the indexer applies them after its quick, deep and video passes.

## XMP sidecars (`xmp.py`)

Only on request: `IMG_1234.jpg.xmp` next to each photo with its people (confirmed or *Sure* faces, and yes answers for hidden faces), categories (*Sure* or confirmed; never private, ID or photo-quality ones) and place, as `dc:subject`, `lr:hierarchicalSubject`, `digiKam:TagsList`, `Iptc4xmpExt:PersonInImage` and `photoshop:City/State/Country`. A sidecar without RecPro's namespace belongs to another app and is left alone. Private photos never get one. Face areas aren't written, because apps disagree on how they apply to rotated photos.

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
- Place names and the map come from data shipped with the app; no map-tile or geocoding service is ever contacted.
- Private content: see [PRIVACY.md](PRIVACY.md).
