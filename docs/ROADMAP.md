# Roadmap

Every feature area ships in this build, delivered as milestones. Status reflects the code on `dev`.

| # | Milestone | Status | Done when |
|---|---|---|---|
| M0 | **Scaffold**: repository, Electron shell, local engine with token auth, React UI shell, design system | Done | App opens; header shows *Local only*; navigation works |
| M1 | **Library**: folders, scanner/watcher, metadata, thumbnails, Photos grid, Viewer, Folders, Home · **safe file operations** (copy → verify → Bin → undo) + History | In progress: engine, Folders, Home, Settings and onboarding done; Photos grid, Viewer and History next | 10k-photo folder browsable in seconds; operation tests pass, including a crash mid-copy |
| M2 | **Faces and People**, **Review** inbox, learning, coverage meter, **Find and Move** wizard | Planned | Find a person across two folders → check doubts → copy → verify → remove to Bin → undo |
| M3 | **Private**: pre-check before showing, sensitive ensemble, blurred review, PIN/password lock, visibility toggles, encrypted private thumbnails, auto re-lock | Planned | Locked: private items never shown or served. Unlocked: both toggles work. Doubtful items always reach Review. |
| M4 | **Smart categories**: SigLIP 2 search and taxonomy, objects, age/gender/emotion, group size, named pets, custom categories, Ctrl+K universal search | Planned | "laptop on sofa" and "happy group at beach" return tiered results |
| M5 | **Text**: OCR (English + Hindi), text search, Aadhaar/PAN/passport/DL/voter ID, screenshots by app, number masking | Planned | Words inside images are searchable; ID and screenshot categories filled |
| M6 | **Video**: frame sampling, face tracks, per-person time segments, sensitive segments, preview proxies for HEVC, speech search, same-event suggestions for hidden faces | Planned | A video search jumps to exact timestamps |
| M7 | **Cleanup and discovery**: duplicates and bursts, blurry/dark, WhatsApp forwards and memes, places with an offline map, trips, On this day, saved searches, label export/import, XMP sidecars | Planned | Every cleanup goes through the same safe Bin |
| M8 | **Polish and ship**: tuning for 8 GB VRAM / 16 GB RAM, accessibility, error states, model downloader, Windows installer, offline verification | Planned | Installer works on a clean Windows account; everything works with the network off |

## Honest limits

- No AI can promise 100%. Faces that are turned away, masked or very blurry can't be identified reliably. RecPro surfaces them as *Please check*, with same-event suggestions, and the coverage meter shows what's left.
- Age, gender and emotion are estimates. A birthdate you enter gives exact ages.
- The Private lock protects RecPro's views and storage, not the original files in File Explorer.
