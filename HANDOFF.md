# HANDOFF

updated-at: 2026-09-04

## Where we left off

The generator is complete, linted, tested and visually verified from a fixture.
Nothing is half-finished in the working tree.

```bash
.venv/bin/python scripts/generate_robot_svg.py --username merna-s-saad \
  --fixture tests/fixtures/sample_calendar.json --out dist/contribution-robot.svg
# wrote dist/contribution-robot.svg (75,183 bytes, 73.4 KB)
```

## Done this session

- Designed and built `scripts/generate_robot_svg.py` and
  `scripts/robot_sprite.py` (see CHANGELOG.md for the full list).
- 43 tests + synthetic fixture; ruff clean.
- Four bugs found and fixed, two of them only visible in a browser render.
- Wrote CONTEXT.md, CODEMAP.md, TESTING.md, DEPENDENCIES.md, CHANGELOG.md.

## Decisions taken (don't re-litigate)

- Per-element keyframes for cells / counter / poses; shared keyframes +
  `animation-delay` for particles only. Reasoning in CONTEXT.md.
- Mini sprite family extended from one symbol to three poses.
- Path length is targeted via a pacing gate (`MIN_CELLS = 78`), and the step
  duration is derived so the run is always exactly 22s.

## Blockers

None. One thing is simply unavailable: no `GITHUB_TOKEN` was present, so the
live fetch has never actually run.

## Both SVGs are published daily

The workflow renders the contribution SVG and then the wordmark, and publishes
`dist/` to `output`. The wordmark step needs no token, so it cannot fail the way
the API step can — and it runs after the API step, so a token failure still
fails the run before anything is published.

The wordmark is **regenerated every run rather than committed once**, even
though its letters never change. `build_word_grid` stamps cells with today's
date, so its month labels track the calendar exactly like the contribution
SVG's. A committed copy would freeze those labels and drift out of step within
weeks, defeating the reason the labels are kept.

`keep_files: true` is set on the publish step. Without it,
`peaceiris/actions-gh-pages` deletes anything on `output` that is not in
`dist/` on that run — so a file added to that branch by hand would disappear on
the next cron. Note the trade: nothing on `output` is ever cleaned up now, so a
renamed output file would leave its old name behind.

## Current pacing (measured, real calendar)

| | |
|---|---|
| start column | 23, from the density rule capped by `MIN_SPAN_COLS` |
| outbound | 64 cells, **0.306s/step**, 22.00s fixed |
| turn | 0.60s, facing flips mid-pause |
| return | 30 cells, **0.204s/step** (1.50× brisker), 6.91s |
| total cycle | **30.51s** (ceiling 35s) |

`CELLS_PER_COLUMN = 2.24` is the only pace lever. The step is `22s / units`,
not `22s / cells`, and a dwell costs three units — so don't reason from the
cell count alone. Don't reason from the fixture either: it gives 0.169s where
the real calendar gives 0.306s.

## Next priorities

1. **Replace the synthetic fixture with the real payload.** The workflow has
   run successfully several times, so `last_fetch.json` on `output` is real
   data (374 contributions) — pull it down and swap it for
   `tests/fixtures/sample_calendar.json`. The two disagree in ways that matter:
   the synthetic one has commits from column 0 and gives a 0.169s step, the
   real one starts at column 25 and gives 0.306s. Several path-shape tests are
   tuned to the synthetic shape and will need re-reading, notably
   `test_path_wanders_rather_than_sweeping`.
3. **README** with the embed snippet pointing at the raw URL on `output`, e.g.
   `https://raw.githubusercontent.com/merna-s-saad/contribution-robot/output/contribution-robot.svg`.
4. Optional: drop the three detailed sprite symbols from `<defs>` (~2 KB) if the
   size budget ever tightens — nothing references them at runtime.

## Watch out for

- Headless Chrome's `--virtual-time-budget` does **not** advance the CSS
  animation clock; screenshots taken that way show t≈0 and look broken. Seek
  with `document.getAnimations()` instead. Full recipe in CONTEXT.md.
- The lint hook blocks on ruff failures, including `EXE001` — a file with a
  shebang must be `chmod +x`.
