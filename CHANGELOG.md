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
