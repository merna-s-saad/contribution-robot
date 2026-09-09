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
| Wordmark | `--word MERNA` → `build_word_grid` + `build_word_path` | skips the API entirely |

## Data flow

```
parse_args
  └─ load_payload ──┬─ fetch_calendar (GraphQL POST)   -> also writes dist/last_fetch.json
                    └─ --fixture (read JSON from disk)
       └─ extract_weeks      unwrap data/user/contributionsCollection/contributionCalendar
            └─ build_grid    ragged weeks -> strict 53x7 Grid[col][row] of Cell|None
                 └─ render_svg
                      ├─ start_column      density point (dense_column - 2), capped by MIN_SPAN_COLS
                      ├─ build_path        seeded wander, retraces if boxed in (RNG seed = end date)
                      ├─ build_round_trip  outbound + turn + build_return_path -> Timeline
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
| `scripts/grid_font.py` | 5x7 bitmap font, A-Z + space, `layout()`; no knowledge of the grid or the robot |
| `tests/test_generate_robot_svg.py` | 71 tests for contribution mode, grouped by section comment |
| `tests/test_wordmark.py` | 40 tests for the font and wordmark mode |
| `tests/fixtures/sample_calendar.json` | 53 weeks, deliberately partial first/last week, active from column 0, 742 contributions |
| `tests/fixtures/late_start_calendar.json` | same shape but dead until column 16, so the start-column logic has something to bite on; 818 contributions |
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
| Why doesn't it start at column 0? | `start_column` docstring |
| Why is the pace different per calendar? | `target_cells` + the Timing block |
| How fast does it walk, and why? | `CELLS_PER_COLUMN` comment — it is the only pace lever |
| Where does the walk start? | `start_column` / `dense_column` docstrings |
| How does the walk home work? | `build_round_trip` / `build_return_path` |
| Why is there no `CYCLE_SECONDS`? | the two modes have different cycle lengths; it is a parameter now |
| Why does the wordmark sweep full columns? | `build_word_path` docstring |
| What differs between the two modes? | `RenderMode`, and its two instances |
| Why per-element keyframes not `animation-delay`? | `render_style` docstring |
| Why do collected cells name their idle colour? | `render_style`, cell keyframe loop |
| How long does it run? | `RUN_SECONDS` / `CYCLE_SECONDS` in the Timing block |
| How is the sprite sized/mirrored? | `robot_use` in `robot_sprite.py` |
