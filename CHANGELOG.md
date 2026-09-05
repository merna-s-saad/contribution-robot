# CHANGELOG

## 2026-09-05 — Publish the wordmark daily; fix its calendar span

### What changed
- `.github/workflows/generate.yml`: a second render step produces
  `dist/wordmark-robot.svg` with `--word MERNA`. It needs no token and runs
  after the API step, so a token failure still fails the run before anything
  publishes. Regenerated daily rather than committed once because its month
  labels track today's date.
- `keep_files: true` on the publish step. The action's default is `false`,
  which deletes anything on the publish branch not present in `publish_dir`
  on that run.

### Bug found and fixed
`build_word_grid` truncated the calendar at exactly 364 days, but GitHub
returns **whole weeks** — the first column starts on the Sunday on or before a
year ago and is complete, only the last column is partial. The real payload
spans 370 days, not 365. The truncation left column 0 with two cells and
shifted the first month label, so the published pair read `Sep Oct Nov ...`
against `Aug Oct Nov ...`. Caught by diffing the two SVGs actually on the
`output` branch, not by the test suite.

### Verification
`ruff check` clean, 95/95 tests pass. Checked against the real `last_fetch.json`
on `output`: spans identical (2025-08-31 → 2026-09-04, 370 days), all twelve
month labels identical, and the None-padding pattern identical cell for cell.
Two new tests lock the span rule and the cell-for-cell date parity.

## 2026-09-04 — Wordmark mode

### What changed
- `scripts/grid_font.py` (new). 5×7 bitmap font, A–Z plus space, `layout()`,
  `width()`. The five MERNA glyphs are exactly as specified.
- `--word MERNA` on the existing generator. Skips the GraphQL fetch, builds the
  grid from the font, centres the word, keeps the real trailing-12-month dates
  so the month and Mon/Wed/Fri labels match the contribution version, and keeps
  the same viewBox so the two stack as a matched pair. Counter and particles
  dropped.
- `RenderMode` carries the five things that differ between modes; the timeline,
  gait, pose segments, sprite and CSS layer are shared unchanged.
- `build_word_path`: a deterministic boustrophedon that reaches **all 88** glyph
  cells, 8-way connected, no repeats, no teleporting.
- `tests/test_wordmark.py` (new). 39 tests (55 → 94 total).

### Decisions
- **Robot lights the word up** rather than darkening it: letters start at
  `--empty`, collected brightens to `--l4`. Contribution mode's darkening
  behaviour would progressively erase the wordmark.
- **Dwell off in wordmark mode.** Uniform letter weights make the top-quartile
  rule select every cell, tripling units and halving the pace.
- **Full-height column sweeps.** Sweeping only each column's lit range reaches
  72/88 and then deadlocks; full-height sweeps make coverage structural.
- **Pace is 0.120s/step against contribution mode's 0.157s** — 1.3× brisker,
  the cost of guaranteeing 88/88. Reported rather than applied silently.
- Palette untouched, as instructed.

### Bugs found and fixed
- First serpentine attempt reached 72/88: BFS between two cells in the same
  column takes an equal-length diagonal detour *out* of the column, skipping
  the cells in between.
- Second attempt deadlocked entirely ("no unvisited route to column 13"): after
  a full sweep the robot is walled in by its own trail and can only leave via a
  single step from its current row.
- The finished word was never held — cells began fading at t=22.0, the instant
  the last one lit. `WORDMARK_MODE.reset_at` is now 23s.

### Verification
`ruff check` clean, 94/94 tests pass. `dist/contribution-robot.svg` is
byte-identical to before (sha256 `898304ba…`), so contribution mode is provably
untouched. Wordmark verified in headless Chrome by seeking the clock: 0/88 lit
at t=0, 45/88 at t=11s, **88/88 at t=22.1s and still 88/88 at t=22.9s**, back to
0 at t=23.8s. 62.7 KB.

## 2026-09-04 — Skip a dead lead-in; scale the pace to the active span

### What changed
- `scripts/generate_robot_svg.py`: new `first_active_column()`, `start_column()`
  and `target_cells()`. The walk now starts two columns before the first column
  with any contributions instead of at column 0, so a calendar with a long dead
  stretch at the start no longer spends most of the animation on empty cells.
- The pacing gate, the neighbour scan, `_has_escape()` and `_nearest_unvisited()`
  are all bounded at the start column, so nothing can drop the robot back into
  the dead region.
- Path length now scales with the active span (`CELLS_PER_COLUMN ≈ 1.472`,
  floored at 24 and capped at `span * 7`). Since the step duration is derived
  from a fixed 22s run, a shorter span yields a slower, more deliberate pace
  rather than a sprint followed by idling.
- `tests/fixtures/late_start_calendar.json` (new): same shape as the main
  fixture but dead until column 16.
- 12 new tests (43 → 55).

### Decisions
- `CELLS_PER_COLUMN` is derived as `MIN_CELLS / COLS` rather than picked, so a
  full-width calendar computes to exactly 78 cells and reproduces the previous
  behaviour byte for byte. Verified: `dist/contribution-robot.svg` from
  `sample_calendar.json` is unchanged (sha256 `898304ba…`).
- Floor of 24 cells: a three-column active region would otherwise collapse to
  ~4 cells and give single steps over five seconds long.
- Palette untouched, as instructed.

### Verification
`ruff check` clean, 55/55 tests pass. Both fixtures rendered and checked in
headless Chrome at seeked timestamps. The late-start render starts at column 14
(robot x≈286 at t=0.2s, not 48.5), the dead columns draw as ordinary cells with
no animation, and the counter runs 0 → 146 → 343 → 363. 63.0 KB.

## 2026-09-04 — Daily publishing workflow

### What changed
- `.github/workflows/generate.yml` (new). Regenerates the SVG on a daily cron
  (`0 8 * * *`), on `workflow_dispatch`, and on a push to `main` touching
  `scripts/**`. Publishes `dist/` to a dedicated `output` branch with
  `peaceiris/actions-gh-pages@v4`. 10 minute timeout, `contents: write`,
  `concurrency: {group: generate, cancel-in-progress: false}`.
- `dist/` untracked from `main` and returned to `.gitignore`, reverting the
  tracking added in `4bfca4f`. The output branch is the single home for
  generated files; keeping a copy on main defeated the point.
- `CONTEXT.md` gained an Automation section; `HANDOFF.md` next priorities
  rewritten around the workflow's first run.

### Decisions
- **No failure fallback.** The generator's exit codes (2/3/4) fail the render
  step, so the publish step never runs. A red run is better than silently
  publishing a stale or blank graphic.
- `last_fetch.json` is published alongside the SVG — public data, and it is the
  fixture format.
- Secrets: `CONTRIBUTION_TOKEN` (`read:user`) for the API call, built-in
  `GITHUB_TOKEN` for the publish step. Neither is committed anywhere.

### Known issues
- The workflow has never run. Its first execution is also the first time the
  live API path will have been exercised at all.

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
