# RecPro

**A private, offline photo and video organizer for Windows.** Point it at your folders and pick a person: RecPro finds every photo and video they appear in, asks you when it isn't sure, copies the matches wherever you want, checks every copy byte for byte, and only then offers to remove the originals.

Nothing leaves your PC. Faces, photos, videos and text are analyzed on this computer only.

## What it does

| | |
|---|---|
| **Find someone** | Choose a person from People, type their name, or drop a photo of them. Matches come back in three tiers: *Sure*, *Please check*, and *No*. You only confirm the doubtful ones. |
| **Never miss** | When the AI isn't sure, it asks ("Is this Rohit?") instead of guessing. Every answer re-scores similar photos and makes RecPro better for you. |
| **Copy and move safely** | Copy → verify (BLAKE3 checksum of every file) → ask → move originals to the RecPro Bin. Everything can be undone; only *Empty bin* deletes permanently. |
| **Private section** | Romance, suggestive and nudity content is detected with the same ask-when-unsure care as faces, kept in a PIN- or password-locked, blurred Private section. After you unlock, toggles let you turn blur off or show private items everywhere; it locks itself again automatically. |
| **Search by anything** | Activities, moods, objects, pets, documents and IDs (Aadhaar, PAN, passport, driving licence, voter ID), screenshots by app, text inside images, speech in videos, places and dates. *(see [Roadmap](docs/ROADMAP.md) for what's built today)* |

## Status

RecPro is being built in milestones. See [docs/ROADMAP.md](docs/ROADMAP.md) for the current state of each one.

## Install

Download `RecPro-X.Y.Z-win-x64.exe` from the [latest release](https://github.com/buildcool/RecPro/releases/latest) and run it (Windows 10/11, 64-bit; it installs for your user, in a folder you choose). On first start RecPro asks for its data folder and downloads its AI models once. On a PC with an NVIDIA graphics card it also offers the GPU pack (about 1.2 GB) so the AI runs on the card. After that it works offline, and it updates itself from GitHub releases (Settings → Updates).

## Quick start (development)

Requirements: Windows 10/11, [Node.js 20.19+](https://nodejs.org), [uv](https://docs.astral.sh/uv/) (installs Python 3.12 for you), [ffmpeg](https://ffmpeg.org) on `PATH`. An NVIDIA GPU is recommended for recognition but not required.

```bash
npm install
cd engine && uv sync && cd ..
npm run dev
```

`npm run dev` starts the UI dev server, builds the desktop shell, and opens the Electron window, which starts the local engine. Development data goes to `.devdata/` in the repository.

More in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Project layout

```
desktop/   Electron shell: window, engine launcher, private media protocol, native dialogs, drag-out
ui/        React + TypeScript + Vite + Tailwind interface
engine/    Python engine (FastAPI on 127.0.0.1): library, indexing, AI, search, safe file operations
scripts/   Dev helpers (launcher, samples) and release tools (engine freezing, smoke test, versions)
docs/      Architecture, privacy model, development guide, roadmap
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md): how the pieces fit, the indexing pipeline, data model and file-operation guarantees
- [Privacy](docs/PRIVACY.md): what stays on your PC, what is stored where, and how Private is protected
- [Development](docs/DEVELOPMENT.md): setup, running, tests and commit conventions
- [Roadmap](docs/ROADMAP.md): milestones and their status
- [Changelog](CHANGELOG.md)

## Licenses of AI models

RecPro is built for personal use with the most accurate models available. Some of them have restrictive licenses: the InsightFace recognition weights are non-commercial, and NudeNet and Ultralytics YOLO are AGPL-3.0. Before distributing RecPro commercially, swap them for a commercial-safe set (YuNet/SFace/AuraFace, RF-DETR, …). Models are downloaded once, on request, and checked against SHA-256 hashes.
