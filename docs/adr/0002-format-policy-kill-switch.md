# ADR 0002: FormatPolicy — per-extractor format kill-switch enforced in UI and use case

- Status: accepted
- Date: 2026-10-26
- Scope: Day 11C (v2)

## Context

We need to switch a format off for one source without a deploy — e.g.
stop offering MP3 for YouTube — and to decide per source whether a
quality choice is worth asking about at all (TikTok's inline-playable
h264 tops out at 720p; offering "1080p" there would download h265 or
nothing better).

Buttons alone cannot enforce anything: a card rendered before the switch
was flipped stays in the chat, and callback data can be forged. A check
only in the use case, on the other hand, would show users buttons that
are guaranteed to fail.

## Decision

1. One application-layer class, `FormatPolicy`, built from configuration
   (`DISABLED_FORMATS`, e.g. `{"youtube": ["audio"]}`), keyed by the
   lowercased yt-dlp `extractor_key`, with two readers:
   - `is_allowed(extractor_key, spec)` — **enforcement**, called by
     `RequestDownloadUseCase` before anything is persisted; a refusal is
     `FormatNotAllowedError` (`error-format-not-allowed`).
   - `offered_choices(extractor_key, max_compatible_short_side)` —
     **presentation hint**: which of video / MP3 to show and which video
     tiers, if any.
   - `default_video_spec(preview)` — the spec for paths without buttons
     (`/download`): what the video button would download.

2. The extractor and short side come from the preview and are stored
   with the URL (`PreviewContext`). Handlers read them from the store,
   never from callback data. `q:` / `back:` re-render the keyboard from
   the stored context and the *current* policy on every tap, so a flipped
   switch shows on the next tap; `dl:` goes through the use case, so a
   stale or forged button is refused.

3. Quality step thresholds derive from `VideoTier.short_side`:
   unknown or ≤ 720 → no step, video downloads `VideoSpec(BEST)`;
   721–1079 → `[720p][<N>p (best)]`; ≥ 1080 → `[720p][1080p]`.

4. No re-check in the worker (YAGNI): the policy is enforced once, when
   a request is created.

## Consequences

- The UI and enforcement cannot disagree: one rule set, two readers.
- The switch is per extractor, and therefore cannot tell apart sources
  that share an extractor: YouTube Music is extracted as `youtube`. URL
  level exclusions belong to `BLOCKED_DOMAINS`, not to this policy.
- `/download` needs a preview (the extractor is only known after
  extraction), so it now runs yt-dlp in the bot process — guarded by the
  allowlist first.
- Changing `DISABLED_FORMATS` needs a bot restart (settings are read at
  startup).
