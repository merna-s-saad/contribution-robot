# CHANGELOG

## 2026-09-04 — Initial build: generator, sprite, tests

### What changed
- `scripts/generate_robot_svg.py` (new). Fetches a GitHub contribution calendar
  over GraphQL, normalises it to a strict 53×7 grid, generates a deterministic
  wandering robot path, and emits a CSS-only animated SVG. CLI with
  `--username / --token / --out / --fixture`; caches the raw payload to
  `dist/last_fetch.json` on every live run; prints the byte size at the end.
- `scripts/robot_sprite.py` (new). Six `<symbol>` poses — `robot-stand`,
  `robot-step`, `robot-grab` plus a simplified `robot-mini` family — and
  `robot_use()`. Colours reference CSS custom properties only.
- `tests/` (new). 43 pytest tests plus a synthetic 53-week fixture with
  deliberately partial first and last weeks.
- `requirements.txt`, `.gitignore` (new).
- `CONTEXT.md`, `CODEMAP.md`, `TESTING.md`, `DEPENDENCIES.md`, `HANDOFF.md` (new).

### Decisions
- **Per-element `@keyframes` instead of shared keyframes + `animation-delay`**
  for cells, counter values and sprite poses. With infinite iteration all
  durations must match, which makes a delay a rigid timeline shift and a common
  reset instant impossible. Particles keep the shared-keyframes + delay
  approach, where it genuinely works. Raised before implementation, approved.
- **Mini sprite family extended to three poses.** The brief named one
  `robot-mini` but also asked for stand/step alternation and a grab pose during
  the walk; one symbol cannot do both. The detailed trio is unchanged.
- Both `href` and `xlink:href` emitted on `<use>` for viewer compatibility.

### Bugs found and fixed
- Collected cells rendered **black**: `fill: inherit` in the cell keyframes took
  the parent group's fill, not the level class. Keyframes now name the idle
  colour explicitly. Invisible to the tests; found by screenshotting.
- Path was a **pure left-to-right sweep** — the drift bonus always beat the
  contribution scores. Replaced with a pacing gate.
- Second attempt **reached the right edge at step 61**, exhausted the last
  column, and ended stranded at column 34. Same gate fixed it.
- Counter number **overlapped** its `commits collected` label (`COUNTER_NUM_DX`
  92 → 108).

### Verification
`ruff check` clean. 43/43 tests pass. Rendered from the fixture at 73.4 KB
(budget 150 KB) and verified in headless Chrome at five seeked timestamps —
exactly one counter value and one sprite pose opaque at each, collected counts
and robot transforms matching the timeline, mirrored pose confirmed.

### Known issues
- The live API path has never made a real request (no token this session).
- No automated visual regression; both render bugs above were invisible to the
  test suite.

### Next priorities
1. Run once against the live API with a real token; commit the resulting
   `last_fetch.json` as the fixture.
2. GitHub Action to regenerate and commit the SVG on a schedule.
3. README with the embed snippet.
