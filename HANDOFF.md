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

## Wordmark mode is in but not wired into anything

`--word MERNA` works and is tested, but the daily workflow does not generate it.
If you want both SVGs on the `output` branch, add a second render step before
the publish step:

```yaml
- name: Render the wordmark
  run: python scripts/generate_robot_svg.py --username merna-s-saad
       --word MERNA --out dist/wordmark-robot.svg
```

It needs no token, so it cannot fail the way the API step can.

## Next priorities

1. **Trigger the workflow by hand** from the Actions tab (`workflow_dispatch`)
   and watch it. This is the first time the live API path will ever have run,
   so failures are likeliest here: a `CONTRIBUTION_TOKEN` without `read:user`
   fails at the render step with exit 3, and the publish step needs the `output`
   branch to be creatable (it does not exist yet — the action creates it).
2. **Real fixture.** Once a run succeeds, pull `last_fetch.json` off the
   `output` branch and replace `tests/fixtures/sample_calendar.json` with it.
   Confirm the real calendar's shape first (GitHub sometimes returns 54 weeks —
   the trim path is tested but unexercised in anger), then re-read
   `test_path_wanders_rather_than_sweeping`, whose thresholds are tuned to the
   synthetic fixture.
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
