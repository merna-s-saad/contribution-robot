# TESTING

updated-at: 2026-09-04

```bash
.venv/bin/python -m pytest tests/ -q      # 43 tests, ~0.2s
ruff check scripts/ tests/
```

No network is touched by any test. `requests` is imported lazily inside
`fetch_calendar`, so the suite runs with pytest alone.

## What is covered

| Area | Tests |
|---|---|
| Normalisation | 53×7 shape, partial first/last weeks padded not skipped, >53 weeks trimmed to the most recent, <53 padded left, all five levels produced |
| Path | no revisits, starts col 0, ends col 52, every step 8-way connected, wanders (backtracks + vertical moves + longer than a straight march), deterministic for a fixed seed |
| Timing | run lands in 20–25s, slots contiguous and ordered, dwell slot is exactly 3× a normal slot and only on ≥75th-percentile cells |
| Pose timeline | segments tile the whole cycle with no overlap (so exactly one pose is ever visible), grab covers every dwell beat, facing flips on leftward travel |
| Sprite | all six symbols present, one shared viewBox, no hex literals, mini drops the chest panel and thickens strokes, mirror is in-place and never vertical, `robot_use` centres on its point |
| SVG | well-formed XML, viewBox with no width/height, no script/`javascript:`/`on*=`, title+desc+role, palette defined once as custom properties and no hex outside `<style>`, one animated rect per visited cell, counter is a strictly increasing stack, one particle per scoring cell, every animation shares the 24s duration, loops forever |
| CLI | fixture render writes no `last_fetch.json` and never calls the API, output under 150 KB, missing token → exit 2 with a readable message, missing fixture → exit 4, bad API payloads raise, empty calendar rejected, a zero-contribution year still renders |

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
