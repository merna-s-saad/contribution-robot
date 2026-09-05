# TESTING

updated-at: 2026-09-04

```bash
.venv/bin/python -m pytest tests/ -q      # 94 tests, ~0.2s
ruff check scripts/ tests/
```

No network is touched by any test. `requests` is imported lazily inside
`fetch_calendar`, so the suite runs with pytest alone.

## What is covered

| Area | Tests |
|---|---|
| Normalisation | 53×7 shape, partial first/last weeks padded not skipped, >53 weeks trimmed to the most recent, <53 padded left, all five levels produced |
| Path | no revisits, ends col 52, every step 8-way connected, wanders (backtracks + vertical moves + longer than a straight march), deterministic for a fixed seed |
| Start column | backs up exactly 2 from the first active column (parametrised over 0/1/2/3/14/30), empty grid falls back to column 0, walk never enters the dead region, dead columns still render as normal unanimated cells, shorter span → fewer cells at a slower base step, `target_cells` scales with the span and honours its floor, full-width calendars reproduce `MIN_CELLS` exactly, late-start render still meets the 20–25s / no-script / 150 KB / determinism budgets |
| Timing | run lands in 20–25s, slots contiguous and ordered, dwell slot is exactly 3× a normal slot and only on ≥75th-percentile cells |
| Pose timeline | segments tile the whole cycle with no overlap (so exactly one pose is ever visible), grab covers every dwell beat, facing flips on leftward travel |
| Sprite | all six symbols present, one shared viewBox, no hex literals, mini drops the chest panel and thickens strokes, mirror is in-place and never vertical, `robot_use` centres on its point |
| SVG | well-formed XML, viewBox with no width/height, no script/`javascript:`/`on*=`, title+desc+role, palette defined once as custom properties and no hex outside `<style>`, one animated rect per visited cell, counter is a strictly increasing stack, one particle per scoring cell, every animation shares the 24s duration, loops forever |
| CLI | fixture render writes no `last_fetch.json` and never calls the API, output under 150 KB, missing token → exit 2 with a readable message, missing fixture → exit 4, bad API payloads raise, empty calendar rejected, a zero-contribution year still renders |
| Font (`test_wordmark.py`) | the five MERNA glyphs match the brief character for character, all 26 letters + space are 5×7 and binary, `layout` puts one blank column between letters and none at the ends, `width` agrees with `layout`, case-insensitive, empty word, unsupported characters raise |
| Wordmark grid | same 53×7 shape as a contribution grid, word centred to within a column, lit cells spell the word exactly (88 for MERNA), trailing-12-month dates preserved so month labels match, over-wide words rejected |
| Wordmark path | **every glyph cell is reached** (also for A/HELLO/WXYZ/III), 8-way connected with no hops, no repeated cells, leads in and out by 2 columns, deterministic, blank word doesn't crash |
| Wordmark timing | 20–25s, nothing dwells, every step the same length, gait still alternates stand/step and never uses the grab pose |
| Wordmark render | well-formed and scriptless, counter + particles + `v` keyframes all absent, same viewBox and same Mon/Wed/Fri and month labels as contribution mode, letters start at `--empty` and brighten to `--l4` with no outline, only glyph cells animate (gaps are walked but not lit), the finished word holds past `RUN_SECONDS` before resetting, deterministic and under 150 KB |
| Mode isolation | `--word` never touches the network and caches no payload, a bad word exits 4 with a readable message, and rendering without `--word` still produces the counter and the darkening style |

## Gaps

- **The live fetch path has never made a real request.** Error handling
  (401, non-200, non-JSON, GraphQL `errors`, null user) is tested through
  `extract_weeks` and by monkeypatching, but `fetch_calendar` itself is only
  exercised via its guards. Needs a token to close.
- **Rendering is not asserted, only inspected.** Correct animation was verified
  by hand in headless Chrome by seeking `document.getAnimations()` to fixed
  timestamps (see CONTEXT.md → Known gotchas #5). There is no automated visual
  regression. Two render bugs this session (`fill: inherit` going black, the
  counter/label collision) were invisible to the test suite and only showed up
  in a screenshot — worth remembering before trusting green tests here.
- Path-shape assertions are tuned to the synthetic fixture. They are written as
  ranges, but swapping in a real calendar should be followed by a re-read of
  `test_path_wanders_rather_than_sweeping`.
