# CONTEXT

updated-at: c78834a

The living snapshot of this project. Read with `CODEMAP.md`.

## Goal

Generate an animated SVG of a small robot wandering a GitHub contribution grid
and collecting commits, to embed in a GitHub profile README. One Python script
produces the whole thing; the SVG is fully self-contained and static once
written.

## Hard constraints (these drive most of the design)

1. **No JavaScript in the output.** GitHub sanitises `<script>` out of SVGs
   served in READMEs. All animation is CSS `@keyframes` in a `<style>` block.
   A test asserts there is no `<script`, no `javascript:`, and no inline
   `on*=` handler.
2. **Under 150 KB.** Currently 73.4 KB from the sample fixture. The byte size
   is printed at the end of every run and asserted in tests.
3. **Deterministic.** Same calendar in → byte-identical SVG out. The RNG is
   seeded with the calendar's end date.
4. **No fixed `width`/`height` on the root `<svg>`** — `viewBox` only, so it
   scales to whatever container the README puts it in.
5. **Type hints throughout; no dependencies beyond `requests`.** `requests` is
   imported lazily inside `fetch_calendar`, so fixture runs and the whole test
   suite need no third-party HTTP library.

## Usage

```bash
python scripts/generate_robot_svg.py \
  --username merna-s-saad --token "$GITHUB_TOKEN" \
  --out dist/contribution-robot.svg

# offline, from saved data
python scripts/generate_robot_svg.py \
  --username merna-s-saad --fixture tests/fixtures/sample_calendar.json \
  --out dist/contribution-robot.svg
```

`--token` defaults to `$GITHUB_TOKEN`. Every live run also writes the raw
payload to `<out-dir>/last_fetch.json` so new fixtures are trivial to make.
Exit codes: `2` missing token, `3` API/transport failure, `4` bad data.

GitHub login in use: **merna-s-saad**. The token needs the `read:user` scope
(the contributions calendar is not available unauthenticated).

## Layout decisions

- Cell 13px, gap 3px → pitch 16px. Grid 53 × 7 = 845 × 109.
- 12px padding, 30px reserved left for weekday labels, 16px above for months.
- viewBox `0 0 899 183`.
- Month labels above the grid; a month is skipped if it would land within 3
  columns of the previous label or within 3 columns of the right edge.
- Weekday labels Mon/Wed/Fri only (rows 1, 3, 5), right-aligned.
- Counter sits below the grid, left-aligned under the first column at y=165.
  Static prefix `commits collected` at x=42, number at x=150
  (`COUNTER_NUM_DX = 108`, widened from 92 after a render showed the label and
  the number colliding).

## Palette (teal, matched to an existing avatar)

Every colour is a CSS custom property on `:root`, defined once in `PALETTE` in
the generator. A test asserts no hex literal appears anywhere outside the
`<style>` block, including in the sprite module.

| Token | Value | Used for |
|---|---|---|
| `--bg` | `transparent` | page background |
| `--empty` | `#1B3B44` | level-0 cell |
| `--l1` … `--l4` | `#2C5561`, `#3E7C89`, `#4E9CAB`, `#5FB3C4` | contribution levels |
| `--collected` | `#14282E` | a cell the robot has taken |
| `--collected-edge` | `#2C5561` | 1px outline on collected cells |
| `--robot-body` | `#EFE6D5` | sprite body |
| `--robot-visor` | `#1B2A33` | visor, chest panel, all sprite strokes |
| `--robot-eye` | `#FFC94A` | eyes |
| `--counter` | `#FF6B1A` | counter number and particles |
| `--label` | `#7FA6AE` | month/weekday labels, counter prefix |

Levels are computed from quartiles of the year's **non-zero** counts, not from
GitHub's own level enum.

## The wander

- Seeded `random.Random(end_date.isoformat())`.
- Starts in column 0 on a random row; 8-way steps; never revisits a cell.
- Candidate score = own count ×2 + a distance-weighted peek at the next 3
  columns (rows ±1), all normalised by the year's max count, plus a constant
  rightward drift (`BASE_DRIFT = 0.6`) and a seeded jitter (0.15).
