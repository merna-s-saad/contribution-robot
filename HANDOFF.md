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

## Next priorities

1. **Live run.** `export GITHUB_TOKEN=...` then run without `--fixture`.
   Confirm the real calendar's shape (GitHub sometimes returns 54 weeks — the
   trim path is tested but unexercised in anger) and replace
   `tests/fixtures/sample_calendar.json` with the real `dist/last_fetch.json`.
   Then re-read `test_path_wanders_rather_than_sweeping`, whose thresholds are
   tuned to the synthetic fixture.
2. **GitHub Action** on a daily cron to regenerate and commit the SVG.
3. **README** with the embed snippet and a preview.
4. Optional: drop the three detailed sprite symbols from `<defs>` (~2 KB) if the
   size budget ever tightens — nothing references them at runtime.

## Watch out for

- Headless Chrome's `--virtual-time-budget` does **not** advance the CSS
  animation clock; screenshots taken that way show t≈0 and look broken. Seek
  with `document.getAnimations()` instead. Full recipe in CONTEXT.md.
- The lint hook blocks on ruff failures, including `EXE001` — a file with a
  shebang must be `chmod +x`.
