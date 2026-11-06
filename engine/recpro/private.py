"""Private section: PIN/password lock, encrypted thumbnails, visibility toggles, auto re-lock.

* The PIN or password is stored only as an Argon2id hash.
* Thumbnails/previews of private items are sealed with a public key (X25519 sealed boxes):
  the engine can add new ones while locked, but only decrypt them after you unlock, because
  the private key is itself encrypted with a key derived from your PIN or password.
* Unlocking is in memory only: restarting the app, Windows locking, inactivity or Ctrl+L
  lock it again and reset the two visibility toggles.
"""
from __future__ import annotations

import base64
import logging
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from .context import Context

log = logging.getLogger("recpro.private")

K_HASH, K_KIND, K_SALT, K_PUB, K_SEALED = "private.hash", "private.kind", "private.salt", "private.pub", "private.sealed_sk"


class Private:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.db = ctx.db
        self._lock = threading.RLock()
        self._sk = None  # nacl PrivateKey while unlocked
        self._blur = True
        self._everywhere = False
        self._last_activity = 0.0
        self._fails: list[float] = []
        self._stop = threading.Event()
        self.dir = ctx.paths.private

    # ---- raw settings storage (not user-editable settings) -----------------------------
    def _get(self, key: str) -> str | None:
        return self.db.scalar("SELECT value FROM settings WHERE key=?", (key,))

    def _set(self, c, key: str, value: str) -> None:
        c.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    # ---- lifecycle -------------------------------------------------------------------------
    def start(self) -> None:
        threading.Thread(target=self._autolock_loop, name="private-autolock", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self.lock(publish=False)

    def _autolock_loop(self) -> None:
        while not self._stop.wait(5.0):
            if self.is_unlocked():
                minutes = float(self.ctx.settings.get("privacy.auto_lock_minutes", 5) or 5)
                if time.time() - self._last_activity > minutes * 60:
                    log.info("Private locked after %.0f minutes without activity", minutes)
                    self.lock()

    # ---- state -------------------------------------------------------------------------------
    def configured(self) -> bool:
        return bool(self._get(K_HASH))

    def is_unlocked(self) -> bool:
        return self._sk is not None

    def visible_everywhere(self) -> bool:
        return self.is_unlocked() and self._everywhere

    def blur_enabled(self) -> bool:
        return (not self.is_unlocked()) or self._blur

    def check_available(self) -> bool:
        ml = self.ctx.services.get("ml")
        return bool(ml and ml.has("nudenet") and self.ctx.settings.get("privacy.check_before_show", True))  # type: ignore[attr-defined]

    def state(self) -> dict[str, Any]:
        minutes = float(self.ctx.settings.get("privacy.auto_lock_minutes", 5) or 5)
        counts: dict[str, int] = {}
        labels = self.ctx.services.get("labels")
        if labels is not None:
            from .labels import SENSITIVE_KEYS

            for k in SENSITIVE_KEYS:
                try:
                    lid = labels.id(k)  # type: ignore[attr-defined]
                except KeyError:
                    continue
                counts[k.split(".", 1)[1]] = self.db.scalar(
                    """SELECT COUNT(*) FROM media_labels ml JOIN media m ON m.id=ml.media_id
                       WHERE ml.label_id=? AND m.state='active' AND m.sens_state IN ('private','review')
                       AND ml.state != 'rejected' AND (ml.tier='sure' OR ml.state='confirmed')""",
                    (lid,),
                    default=0,
                )
            if labels.ids_private():  # type: ignore[attr-defined]
                counts["ids"] = self.db.scalar(
                    """SELECT COUNT(DISTINCT m.id) FROM media_labels ml JOIN labels l ON l.id=ml.label_id JOIN media m ON m.id=ml.media_id
                       WHERE l.grp='id' AND m.state='active' AND m.sens_state='private'
                       AND ml.state != 'rejected' AND (ml.tier='sure' OR ml.state='confirmed')""",
                    default=0,
                )
        counts["review"] = self.db.scalar("SELECT COUNT(*) FROM media WHERE state='active' AND sens_state='review'", default=0)
        counts["total"] = self.db.scalar("SELECT COUNT(*) FROM media WHERE state='active' AND sens_state IN ('private','review')", default=0)
        return {
            "configured": self.configured(),
            "kind": self._get(K_KIND),
            "unlocked": self.is_unlocked(),
            "blur": self.blur_enabled(),
            "showEverywhere": self.visible_everywhere(),
            "expiresAt": (self._last_activity + minutes * 60) if self.is_unlocked() else None,
            "autoLockMinutes": minutes,
            "counts": counts,
        }

    def _publish(self) -> None:
        self.ctx.events.publish("private.state", self.state())

    # ---- PIN / password ----------------------------------------------------------------------
    @staticmethod
    def _derive(secret: str, salt: bytes) -> bytes:
        from argon2.low_level import Type, hash_secret_raw

        return hash_secret_raw(secret.encode("utf-8"), salt, time_cost=3, memory_cost=64 * 1024, parallelism=2, hash_len=32, type=Type.ID)

    def setup(self, secret: str, kind: str) -> dict[str, Any]:
        from argon2 import PasswordHasher
        from nacl.public import PrivateKey
        from nacl.secret import SecretBox

        if self.configured():
            raise PermissionError("Private is already set up.")
        if kind not in ("pin", "password"):
            raise ValueError("Choose a PIN or a password.")
        if kind == "pin" and not (secret.isdigit() and 4 <= len(secret) <= 8):
            raise ValueError("A PIN has 4 to 8 digits.")
        if kind == "password" and len(secret) < 6:
            raise ValueError("Use at least 6 characters.")
        salt = os.urandom(16)
        sk = PrivateKey.generate()
        sealed = SecretBox(self._derive(secret, salt)).encrypt(bytes(sk))
        with self.db.tx() as c:
            self._set(c, K_HASH, PasswordHasher().hash(secret))
            self._set(c, K_KIND, kind)
            self._set(c, K_SALT, base64.b64encode(salt).decode())
            self._set(c, K_PUB, base64.b64encode(bytes(sk.public_key)).decode())
            self._set(c, K_SEALED, base64.b64encode(bytes(sealed)).decode())
        with self._lock:
            self._sk = sk
            self._blur = bool(self.ctx.settings.get("privacy.blur_default", True))
            self._everywhere = False
            self._last_activity = time.time()
        self._publish()
        return self.state()

    def unlock(self, secret: str) -> dict[str, Any]:
        from argon2 import PasswordHasher
        from argon2.exceptions import VerifyMismatchError
        from nacl.public import PrivateKey
        from nacl.secret import SecretBox

        if not self.configured():
            raise LookupError("Private isn't set up yet.")
        now = time.time()
        self._fails = [t for t in self._fails if now - t < 300]
        if len(self._fails) >= 5 and now - self._fails[-1] < 30:
            raise TimeoutError("Too many tries. Wait 30 seconds and try again.")
        try:
            PasswordHasher().verify(self._get(K_HASH) or "", secret)
        except VerifyMismatchError:
            self._fails.append(now)
            raise PermissionError("Wrong PIN or password.")
        salt = base64.b64decode(self._get(K_SALT) or "")
        sealed = base64.b64decode(self._get(K_SEALED) or "")
        sk = PrivateKey(SecretBox(self._derive(secret, salt)).decrypt(sealed))
        with self._lock:
            self._sk = sk
            self._blur = bool(self.ctx.settings.get("privacy.blur_default", True))
            self._everywhere = False
            self._last_activity = time.time()
            self._fails.clear()
        self._publish()
        return self.state()

    def lock(self, publish: bool = True) -> None:
        with self._lock:
            was = self._sk is not None
            self._sk = None
            self._blur = True
            self._everywhere = False
        if publish and was:
            self._publish()

    def activity(self) -> None:
        if self.is_unlocked():
            self._last_activity = time.time()

    def set_toggles(self, blur: bool | None, everywhere: bool | None) -> dict[str, Any]:
        if not self.is_unlocked():
            raise PermissionError("Unlock Private first.")
        with self._lock:
            if blur is not None:
                self._blur = bool(blur)
            if everywhere is not None:
                self._everywhere = bool(everywhere)
            self._last_activity = time.time()
        self._publish()
        return self.state()

    def reset(self) -> None:
        """Forgot the PIN: forget the lock, private labels and encrypted images; check again."""
        from .labels import SENSITIVE_KEYS

        self.lock(publish=False)
        labels = self.ctx.services.get("labels")
        ids = [labels.id(k) for k in SENSITIVE_KEYS] if labels else []  # type: ignore[attr-defined]
        with self.db.tx() as c:
            for k in (K_HASH, K_KIND, K_SALT, K_PUB, K_SEALED):
                c.execute("DELETE FROM settings WHERE key=?", (k,))
            if ids:
                c.execute(f"DELETE FROM media_labels WHERE label_id IN ({','.join('?' * len(ids))})", ids)
            c.execute("UPDATE media SET sens_state='unchecked', sens_score=NULL, sens_v=0, sem_v=0 WHERE sens_state IN ('private','review')")
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True, exist_ok=True)
        ix = self.ctx.services.get("indexer")
        if ix is not None:
            ix.wake()  # type: ignore[attr-defined]
        self._publish()

    # ---- encrypted cache -----------------------------------------------------------------------
    def _path(self, kind: str, media_id: int) -> Path:
        return self.dir / f"{media_id // 1000:04d}" / f"{media_id}.{kind}.bin"

    def _pub(self):
        from nacl.public import PublicKey

        p = self._get(K_PUB)
        return PublicKey(base64.b64decode(p)) if p else None

    def read_cached(self, kind: str, media_id: int) -> bytes | None:
        if not self.is_unlocked():
            return None
        from nacl.public import SealedBox

        p = self._path(kind, media_id)
        if p.exists():
            try:
                return SealedBox(self._sk).decrypt(p.read_bytes())
            except Exception:
                p.unlink(missing_ok=True)
        if kind == "thumb":
            return self._make_thumb(media_id)
        return None

    def store_cached(self, kind: str, media_id: int, img) -> bytes:
        from .library.imaging import PREVIEW_MAX, THUMB_MAX, webp_bytes

        data = webp_bytes(img, THUMB_MAX if kind == "thumb" else PREVIEW_MAX, 80 if kind == "thumb" else 86)
        pub = self._pub()
        if pub is not None:
            from nacl.public import SealedBox

            p = self._path(kind, media_id)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(SealedBox(pub).encrypt(data))
        return data

    def _make_thumb(self, media_id: int) -> bytes | None:
        from .library.imaging import THUMB_MAX, open_image, video_frame

        r = self.db.q1("SELECT path, kind, duration FROM media WHERE id=?", (media_id,))
        if r is None:
            return None
        try:
            if r["kind"] == "image":
                raw, img, _ = open_image(r["path"], want=THUMB_MAX * 2)
                raw.close()
            else:
                d = r["duration"] or 0
                img = video_frame(r["path"], min(3.0, d * 0.1) if d else 0.0, max_side=THUMB_MAX * 2)
        except Exception:
            return None
        return self.store_cached("thumb", media_id, img)

    def on_became_private(self, media_ids: list[int]) -> None:
        """No readable copy of a private item stays in the data folder."""
        from .library.imaging import shard

        playable = self.ctx.services.get("playable")
        if playable is not None:
            playable.forget(media_ids)  # type: ignore[attr-defined]

        for mid in media_ids:
            for base in (self.ctx.paths.thumbs, self.ctx.paths.previews):
                try:
                    shard(base, mid).unlink(missing_ok=True)
                except OSError:
                    pass
            for f in self.db.q("SELECT id FROM faces WHERE media_id=?", (mid,)):
                for p in (self.ctx.paths.faces / f"{f['id'] // 1000:04d}").glob(f"{f['id']}_*.webp"):
                    try:
                        p.unlink()
                    except OSError:
                        pass

    def on_became_clear(self, media_ids: list[int]) -> None:
        for mid in media_ids:
            for kind in ("thumb", "preview"):
                self._path(kind, mid).unlink(missing_ok=True)
        # recreate a normal thumbnail
        with self.db.tx() as c:
            c.executemany("UPDATE media SET quick_v=0 WHERE id=?", [(m,) for m in media_ids])
        ix = self.ctx.services.get("indexer")
        if ix is not None:
            ix.wake()  # type: ignore[attr-defined]


def create(ctx: Context) -> Private:
    return Private(ctx)