- **Pacing gate** (`MIN_CELLS = 78`, `GATE_SLACK = 2`): the robot may not be
  further right than `52 * len(path) / 78 + 2`. It presses against this gate
  and spends the surplus wandering vertically. This is what makes it a wander
  rather than a sweep.
- **Trap penalty** (`TRAP_PENALTY = 10`): a candidate with no unvisited
  neighbour of its own is heavily penalised, which keeps the walk 8-way
  connected instead of having to teleport out of a dead end.
- Fallbacks in order: gated best → ungated best → nearest unvisited column to
  the right. The last one would visibly teleport; the trap penalty keeps it
  from firing on real data.
- Dwell: a cell whose count is at or above the 75th percentile of non-zero
  counts holds for 3× a normal step.

On the sample fixture: 76 cells, 22 backtracking moves, 51 vertical moves,
32 dwells, ends at column 52, collects 312 of 742 contributions.

## Timing

`RUN_SECONDS = 22` walking + `SETTLE_SECONDS = 2` → `CYCLE_SECONDS = 24`,
`animation-iteration-count: infinite`. The base step is *derived*
(`22 / total_units`, a dwell counting as 3 units), so the run is exactly 22s no
matter how long the path came out. Cells reset over the 1s from t=22 to t=23.

## The keyframes decision (important, and a deliberate deviation)

The original brief asked for one shared `@keyframes` set plus per-element
`animation-delay`. That cannot work here: with `animation-iteration-count:
infinite`, every element must share the same 24s duration to stay in lockstep,
and once durations are equal, a delay is a *rigid shift* of one timeline —
there is no way to make all elements reset at the same absolute instant.
Collected cells would silently re-collect instead of resetting during the
settle. So:

- **Cells, counter values, sprite poses** → per-element `@keyframes` at
  computed percentages.
- **Particles** → shared `@keyframes fly` + per-element `animation-delay`, with
  the per-particle destination passed as `--dx` / `--dy` custom properties.
  This one genuinely works with a delay: the flight is a 0.9s transient that is
  opacity-0 at both ends, so the staggered reset is invisible. If `var()` in
  keyframes ever failed, the particle would simply fade in place rather than
  break the render.

This was raised with the user before implementation and approved (option 1).

## Sprite (`scripts/robot_sprite.py`)

- Six `<symbol>`s, all sharing viewBox `-20 -8 40 72` with `overflow="visible"`
  (the ears reach x=±21 and would otherwise be clipped).
- Detailed poses: `robot-stand`, `robot-step`, `robot-grab`. Strokes 1.4 on
  head/torso, 1.2 on limbs, ears and chest panel.
- Simplified poses: `robot-mini`, `robot-mini-step`, `robot-mini-grab` — chest
  panel dropped, all strokes bumped to 2, because the sprite renders ~22px tall
  over 13px cells and the fine detail turns to mud.
- **Extension to the brief:** the brief specified a single `robot-mini` but also
  asked for stand/step alternation and a grab pose during the walk. One mini
  symbol cannot do both, so the mini family was extended to all three poses.
  The detailed trio is untouched and reserved for a larger standalone render.
- `robot_use(x, y, facing, symbol, extra)` centres the sprite on `(x, y)` at
  22px tall. `facing = -1` emits `transform="translate(2x 0) scale(-1 1)"`,
  which mirrors about the sprite's own x centre. Because the sprite box is
  symmetric about that centre, the mirrored element occupies exactly the same
  rectangle — no transform-origin / transform-box ambiguity. Never flips
  vertically.
- `href` **and** `xlink:href` are both emitted for maximum viewer compatibility.

## Animation composition

- Robot position: one `walk` keyframe set on the outer `<g class="robot">`,
  two stops per waypoint (arrive, hold) so dwells read as a genuine hold rather
  than an eased slowdown.
