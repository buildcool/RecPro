# Changelog

All notable changes to RecPro. Versions follow [Semantic Versioning](https://semver.org).

## Unreleased

### Added
- Local engine on 127.0.0.1 with a per-launch secret token, host checking and live events over WebSocket.
- Library folders: add (a parent folder absorbs folders already in the library), remove (files untouched), watch for changes, include/exclude subfolders.
- Scanner that skips cloud-only OneDrive/Dropbox files instead of downloading them, and keeps everything RecPro learned when files are renamed or moved.
- Quick pass: dates from EXIF, file names (WhatsApp, screenshots, phone cameras) or file times; dimensions after rotation; camera; GPS; video duration and codec; thumbnails; perceptual hashes.
- Safe copy and move: BLAKE3-verified copies, journaled per file, resumable after a crash; originals removed only after verification and only if unchanged; the restorable RecPro Bin; undo; explicit *Empty bin*.
- Desktop shell: Electron window that starts and stops the engine, private media protocol with video seeking, native folder pickers, drag files out, notifications, Windows-lock events.
- Interface: light and dark themes, sidebar, status bar with live progress and pause, Ctrl+K command palette, Home, Folders, Settings, first-run setup, Private unlock dialog.
- Photos: month-by-month timeline with a justified grid, three thumbnail sizes, a year rail, and photo/video filters. It stays smooth on large libraries because only visible months load.
- Selecting: click the circle, Ctrl+click, Shift+click a range, or a whole month; drag the selection out to File Explorer or WhatsApp.
- Viewer: full-screen photos and videos with arrow keys, a details panel (where the date came from, file, folder, camera, place), Show in folder, and Copy to.
- Copy dialog: choose a destination, what happens to the originals, the folder layout and the name-conflict rule; see space and conflicts before starting; watch progress (pause, resume, run in background); then decide about the originals: RecPro Bin, Windows Recycle Bin, or keep. Windows notification when a background copy finishes.
- History and bin: every operation with resume, retry failed, move originals to the bin, open, and undo; the RecPro Bin with restore and a confirmed permanent delete.
- AI models: one-time downloads (best or fast set) into the data folder, resumable, verified by pinned SHA-256 or Hugging Face hashes; a guard against web pages served instead of files; Settings lists every model with its license and status. Runs on the GPU (CUDA) with CPU fallback.
- Faces: detection at two scales for small faces in group shots, 5-point alignment, ArcFace R100 recognition averaged with the mirror image, age and gender estimates, and a face quality score. Your answers survive re-analysis.
- People: unknown faces are grouped automatically (mutual nearest neighbours, never two faces of one photo); naming a group, or typing an existing name, merges it; "Same person?" suggestions; hide strangers; "Often with"; a coverage meter ("≈ 97% found").
- Ask when unsure: every face lands in Sure / Please check / No with thresholds set by "How often RecPro asks you"; low-quality faces and near-ties are never decided automatically; each answer re-scores similar faces and calibrates the thresholds; undo.
- Review: "Is this …?" batches with the most informative faces first (keyboard Y/N/Space/P/Z), "Same person?" and "Who is this?".
- Private check before showing: right after thumbnails, NudeNet 640m checks every photo (and 3 frames of every video) at full size plus tiles for large photos; detections sitting on a face are ignored (close-up skin isn't nudity). Unchecked items show as blurred "Checking…" tiles.
- Private content ensemble: NudeNet (nudity, suggestive) plus SigLIP 2 prompts (romance, suggestive, nudity, sexual), recall-first with Sure / Please check tiers per "How often RecPro asks"; your answers always win; changing the setting re-tiers stored scores without re-analyzing.
- Private section: PIN or password (Argon2id), private thumbnails and previews sealed with X25519 boxes (no readable copy left on disk), hidden from every view and API while locked, a "hidden" count in Find, Blur and "Show private items everywhere" toggles after unlocking, auto re-lock after inactivity, Windows lock, sleep or Ctrl+L, rate-limited unlock, and a safe "Forgot your PIN?" reset.
- Review → Private: blurred batches with press-and-hold to peek and Not sensitive / Romance / Suggestive / Nudity / Sexual answers.
- SigLIP 2 understanding: every photo gets a multilingual image embedding (stored for search) at about 18 photos/s on an RTX 4070; the text model runs on the CPU with a persistent prompt cache so 8 GB of VRAM isn't exceeded.
- Categories: about 90 built-in categories (activities, moods, places, kinds of people, things, pets, documents and IDs, screenshots, entertainment) scored from the stored SigLIP 2 embeddings with relative (group softmax) scoring against "nothing special" prompts, with stricter "sure" for subjective groups. New or changed categories score the whole library in seconds without re-reading photos.
- Your own categories: describe them in words; matches appear right away, "Maybe" items can be confirmed or rejected, and after 8 yes and 8 no answers a personal classifier trained on your answers joins in.
- Facial expressions per face (HSEmotion, 8 expressions), filled in later for photos analyzed before the model arrived.
- Universal search: people names (together), years and months, photos/videos, girl/boy/woman/man/baby/kids/old, alone/couple/group, expressions on the right person's face ("Colin Powell smiling"), folder names, category names, and free text understood by SigLIP 2; results in Best matches and Maybe with removable "Understood as" chips. Private content can't be searched together with children.
- Explore: category cards with covers and counts; category pages with the timeline and a "Maybe" strip.
- Re-analysis keeps people: when faces are detected again, the face at the same spot inherits its person, state, votes and cover.
- Find and move: pick people (any of them, all together, or alone) or use a photo of someone, choose folders and photos/videos, see Sure matches grouped by folder and the doubtful ones to tick, how many private matches are hidden, then copy or move with the safe copy flow. Searching a folder that is still being analyzed processes it first and updates live.
