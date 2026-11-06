# Privacy

RecPro's promise is simple: **nothing leaves this PC.**

## What never leaves your computer

- Photos and videos, including thumbnails and previews
- Faces and face data (embeddings), names you give people and your answers
- Text read from images (OCR) and speech transcribed from videos
- Categories, private-content scores, locations and everything else RecPro learns

All analysis runs locally with ONNX Runtime (on your graphics card when available).

## Network use

RecPro uses the internet for two things, and *Strict offline* (Settings → Network) blocks both:

- **Downloading its AI models**, the first time you set up recognition. You start it, you see the sizes first, and each file is checked against a SHA-256 hash. On a PC with an NVIDIA graphics card, the installed app also offers the **GPU pack** (about 1.2 GB): NVIDIA's CUDA and cuDNN libraries, downloaded from NVIDIA's own packages on PyPI and checked against PyPI's SHA-256.
- **Checking for updates** (Settings → Updates: *Download for me*, *Ask me first*, the default, or *Off*). A check asks GitHub for RecPro's latest release; GitHub sees the app's version and your IP address. Nothing about your photos, people, text or settings is sent. Updates install only when you click *Restart to update*, or when you next close RecPro after a download.

There is no telemetry, analytics or crash reporting.

The engine only listens on `127.0.0.1` and requires a secret token that the desktop app creates at every launch, so other programs and websites can't query it.

## What is stored, and where

Everything RecPro creates is in its data folder, chosen during setup (for example `D:\RecProData`):

| Path | Contents |
|---|---|
| `recpro.db` | Library index, faces, people, labels, text read from photos and speech from videos (ID numbers masked), when people and categories appear in videos, your answers, settings, operation history |
| `thumbs/`, `previews/`, `faces/` | Small images for the interface, and playable copies of videos the player can't open (never of private videos) |
| `private/` | Encrypted thumbnails and previews of private items |
| `models/` | Downloaded AI models |
| `logs/` | Engine logs (file paths, no image content) |

Your original files are never modified by analysis. They are only copied, moved or removed when you ask, and removals go to the restorable RecPro Bin (see [ARCHITECTURE.md](ARCHITECTURE.md#file-operations-opsservicepy)).

Files whose content lives only in the cloud (OneDrive "online-only", Dropbox placeholders) are skipped, because reading them would download them.

## Private section

Romance, suggestive, nudity and sexual content is detected with the same care as faces: a recall-first ensemble of detectors, with doubtful items sent to you for review (blurred) rather than silently decided.

- **Lock:** a PIN or password of your choice, stored only as an Argon2id hash.
- **Encrypted at rest:** private thumbnails and previews are sealed with a public key. The engine can add new ones while locked, but they can only be decrypted after you unlock, because the private key is itself encrypted with a key derived from your PIN or password.
- **Hidden while locked:** private items don't appear in Photos, Search, People, Explore, Find and Move or slideshows, and the engine refuses to serve them. Searches show how many private matches are hidden, so nothing is missed.
- **After unlocking:** two toggles appear, *Blur* and *Show private items everywhere*.
- **Locks again automatically** after a period without activity (default 5 minutes), when Windows locks or sleeps, when the app closes, or instantly with **Ctrl+L**. Locking resets both toggles.
- **Forgot your PIN?** A reset wipes the private labels and encrypted thumbnails and re-runs detection. It never reveals anything.
- New photos are checked before they are shown; until then they appear blurred. Videos are checked frame by frame, and private content in any part of a video makes the whole video private.
- **Nothing readable of private items is kept:** words read in them and speech in them are deleted when they become private and aren't read or transcribed while private, and private videos never get a playable copy. If an item stops being private, it's read and listened to again.
- The *Sensitive* filter cannot be combined with child age groups.

**Limit:** the lock protects what RecPro shows and stores. Original files stay in their folders, so anyone signed in to your Windows account can still open them in File Explorer, unless you move them somewhere safer with Find and Move.

## ID documents

RecPro reads the words in documents, ID cards and screenshots on this PC (PaddleOCR) so you can search them and find ID documents: Aadhaar, PAN, passport, driving licence and voter ID.

- **Numbers are masked before anything is stored.** RecPro's text index keeps only the last 4 characters of an ID number (`XXXX XXXX 1234`) and of a passport's machine-readable lines. Any 12-digit number printed in groups of four is masked, even if one digit was misread. Your photos themselves are not changed.
- **Treat ID documents as private** (Settings → Private) moves photos RecPro is sure are ID documents, and ones you confirm, into Private, with their own *ID documents* tab. Ones it isn't sure about stay visible and wait in the ID category for you to check. Turning the setting off brings them back.
- Tests use synthetic numbers only (random digits with a valid checksum, and the ICAO specimen passport).
