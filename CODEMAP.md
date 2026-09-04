# CODEMAP

updated-at: c78834a

Navigation map for `contribution-robot`. Read this before opening files.

## What this repo is

One Python generator that turns a GitHub contribution calendar into a
self-contained, CSS-animated SVG of a robot wandering the grid collecting
commits. No runtime, no server, no JavaScript in the output.

## Entry points

| Entry | File | Notes |
|---|---|---|
| CLI | `scripts/generate_robot_svg.py` → `main()` | `--username --token --out --fixture` |
| Library | `render_svg(grid, username, year_total) -> str` | pure; no I/O |
| Sprite | `scripts/robot_sprite.py` → `ROBOT_DEFS`, `robot_use()` | imported by the generator |

## Data flow

```
parse_args
  └─ load_payload ──┬─ fetch_calendar (GraphQL POST)   -> also writes dist/last_fetch.json
                    └─ --fixture (read JSON from disk)
       └─ extract_weeks      unwrap data/user/contributionsCollection/contributionCalendar
            └─ build_grid    ragged weeks -> strict 53x7 Grid[col][row] of Cell|None
                 └─ render_svg
                      ├─ build_path        seeded wander, no revisits          (RNG seed = end date)
                      ├─ build_timeline    Step slots filling RUN_SECONDS
                      ├─ build_pose_segments / build_facings   sprite pose + facing timeline
                      ├─ render_style      :root vars, classes, walk + cell keyframes
                      ├─ render_robot      6 stacked <use> + rpN opacity keyframes
                      └─ opacity_keyframes counter values vN
```

## File map

| Path | Contains |
|---|---|
| `scripts/generate_robot_svg.py` | everything except the sprite art: fetch, normalise, path, timeline, CSS, SVG assembly, CLI |
| `scripts/robot_sprite.py` | 6 `<symbol>` poses + `robot_use()`; art only, no timing logic |
| `tests/test_generate_robot_svg.py` | 43 tests, grouped by section comment |
| `tests/fixtures/sample_calendar.json` | 53 weeks, deliberately partial first/last week, 742 contributions |
| `requirements.txt` | `requests` (live fetch only; lazily imported) |
| `dist/` | gitignored output: `contribution-robot.svg`, `last_fetch.json` |

## Section landmarks in `generate_robot_svg.py`

Constants are grouped under banner comments in this order: Layout → Palette →
Timing → Path generation. Then: data model, fetching, normalisation, path,
sprite pose timeline, SVG helpers, rendering, CLI.

## Boundaries

- `robot_sprite.py` knows nothing about time, paths, or the grid. It only draws.
- Colours live in exactly one place: `PALETTE` in the generator, emitted as CSS
  custom properties. Nothing else may contain a hex literal (a test enforces it).
- Everything after `build_grid` is deterministic and pure — same calendar in,
  byte-identical SVG out.

## Where to look for...

| Question | Go to |
|---|---|
| Why is the walk shaped like that? | `build_path` docstring (the pacing gate) |
| Why per-element keyframes not `animation-delay`? | `render_style` docstring |
| Why do collected cells name their idle colour? | `render_style`, cell keyframe loop |
| How long does it run? | `RUN_SECONDS` / `CYCLE_SECONDS` in the Timing block |
| How is the sprite sized/mirrored? | `robot_use` in `robot_sprite.py` |
