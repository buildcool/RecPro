export type Settings = Record<string, unknown> & {
  onboarded: boolean;
  theme: 'system' | 'light' | 'dark';
};

export type Health = {
  ok: boolean;
  version: string;
  dataDir: string;
  localOnly: boolean;
  strictOffline: boolean;
  gpu: { provider: string; name?: string; vramMb?: number; gpuPackNeeded?: boolean } | null;
  tools?: { ffmpeg: string | null; ffprobe: string | null };
};

export type Folder = {
  id: number;
  path: string;
  recursive: boolean;
  watch: boolean;
  status: 'pending' | 'scanning' | 'ready' | 'offline' | 'error';
  added_at: number;
  last_scan_at: number | null;
  file_count: number;
  photos: number;
  videos: number;
  bytes: number;
  skipped_cloud: number;
  online: boolean;
};

export type MediaItem = {
  id: number;
  kind: 'image' | 'video';
  w: number | null;
  h: number | null;
  t: number | null; // taken_at
  dur: number | null;
  faces: number;
  priv: boolean; // private (sensitive) and currently hidden/blurred
  chk: boolean; // sensitivity not checked yet
  v: number; // thumbnail version for cache busting
  err?: boolean; // file couldn't be read
  at_ms?: number; // videos: where the match is (Find, search)
  spans?: Moment[]; // videos: when the matched people or categories are on screen
};

/** A stretch of a video: a person on screen, a category, a matching scene. */
export type Moment = { person_id?: number | null; label_id?: number; name: string | null; start_ms: number; end_ms: number };

export type MediaDetail = {
  id: number;
  path: string;
  name: string;
  folder_id: number;
  folder_path: string;
  rel_dir: string;
  kind: 'image' | 'video';
  size: number;
  mtime: number;
  width: number | null;
  height: number | null;
  duration: number | null;
  vcodec: string | null;
  taken_at: number | null;
  taken_src: string | null;
  camera: string | null;
  gps_lat: number | null;
  gps_lon: number | null;
  state: string;
  sens_state: string;
  faces: FaceBox[];
  labels: MediaLabel[];
  text?: string | null;
  label_spans?: { label_id: number; name: string; start_ms: number; end_ms: number }[];
  speech?: { start_ms: number; end_ms: number; text: string }[]; // videos: what is said, when
};

export type FaceBox = {
  id: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  person_id: number | null;
  person_name: string | null;
  state: string;
  score: number | null;
  frame_ms: number | null;
  age: number | null;
  male: number | null;
  emotion: string | null;
  spans?: { start_ms: number; end_ms: number }[]; // videos: when this person is on screen
};

export type MediaLabel = {
  label_id: number;
  key: string;
  name: string;
  grp: string;
  score: number;
  tier: 'sure' | 'check' | 'no';
  state: 'ai' | 'confirmed' | 'rejected';
  t_start_ms: number | null;
  t_end_ms: number | null;
};

export type Stats = {
  photos: number;
  videos: number;
  bytes: number;
  folders: number;
  people: number;
  named_people: number;
  review: number;
  private_hidden: number;
};