- Poses: six stacked `<use>` elements (3 poses × 2 facings), exactly one opaque
  at a time via `rpN` opacity keyframes with `steps(1, end)`. Stand/step
  alternate on a 0.4s gait phased off a global clock so the gait stays
  continuous across cells; grab covers exactly the dwell hold, which is when
  that cell's particle launches.
- Counter: a stack of `<text>` elements, one per cumulative value, one visible
  at a time. Values only change on cells with count > 0, which keeps the stack
  (and the particle count) down.

## Known gotchas / bugs already fixed

1. **`fill: inherit` in cell keyframes rendered every collected cell black.**
   An animation overrides the element's class for the whole cycle, and
   `inherit` takes the *parent group's* fill (unset → black), not the level
   class. Cell keyframes now name their idle colour explicitly
   (`var(--l3)` etc.). Caught only by rendering a screenshot.
2. **First wander implementation was a pure left-to-right sweep.** The drift
   bonus always beat the contribution score differences. Fixed with the pacing
   gate.
3. **Second attempt reached column 52 at step 61**, then wandered, exhausted the
   seven cells of the last column, and could never return to the edge — the
   path ended at column 34. The gate fixed this too.
4. **Counter/label collision** at `COUNTER_NUM_DX = 92`; now 108.
5. **Chrome headless `--virtual-time-budget` does not advance the CSS animation
   clock.** Screenshots taken that way look like t≈0 and will make you think
   the counter is broken. To verify a specific moment, inline the SVG in an
   HTML wrapper and seek: `document.getAnimations().forEach(a => {a.pause();
   a.currentTime = T})`, then screenshot. This is how the render was verified
   at t = 0, 5.5, 11, 16.5, 22.5s.

## Verification performed

`ruff check` clean; 43 pytest tests pass; rendered from the fixture and
screenshotted in headless Chrome at five seeked timestamps. At each one exactly
one counter value and exactly one sprite pose were opaque, the collected count
matched the timeline, and the robot's computed transform matched the expected
cell centre. The mirrored (left-facing) grab pose was rendered zoomed in and
confirmed correct.

## Conventions agreed

- Ruff-clean (the repo has a lint hook that blocks on failure). Notable rules
  it enforces here: `collections.abc` over `typing` for `Sequence`,
  `itertools.pairwise` over `zip(xs, xs[1:])`, no implicit string concatenation
  inside a collection literal, and a shebang requires the file mode be +x.
- Type hints everywhere, `from __future__ import annotations` at the top.
- British spelling in identifiers where it reads naturally (`normalise`,
  `colour` in prose, `centre`).
- Comments explain *why*, not what. Several carry the reasoning for a
  non-obvious constraint (see the keyframes and `fill: inherit` notes above).
- Tests are named as sentences describing the behaviour, grouped under banner
  comments matching the pipeline stages.

## Environment

- Python 3.13.3 at `/usr/local/bin/python3`.
- Local venv at `.venv/` (gitignored) with `pytest` and `requests`.
- `ruff` available on PATH.
- Google Chrome at `/Applications/Google Chrome.app` — used headless for render
  verification.

## Open loose ends

- Never run against the live API — no token was available in this session. The
  fetch path is unit-tested for error handling but has not made a real request.
- The fixture is synthetic (seeded generator, weekday-heavy, a holiday gap, a
  few spikes). Replacing it with a real `last_fetch.json` will change the path
  and the numbers in the path-shape tests' tolerances, though all assertions
  are written as ranges rather than exact values.
- No GitHub Action yet to regenerate the SVG on a schedule and commit it. That
  is the obvious next step for actually using this in a profile README.
- No README.md.
- `robot-stand` / `robot-step` / `robot-grab` (the detailed trio) are emitted
  into every SVG's `<defs>` but never referenced by the animation. They cost
  ~2 KB. Worth pruning if the size budget ever gets tight, or worth using for a
  larger standalone render.
