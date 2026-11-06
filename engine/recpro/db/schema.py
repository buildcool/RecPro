"""SQLite schema. Each entry in MIGRATIONS runs once, in order."""

MIGRATIONS: list[str] = [
    # v1 — core library, people, labels, operations
    """
    CREATE TABLE IF NOT EXISTS settings(
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );

    CREATE TABLE folders(
      id INTEGER PRIMARY KEY,
      path TEXT NOT NULL UNIQUE,
      recursive INTEGER NOT NULL DEFAULT 1,
      watch INTEGER NOT NULL DEFAULT 1,
      excluded TEXT NOT NULL DEFAULT '[]',
      added_at REAL NOT NULL,
      last_scan_at REAL,
      status TEXT NOT NULL DEFAULT 'pending',
      file_count INTEGER NOT NULL DEFAULT 0,
      skipped_cloud INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE media(
      id INTEGER PRIMARY KEY,
      folder_id INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
      path TEXT NOT NULL UNIQUE,
      rel_dir TEXT NOT NULL,
      name TEXT NOT NULL,
      ext TEXT NOT NULL,
      kind TEXT NOT NULL,
      size INTEGER NOT NULL,
      mtime REAL NOT NULL,
      quick_hash TEXT,
      content_hash TEXT,
      width INTEGER,
      height INTEGER,
      duration REAL,
      vcodec TEXT,
      taken_at REAL,
      taken_src TEXT,
      gps_lat REAL,
      gps_lon REAL,
      camera TEXT,
      phash INTEGER,
      has_exif_camera INTEGER NOT NULL DEFAULT 0,
      state TEXT NOT NULL DEFAULT 'active',
      quick_v INTEGER NOT NULL DEFAULT 0,
      sens_v INTEGER NOT NULL DEFAULT 0,
      deep_v INTEGER NOT NULL DEFAULT 0,
      text_v INTEGER NOT NULL DEFAULT 0,
      video_v INTEGER NOT NULL DEFAULT 0,
      sens_state TEXT NOT NULL DEFAULT 'unchecked',
      sens_score REAL,
      face_count INTEGER NOT NULL DEFAULT 0,
      error TEXT,
      added_at REAL NOT NULL
    );
    CREATE INDEX media_folder ON media(folder_id, rel_dir);
    CREATE INDEX media_taken ON media(taken_at);
    CREATE INDEX media_quick_hash ON media(quick_hash);
    CREATE INDEX media_content_hash ON media(content_hash);
    CREATE INDEX media_state ON media(state);

    CREATE TABLE people(
      id INTEGER PRIMARY KEY,
      name TEXT,
      kind TEXT NOT NULL DEFAULT 'human',
      birthdate TEXT,
      hidden INTEGER NOT NULL DEFAULT 0,
      cover_face_id INTEGER,
      created_at REAL NOT NULL,
      updated_at REAL NOT NULL
    );
    CREATE INDEX people_name ON people(name);

    CREATE TABLE faces(
      id INTEGER PRIMARY KEY,
      media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
      frame_ms INTEGER,
      track_id INTEGER,
      x1 REAL NOT NULL, y1 REAL NOT NULL, x2 REAL NOT NULL, y2 REAL NOT NULL,
      landmarks BLOB,
      det_score REAL NOT NULL,
      quality REAL NOT NULL,
      embedding BLOB NOT NULL,
      age REAL,
      male REAL,
      emotion TEXT,
      emotion_score REAL,
      person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
      state TEXT NOT NULL DEFAULT 'none',
      score REAL
    );
    CREATE INDEX faces_media ON faces(media_id);
    CREATE INDEX faces_person ON faces(person_id, state);

    CREATE TABLE face_votes(
      face_id INTEGER NOT NULL REFERENCES faces(id) ON DELETE CASCADE,
      person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
      vote INTEGER NOT NULL,
      at REAL NOT NULL,
      PRIMARY KEY(face_id, person_id)
    );

    CREATE TABLE ref_faces(
      id INTEGER PRIMARY KEY,
      person_id INTEGER REFERENCES people(id) ON DELETE CASCADE,
      source_path TEXT,
      embedding BLOB NOT NULL,
      quality REAL NOT NULL,
      created_at REAL NOT NULL
    );

    CREATE TABLE labels(
      id INTEGER PRIMARY KEY,
      key TEXT NOT NULL UNIQUE,
      name TEXT NOT NULL,
      grp TEXT NOT NULL,
      prompts TEXT,
      negatives TEXT,
      sure_thr REAL,
      check_thr REAL,
      builtin INTEGER NOT NULL DEFAULT 1,
      enabled INTEGER NOT NULL DEFAULT 1,
      version INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE media_labels(
      media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
      label_id INTEGER NOT NULL REFERENCES labels(id) ON DELETE CASCADE,
      score REAL NOT NULL,
      tier TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'ai',
      source TEXT,
      t_start_ms INTEGER,
      t_end_ms INTEGER,
      PRIMARY KEY(media_id, label_id)
    );
    CREATE INDEX media_labels_label ON media_labels(label_id, tier);

    CREATE TABLE embeddings(
      media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
      model TEXT NOT NULL,
      frame_ms INTEGER NOT NULL DEFAULT -1,
      vec BLOB NOT NULL,
      PRIMARY KEY(media_id, model, frame_ms)
    );

    CREATE VIRTUAL TABLE texts USING fts5(media_id UNINDEXED, kind UNINDEXED, content, tokenize='trigram');

    CREATE TABLE operations(
      id INTEGER PRIMARY KEY,
      kind TEXT NOT NULL,
      status TEXT NOT NULL,
      title TEXT,
      dest TEXT,
      structure TEXT,
      conflict TEXT,
      removal TEXT,
      parent_id INTEGER,
      created_at REAL NOT NULL,
      finished_at REAL,
      total INTEGER NOT NULL DEFAULT 0,
      done INTEGER NOT NULL DEFAULT 0,
      failed INTEGER NOT NULL DEFAULT 0,
      bytes_total INTEGER NOT NULL DEFAULT 0,
      bytes_done INTEGER NOT NULL DEFAULT 0,
      error TEXT
    );

    CREATE TABLE op_items(
      id INTEGER PRIMARY KEY,
      op_id INTEGER NOT NULL REFERENCES operations(id) ON DELETE CASCADE,
      media_id INTEGER,
      src TEXT NOT NULL,
      dst TEXT,
      size INTEGER,
      src_mtime REAL,
      hash TEXT,
      state TEXT NOT NULL DEFAULT 'pending',
      removed_to TEXT,
      error TEXT
    );
    CREATE INDEX op_items_op ON op_items(op_id, state);
    """,
    # v2 — answers to "Same person?" questions
    """
    CREATE TABLE person_pairs(
      a INTEGER NOT NULL,
      b INTEGER NOT NULL,
      same INTEGER NOT NULL,
      at REAL NOT NULL,
      PRIMARY KEY(a, b)
    );
    CREATE INDEX faces_state ON faces(state);
    """,
    # v3 — semantic (SigLIP) stage version and private-state index
    """
    ALTER TABLE media ADD COLUMN sem_v INTEGER NOT NULL DEFAULT 0;
    CREATE INDEX media_sens ON media(sens_state);
    """,
    # v4 — videos: when each face (one per person per video) is on screen, and when a category or
    # private content is
    """
    CREATE TABLE face_spans(
      face_id INTEGER NOT NULL REFERENCES faces(id) ON DELETE CASCADE,
      start_ms INTEGER NOT NULL,
      end_ms INTEGER NOT NULL
    );
    CREATE INDEX face_spans_face ON face_spans(face_id);
    CREATE TABLE label_spans(
      media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
      label_id INTEGER NOT NULL REFERENCES labels(id) ON DELETE CASCADE,
      start_ms INTEGER NOT NULL,
      end_ms INTEGER NOT NULL,
      score REAL NOT NULL
    );
    CREATE INDEX label_spans_media ON label_spans(media_id, label_id);
    """,
    # v5 — what is said in videos, with times (trigram search in any script)
    """
    ALTER TABLE media ADD COLUMN speech_v INTEGER NOT NULL DEFAULT 0;
    CREATE VIRTUAL TABLE speech USING fts5(media_id UNINDEXED, start_ms UNINDEXED, end_ms UNINDEXED, lang UNINDEXED, content, tokenize='trigram');
    """,
]
