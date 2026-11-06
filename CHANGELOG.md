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
