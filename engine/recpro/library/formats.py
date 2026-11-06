from __future__ import annotations

IMAGE_EXT = {
    ".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".webp", ".heic", ".heif", ".avif",
    ".bmp", ".gif", ".tif", ".tiff",
}
VIDEO_EXT = {
    ".mp4", ".mov", ".m4v", ".mkv", ".avi", ".3gp", ".3g2", ".webm", ".wmv",
    ".mts", ".m2ts", ".mpg", ".mpeg", ".flv",
}

# Folder names never scanned (system, app internals, our own bin).
SKIP_DIRS = {
    "$recycle.bin", "system volume information", ".recpro-bin", "node_modules", ".git",
    "__pycache__", "appdata", ".thumbnails", ".trash", ".trashes", "windows", "program files",
    "program files (x86)", "programdata", "$windows.~bt", "$windows.~ws", "msocache",
}

# Windows file attributes that mean "the bytes live in the cloud" (OneDrive, Dropbox…).
# Reading such a file would make the sync client download it, so we skip it.
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_ONLY_MASK = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4


def kind_for(ext: str) -> str | None:
    e = ext.lower()
    if e in IMAGE_EXT:
        return "image"
    if e in VIDEO_EXT:
        return "video"
    return None
