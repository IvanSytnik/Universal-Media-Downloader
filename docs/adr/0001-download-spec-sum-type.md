# ADR 0001: DownloadSpec as a sum type with explicit columns

- Status: accepted
- Date: 2026-10-26
- Scope: Day 11C (v2), migration `0005_video_tier`

## Context

A download request carried two independent fields: `format_kind`
(video | audio) and `quality_kind` (`hd_720` | `hd_1080`). Every
combination was representable, including meaningless ones: an audio
request with a video quality, which the database stored as the default
and nothing read. Adding "best available" as a third tier, and keeping
the door open for an audio codec choice, would have multiplied the
combinations that code had to ignore.

Separately, Stage 0 diagnostics showed that "quality" itself was defined
wrongly: a height cap (`height<=720`) applied to the long side of
vertical video, so a 1080x1920 Short asked for at 720 arrived 360x640.

## Decision

1. The user's choice is a sum type in the domain:

   ```python
   DownloadSpec = VideoSpec | AudioSpec
   VideoSpec(tier: VideoTier)       # P720 | P1080 | BEST
   AudioSpec(codec: AudioCodec)     # MP3
   ```

   An audio spec cannot carry a tier; a video spec cannot lack one.
   `DEFAULT_DOWNLOAD_SPEC = VideoSpec(P720)`.

2. A tier means the video's **short side**. `VideoTier.short_side`
   (720, 1080, None for BEST) is the only tier → pixels mapping; the
   downloader turns it into yt-dlp's `res:` sort key (`res` is
   `min(width, height)`), the policy derives its thresholds from it, the
   callback codes are built from it.

3. Persistence uses explicit columns, not a serialized blob:
   `format_kind` (kept as the discriminator) and a nullable `video_tier`,
   tied by a CHECK constraint
   `(format_kind = 'video') = (video_tier IS NOT NULL)`. Reading is
   strict: `spec_from_parts` rejects any other combination, and the
   repository raises `CorruptedRecordError` (lesson 11C.3) instead of
   guessing.

4. The same two primitives cross the multiprocessing spawn boundary and
   are rebuilt in the child with the same `spec_from_parts`: one parser
   for the database and the process boundary.

## Migration `0005_video_tier`

- Adds `video_tier`; backfills `hd_1080` → `p1080`, any other video row →
  `p720`, audio rows → NULL; adds the CHECK; drops `quality_kind`; drops
  the `format_kind` server default (every writer sets it explicitly, and
  a default would let an INSERT without a spec silently become video).
- **Deploy order** (single host, pre-launch — no expand/contract): stop
  bot and worker → `alembic upgrade head` → start. Queued jobs do not need
  draining: they carry only a request id, and the row is migrated in
  place.
- **The downgrade is lossy**: `best` has no `quality_kind` equivalent and
  becomes `hd_720`. Accepted: `best` did not exist before this migration.

## Consequences

- Invalid combinations are unrepresentable in the domain and rejected by
  the database.
- A new tier is an enum member plus a label key; the picker, the
  callback codes and the policy pick it up by iteration.
- A new audio codec needs no migration (the codec is not persisted yet —
  MP3 is the only one; persisting it is a future column, same pattern).
- `QualityKind` and its column are gone; history rows keep their meaning
  through the backfill.
