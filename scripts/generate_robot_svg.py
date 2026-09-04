#!/usr/bin/env python3
"""Generate an animated SVG of a small robot wandering a GitHub contribution grid.

The robot walks a deterministic wandering path across the trailing-12-months
contribution calendar, collecting cells as it goes. Everything is animated with
CSS ``@keyframes`` only -- GitHub strips ``<script>`` out of SVGs, so there is
no JavaScript anywhere in the output.

Usage::

    python scripts/generate_robot_svg.py --username merna-s-saad \\
        --token "$GITHUB_TOKEN" --out dist/contribution-robot.svg

    python scripts/generate_robot_svg.py --username merna-s-saad \\
        --fixture tests/fixtures/sample_calendar.json --out dist/robot.svg
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

try:  # running as a script: scripts/ is already on sys.path
    from robot_sprite import MINI_SYMBOLS, ROBOT_DEFS, robot_use
except ImportError:  # imported as scripts.robot_sprite from the repo root
    from scripts.robot_sprite import MINI_SYMBOLS, ROBOT_DEFS, robot_use

# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------

COLS = 53
ROWS = 7
CELL = 13.0
GAP = 3.0
PITCH = CELL + GAP  # 16px
PAD = 12.0
WEEKDAY_LABEL_W = 30.0
MONTH_LABEL_H = 16.0

GRID_X = PAD + WEEKDAY_LABEL_W
GRID_Y = PAD + MONTH_LABEL_H
GRID_W = COLS * PITCH - GAP  # 845
GRID_H = ROWS * PITCH - GAP  # 109

COUNTER_Y = GRID_Y + GRID_H + 28.0
COUNTER_NUM_DX = 108.0  # gap between the "commits collected" prefix and the number

SVG_W = GRID_X + GRID_W + PAD
SVG_H = COUNTER_Y + 18.0

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"

# --------------------------------------------------------------------------
# Palette (mirrored into CSS custom properties so it can be retuned in one place)
# --------------------------------------------------------------------------

PALETTE: dict[str, str] = {
    "bg": "transparent",
    "empty": "#1B3B44",
    "l1": "#2C5561",
    "l2": "#3E7C89",
    "l3": "#4E9CAB",
    "l4": "#5FB3C4",
    "collected": "#14282E",
    "collected-edge": "#2C5561",
    "robot-body": "#EFE6D5",
    "robot-visor": "#1B2A33",
    "robot-eye": "#FFC94A",
    "counter": "#FF6B1A",
    "label": "#7FA6AE",
}

# --------------------------------------------------------------------------
# Timing
# --------------------------------------------------------------------------

RUN_SECONDS = 22.0  # robot is walking for this long
SETTLE_SECONDS = 2.0  # everything holds, then resets
CYCLE_SECONDS = RUN_SECONDS + SETTLE_SECONDS
MOVE_FRACTION = 0.55  # share of a base step spent translating between cells
PARTICLE_SECONDS = 0.9
COLLECT_SECONDS = 0.25  # how long a cell takes to flip to the collected colour
RESET_SECONDS = 1.0
GAIT_PERIOD = 0.4  # full stand -> step -> stand cycle while travelling

# --------------------------------------------------------------------------
# Path generation
# --------------------------------------------------------------------------

MIN_CELLS = 78  # a straight march is 53; the extra length is the wander
GATE_SLACK = 2  # columns the walk may run ahead of its pace
MAX_STEPS = 150
LOOKAHEAD_COLS = 3
BASE_DRIFT = 0.6
JITTER = 0.15
TRAP_PENALTY = 10.0  # steering away from cells that would dead-end the walk

GRAPHQL_URL = "https://api.github.com/graphql"
QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays { date contributionCount weekday }
        }
      }
    }
  }
}
"""

EXIT_NO_TOKEN = 2
EXIT_API = 3
EXIT_DATA = 4

MONTH_NAMES = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


class GeneratorError(Exception):
    """Anything that should abort the run with a clear message."""

    def __init__(self, message: str, code: int = EXIT_DATA) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Cell:
    """One real day on the calendar."""

    day: date
    count: int
    level: int


Grid = list[list[Cell | None]]  # [col][row]; None == padding outside the calendar


@dataclass(frozen=True)
class Step:
    """One cell of the robot's walk, with its slot on the timeline."""

    col: int
    row: int
    count: int
    dwell: bool
    arrive: float  # seconds from the start of the cycle
    hold_until: float  # when it starts translating to the next cell
    depart: float  # == arrive of the next step


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------


def fetch_calendar(username: str, token: str) -> dict[str, Any]:
    """POST the GraphQL query and return the raw JSON payload."""
    try:
        import requests  # imported lazily so fixture runs need no network deps
    except ImportError as exc:  # pragma: no cover - environment specific
        raise GeneratorError(
            "The 'requests' package is required for live runs. "
            "Install it with: pip install -r requirements.txt",
            EXIT_API,
        ) from exc

    try:
        response = requests.post(
            GRAPHQL_URL,
            json={"query": QUERY, "variables": {"login": username}},
            headers={
                "Authorization": f"bearer {token}",
                "User-Agent": "contribution-robot",
            },
            timeout=30,
        )
    except Exception as exc:  # surface any transport failure plainly
        raise GeneratorError(f"Could not reach the GitHub API: {exc}", EXIT_API) from exc

    if response.status_code == 401:
        raise GeneratorError(
            "GitHub rejected the token (401). It needs the 'read:user' scope.",
            EXIT_API,
        )
    if response.status_code != 200:
        raise GeneratorError(
            f"GitHub API returned HTTP {response.status_code}: {response.text[:300]}",
            EXIT_API,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise GeneratorError("GitHub API returned a non-JSON body.", EXIT_API) from exc

    if payload.get("errors"):
        messages = "; ".join(
            str(error.get("message", error)) for error in payload["errors"]
        )
        raise GeneratorError(f"GitHub GraphQL error: {messages}", EXIT_API)
    return payload


def extract_weeks(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Pull ``weeks`` and the year total out of a payload or a bare calendar."""
    node: Any = payload
    if isinstance(node, dict) and "data" in node:
        node = node["data"]
    if isinstance(node, dict) and "user" in node:
        if node["user"] is None:
            raise GeneratorError("GitHub has no user by that name.")
        node = node["user"]
    if isinstance(node, dict) and "contributionsCollection" in node:
        node = node["contributionsCollection"]
    if isinstance(node, dict) and "contributionCalendar" in node:
        node = node["contributionCalendar"]

    if not isinstance(node, dict) or "weeks" not in node:
        raise GeneratorError(
            "Could not find contributionCalendar.weeks in the data. "
            "If this is a fixture, save a full API response from dist/last_fetch.json."
        )
    weeks = node["weeks"]
    if not weeks:
        raise GeneratorError("The contribution calendar came back empty.")
    return list(weeks), int(node.get("totalContributions", 0))


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------


def quantile(values: Sequence[int], fraction: float) -> int:
    """Nearest-rank quantile. ``values`` must be sorted ascending."""
    if not values:
        return 0
    index = min(len(values) - 1, max(0, round(fraction * (len(values) - 1))))
    return values[index]


def build_grid(weeks: Sequence[dict[str, Any]]) -> Grid:
    """Normalise the API's ragged weeks into a strict 53x7 grid.

    GitHub's first and last weeks are usually partial. Those missing days stay
    as ``None`` and get rendered as empty cells rather than being skipped, so
    the columns stay aligned with the real weekday rows.
    """
    columns: list[list[Cell | None]] = []
    nonzero: list[int] = []

    for week in weeks:
        column: list[Cell | None] = [None] * ROWS
        for entry in week.get("contributionDays", []):
            try:
                day = date.fromisoformat(entry["date"])
                count = int(entry["contributionCount"])
            except (KeyError, TypeError, ValueError) as exc:
                raise GeneratorError(f"Malformed contribution day: {entry!r}") from exc
            row = int(entry.get("weekday", day.isoweekday() % 7))
            if not 0 <= row < ROWS:
                raise GeneratorError(f"Weekday out of range in {entry!r}")
            column[row] = Cell(day=day, count=count, level=0)
            if count > 0:
                nonzero.append(count)
        columns.append(column)

    # Trim or pad to exactly 53 columns, keeping the most recent weeks.
    if len(columns) > COLS:
        columns = columns[-COLS:]
    while len(columns) < COLS:
        columns.insert(0, [None] * ROWS)

    nonzero.sort()
    q1 = quantile(nonzero, 0.25)
    q2 = quantile(nonzero, 0.50)
    q3 = quantile(nonzero, 0.75)
    for column in columns:
        for row, cell in enumerate(column):
            if cell is None or cell.count == 0:
                continue
            if cell.count <= q1:
                level = 1
            elif cell.count <= q2:
                level = 2
            elif cell.count <= q3:
                level = 3
            else:
                level = 4
            column[row] = Cell(day=cell.day, count=cell.count, level=level)
    return columns


def grid_end_date(grid: Grid) -> date:
    """The most recent real day on the calendar; used as the RNG seed."""
    for column in reversed(grid):
        for cell in reversed(column):
            if cell is not None:
                return cell.day
    raise GeneratorError("The calendar contains no dated days.")


def dwell_threshold(grid: Grid) -> int:
    """Counts at or above this are 'top quartile' and make the robot linger."""
    nonzero = sorted(
        cell.count for column in grid for cell in column if cell and cell.count > 0
    )
    return quantile(nonzero, 0.75) if nonzero else 0


# --------------------------------------------------------------------------
# Path
# --------------------------------------------------------------------------

NEIGHBOURS: tuple[tuple[int, int], ...] = tuple(
    (dc, dr) for dc in (-1, 0, 1) for dr in (-1, 0, 1) if (dc, dr) != (0, 0)
)


def count_at(grid: Grid, col: int, row: int) -> int:
    if not (0 <= col < COLS and 0 <= row < ROWS):
        return 0
    cell = grid[col][row]
    return cell.count if cell else 0


def lookahead_score(grid: Grid, col: int, row: int, scale: float) -> float:
    """Own count, plus a distance-weighted peek at the next 3 columns."""
    score = 2.0 * count_at(grid, col, row) / scale
    for dc in range(1, LOOKAHEAD_COLS + 1):
        for dr in (-1, 0, 1):
            score += count_at(grid, col + dc, row + dr) / scale / dc
    return score


def build_path(grid: Grid, rng: random.Random) -> list[tuple[int, int]]:
    """Wander left-to-right, greedy toward contributions, never revisiting.

    A constant rightward drift keeps the walk moving, and a *pacing gate*
    caps how far right it is allowed to be for the number of steps taken so
    far. The robot presses against that gate, cannot outrun it, and spends the
    difference wandering vertically -- which is what turns a straight march
    into a wander while still guaranteeing it crosses the whole grid.

    The gate also has to exist: with no cap the walk reaches the last column
    early, exhausts those seven cells, and can never get back to the edge.
    """
    scale = float(
        max(
            1,
            max((cell.count for column in grid for cell in column if cell), default=1),
        )
    )
    row = rng.randrange(ROWS)
    col = 0
    path: list[tuple[int, int]] = [(col, row)]
    visited: set[tuple[int, int]] = {(col, row)}

    while len(path) < MAX_STEPS:
        if col == COLS - 1:
            break

        gate = min(COLS - 1, (COLS - 1) * len(path) // MIN_CELLS + GATE_SLACK)

        best: tuple[int, int] | None = None
        best_score = float("-inf")
        loose: tuple[int, int] | None = None
        loose_score = float("-inf")
        for dc, dr in NEIGHBOURS:
            nc, nr = col + dc, row + dr
            if not (0 <= nc < COLS and 0 <= nr < ROWS):
                continue
            if (nc, nr) in visited:
                continue
            score = (
                lookahead_score(grid, nc, nr, scale)
                + BASE_DRIFT * dc
                + rng.random() * JITTER
            )
            if not _has_escape(visited, nc, nr):
                score -= TRAP_PENALTY  # would strand the robot next step
            if score > loose_score:
                loose_score, loose = score, (nc, nr)
            if nc <= gate and score > best_score:
                best_score, best = score, (nc, nr)

        # Ignore the gate rather than stall; hop only if truly boxed in.
        best = best or loose or _nearest_unvisited(grid, visited, col, scale)
        if best is None:
            break

        col, row = best
        path.append(best)
        visited.add(best)

    return path


def _has_escape(visited: set[tuple[int, int]], col: int, row: int) -> bool:
    """True if (col, row) still has an unvisited 8-way neighbour."""
    return any(
        0 <= col + dc < COLS
        and 0 <= row + dr < ROWS
        and (col + dc, row + dr) not in visited
        for dc, dr in NEIGHBOURS
    )


def _nearest_unvisited(
    grid: Grid, visited: set[tuple[int, int]], col: int, scale: float
) -> tuple[int, int] | None:
    for search_col in list(range(col + 1, COLS)) + list(range(col - 1, -1, -1)):
        candidates = [
            (search_col, r) for r in range(ROWS) if (search_col, r) not in visited
        ]
        if candidates:
            return max(
                candidates, key=lambda c: lookahead_score(grid, c[0], c[1], scale)
            )
    return None


def build_timeline(grid: Grid, path: Sequence[tuple[int, int]]) -> list[Step]:
    """Assign every path cell a slot so the whole walk fills RUN_SECONDS."""
    threshold = dwell_threshold(grid)
    dwells = [bool(threshold and count_at(grid, c, r) >= threshold) for c, r in path]
    total_units = sum(3.0 if d else 1.0 for d in dwells)
    base = RUN_SECONDS / total_units
    move = base * MOVE_FRACTION

    steps: list[Step] = []
    t = 0.0
    for index, ((col, row), dwell) in enumerate(zip(path, dwells)):
        slot = base * (3.0 if dwell else 1.0)
        is_last = index == len(path) - 1
        hold = t + (slot if is_last else max(slot - move, slot * 0.15))
        steps.append(
            Step(
                col=col,
                row=row,
                count=count_at(grid, col, row),
                dwell=dwell,
                arrive=t,
                hold_until=hold,
                depart=t + slot,
            )
        )
        t += slot
    return steps


# --------------------------------------------------------------------------
# Sprite pose timeline
# --------------------------------------------------------------------------


def build_facings(steps: Sequence[Step]) -> list[int]:
    """+1 facing right, -1 facing left, looking ahead to the next column."""
    facings: list[int] = []
    current = 1
    for index, step in enumerate(steps):
        if index + 1 < len(steps):
            delta = steps[index + 1].col - step.col
            if delta > 0:
                current = 1
            elif delta < 0:
                current = -1
        facings.append(current)
    return facings


def build_pose_segments(steps: Sequence[Step]) -> list[tuple[float, float, str, int]]:
    """Chronological ``(start, end, pose, facing)`` covering the whole cycle.

    While travelling the sprite alternates stand/step on GAIT_PERIOD, phased
    off a global clock so the gait stays continuous across cells. A dwell beat
    on a top-quartile cell swaps to the grab pose for exactly the hold, which
    is when that cell's particle launches toward the counter.
    """
    facings = build_facings(steps)
    segments: list[tuple[float, float, str, int]] = []

    def alternate(start: float, end: float, facing: int) -> None:
        half = GAIT_PERIOD / 2.0
        t = start
        while t < end - 1e-9:
            index = int(t / half + 1e-9)
            nxt = min(end, (index + 1) * half)
            segments.append((t, nxt, "stand" if index % 2 == 0 else "step", facing))
            t = nxt

    for step, facing in zip(steps, facings):
        if step.dwell:
            segments.append((step.arrive, step.hold_until, "grab", facing))
            alternate(step.hold_until, step.depart, facing)
        else:
            alternate(step.arrive, step.depart, facing)

    # Settle: stand still until the cycle resets.
    segments.append((RUN_SECONDS, CYCLE_SECONDS, "stand", facings[-1]))

    merged: list[tuple[float, float, str, int]] = []
    for start, end, pose, facing in segments:
        if end - start < 1e-9:
            continue
        if merged and merged[-1][2] == pose and merged[-1][3] == facing:
            merged[-1] = (merged[-1][0], end, pose, facing)
        else:
            merged.append((start, end, pose, facing))
    return merged


# --------------------------------------------------------------------------
# SVG helpers
# --------------------------------------------------------------------------


def num(value: float) -> str:
    """Compact number formatting -- keeps the output small."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def pct(seconds: float) -> str:
    """Seconds on the cycle timeline -> a keyframe percentage."""
    value = max(0.0, min(100.0, seconds / CYCLE_SECONDS * 100.0))
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return (text if text else "0") + "%"


def cell_x(col: int) -> float:
    return GRID_X + col * PITCH


def cell_y(row: int) -> float:
    return GRID_Y + row * PITCH


def cell_centre(col: int, row: int) -> tuple[float, float]:
    return cell_x(col) + CELL / 2.0, cell_y(row) + CELL / 2.0


def month_labels(grid: Grid) -> list[tuple[int, str]]:
    """(column, label) for each month boundary, skipping cramped ones."""
    labels: list[tuple[int, str]] = []
    previous_month = -1
    last_col = -99
    for col, column in enumerate(grid):
        first = next((cell for cell in column if cell is not None), None)
        if first is None:
            continue
        if first.day.month != previous_month:
            previous_month = first.day.month
            if col - last_col >= 3 and col <= COLS - 3:
                labels.append((col, MONTH_NAMES[first.day.month - 1]))
                last_col = col
    return labels


def opacity_keyframes(name: str, windows: Sequence[tuple[float, float]]) -> str:
    """Show the element only during ``windows``; base opacity is 0.

    Paired with ``animation-timing-function: steps(1, end)`` so each stop holds
    its value until the next one rather than cross-fading.
    """
    parts: list[str] = []
    if not windows or windows[0][0] > 0.0:
        parts.append("0%{opacity:0}")
    for start, end in windows:
        parts.append(f"{pct(start)}{{opacity:1}}")
        if end < CYCLE_SECONDS:
            parts.append(f"{pct(end)}{{opacity:0}}")
    if not windows or windows[-1][1] < CYCLE_SECONDS:
        parts.append("100%{opacity:0}")
    return f"@keyframes {name}{{" + "".join(parts) + "}"


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def render_style(
    steps: Sequence[Step],
    collected: Sequence[tuple[int, Step, int]],
) -> str:
    """Variables, classes, and the shared/robot keyframes.

    Note on timing: with ``animation-iteration-count: infinite`` every element
    shares the same CYCLE_SECONDS duration, so an ``animation-delay`` is a
    rigid shift of one timeline and cannot produce a common reset instant.
    Cells, counter values and sprite poses therefore get per-element keyframes
    at computed percentages. Particles are short transients that are invisible
    at both ends of their flight, so they genuinely can share one keyframe set
    with a per-element delay.
    """
    lines: list[str] = []
    variables = ";".join(f"--{key}:{value}" for key, value in PALETTE.items())
    lines.append(f":root{{{variables}}}")
    lines.append("svg{background:var(--bg)}")
    lines.append(
        ".l0{fill:var(--empty)}.l1{fill:var(--l1)}.l2{fill:var(--l2)}"
        ".l3{fill:var(--l3)}.l4{fill:var(--l4)}"
    )
    lines.append(
        ".col{stroke:var(--collected-edge);stroke-width:1;stroke-opacity:0;"
        f"animation-duration:{num(CYCLE_SECONDS)}s;animation-iteration-count:infinite;"
        "animation-timing-function:ease-out}"
    )
    lines.append(
        f".lbl{{fill:var(--label);font:400 9px {FONT}}}"
        f".pre{{fill:var(--label);font:400 10px {FONT};letter-spacing:.4px}}"
    )
    lines.append(
        f".cv{{fill:var(--counter);font:700 15px {FONT};opacity:0;"
        f"animation-duration:{num(CYCLE_SECONDS)}s;animation-iteration-count:infinite;"
        "animation-timing-function:steps(1,end)}"
    )
    lines.append(
        f".p{{fill:var(--counter);opacity:0;animation:fly {num(CYCLE_SECONDS)}s "
        "linear infinite}"
    )
    lines.append(
        f".robot{{animation:walk {num(CYCLE_SECONDS)}s linear infinite}}"
        f".rp{{opacity:0;animation-duration:{num(CYCLE_SECONDS)}s;"
        "animation-iteration-count:infinite;animation-timing-function:steps(1,end)}"
    )

    # Particles: one shared flight, aimed per element via --dx/--dy.
    lines.append(
        "@keyframes fly{0%{opacity:1;transform:translate(0,0)}"
        f"{pct(PARTICLE_SECONDS)}{{opacity:0;"
        "transform:translate(var(--dx),var(--dy))}"
        "100%{opacity:0;transform:translate(var(--dx),var(--dy))}}"
    )

    # Robot: an explicit keyframe pair per waypoint, so dwells read as a held
    # position rather than an eased slowdown.
    walk: list[str] = []
    for step in steps:
        x, y = cell_centre(step.col, step.row)
        position = f"transform:translate({num(x)}px,{num(y)}px)"
        walk.append(f"{pct(step.arrive)}{{{position}}}")
        if step.hold_until > step.arrive:
            walk.append(f"{pct(step.hold_until)}{{{position}}}")
    last = steps[-1]
    lx, ly = cell_centre(last.col, last.row)
    walk.append(f"100%{{transform:translate({num(lx)}px,{num(ly)}px)}}")
    lines.append("@keyframes walk{" + "".join(walk) + "}")

    # Cells: empty -> collected on arrival, held through the settle, then reset.
    # The idle colour has to be named explicitly: `fill: inherit` would take
    # the parent group's fill (black) rather than the cell's own level class,
    # because an animation overrides the class for the whole cycle.
    reset_start = RUN_SECONDS
    reset_end = min(CYCLE_SECONDS, RUN_SECONDS + RESET_SECONDS)
    for index, step, level in collected:
        idle = "var(--empty)" if level == 0 else f"var(--l{level})"
        flip = min(step.arrive + COLLECT_SECONDS, reset_start)
        lines.append(
            f"@keyframes k{index}{{"
            f"0%,{pct(step.arrive)}{{fill:{idle};stroke-opacity:0}}"
            f"{pct(flip)},{pct(reset_start)}{{fill:var(--collected);stroke-opacity:1}}"
            f"{pct(reset_end)},100%{{fill:{idle};stroke-opacity:0}}}}"
        )
    return "\n".join(lines)


def render_robot(steps: Sequence[Step]) -> tuple[str, str]:
    """The robot group plus the keyframes driving its pose swaps."""
    segments = build_pose_segments(steps)

    windows: dict[tuple[str, int], list[tuple[float, float]]] = {}
    for start, end, pose, facing in segments:
        windows.setdefault((pose, facing), []).append((start, end))

    uses: list[str] = []
    keyframes: list[str] = []
    for index, ((pose, facing), spans) in enumerate(sorted(windows.items())):
        name = f"rp{index}"
        keyframes.append(opacity_keyframes(name, spans))
        uses.append(
            robot_use(
                0.0,
                0.0,
                facing,
                MINI_SYMBOLS[pose],
                extra=f' class="rp" style="animation-name:{name}"',
            )
        )

    start_x, start_y = cell_centre(steps[0].col, steps[0].row)
    group = (
        f'<g class="robot" style="transform:translate({num(start_x)}px,'
        f'{num(start_y)}px)">' + "".join(uses) + "</g>"
    )
    return group, "\n".join(keyframes)


def render_svg(grid: Grid, username: str, year_total: int) -> str:
    rng = random.Random(grid_end_date(grid).isoformat())
    path = build_path(grid, rng)
    steps = build_timeline(grid, path)

    def level_at(col: int, row: int) -> int:
        cell = grid[col][row]
        return cell.level if cell else 0

    collected = [
        (index, step, level_at(step.col, step.row))
        for index, step in enumerate(steps)
    ]
    step_by_position = {(step.col, step.row): index for index, step, _ in collected}

    # Counter windows: the value only changes when a cell with commits is hit.
    counter_x = GRID_X + COUNTER_NUM_DX
    particles: list[str] = []
    values: list[int] = [0]
    starts: list[float] = [0.0]
    running = 0
    for _, step, _level in collected:
        if step.count <= 0:
            continue
        running += step.count
        values.append(running)
        starts.append(step.arrive)
        cx, cy = cell_centre(step.col, step.row)
        particles.append(
            f'<circle class="p" cx="{num(cx)}" cy="{num(cy)}" r="2" '
            f'style="--dx:{num(counter_x + 6 - cx)}px;'
            f'--dy:{num(COUNTER_Y - 5 - cy)}px;'
            f'animation-delay:{num(step.arrive)}s"/>'
        )

    counter_windows = [
        (start, starts[i + 1] if i + 1 < len(starts) else CYCLE_SECONDS)
        for i, start in enumerate(starts)
    ]

    robot, pose_keyframes = render_robot(steps)
    style = "\n".join(
        [
            render_style(steps, collected),
            "\n".join(
                opacity_keyframes(f"v{i}", [window])
                for i, window in enumerate(counter_windows)
            ),
            pose_keyframes,
        ]
    )

    # --- grid ------------------------------------------------------------
    cells: list[str] = []
    for col in range(COLS):
        for row in range(ROWS):
            cell = grid[col][row]
            level = cell.level if cell else 0
            index = step_by_position.get((col, row))
            classes = f"l{level}" + (" col" if index is not None else "")
            extra = f' style="animation-name:k{index}"' if index is not None else ""
            cells.append(
                f'<rect class="{classes}" x="{num(cell_x(col))}" '
                f'y="{num(cell_y(row))}" width="{num(CELL)}" height="{num(CELL)}" '
                f'rx="3"{extra}/>'
            )

    # --- labels ----------------------------------------------------------
    months = "".join(
        f'<text class="lbl" x="{num(cell_x(col))}" y="{num(GRID_Y - 5)}">{name}</text>'
        for col, name in month_labels(grid)
    )
    weekdays = "".join(
        f'<text class="lbl" x="{num(GRID_X - 6)}" y="{num(cell_y(row) + 10)}" '
        f'text-anchor="end">{name}</text>'
        for row, name in ((1, "Mon"), (3, "Wed"), (5, "Fri"))
    )

    # --- counter ---------------------------------------------------------
    counter = [
        (
            f'<text class="pre" x="{num(GRID_X)}" y="{num(COUNTER_Y)}">'
            f"commits collected</text>"
        )
    ]
    counter += [
        f'<text class="cv" x="{num(counter_x)}" y="{num(COUNTER_Y)}" '
        f'style="animation-name:v{i}">{value:,}</text>'
        for i, value in enumerate(values)
    ]

    total_collected = values[-1]
    safe_user = escape(username)
    title = f"{safe_user}&#8217;s contribution robot"
    desc = (
        f"An animated GitHub contribution grid for {safe_user}. "
        f"The year&#8217;s total is {year_total:,} contributions. "
        f"A small robot wanders {len(steps)} of the {COLS * ROWS} cells and "
        f"collects {total_collected:,} contributions over {num(RUN_SECONDS)} "
        "seconds, then the animation resets and repeats."
    )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'viewBox="0 0 {num(SVG_W)} {num(SVG_H)}" role="img" '
        f'aria-labelledby="robotTitle robotDesc" preserveAspectRatio="xMinYMin meet">'
        f'<title id="robotTitle">{title}</title>'
        f'<desc id="robotDesc">{desc}</desc>'
        f"<style>{style}</style>"
        f"<defs>{ROBOT_DEFS}</defs>"
        f'<g class="months">{months}</g>'
        f'<g class="weekdays">{weekdays}</g>'
        f'<g class="cells">{"".join(cells)}</g>'
        f'<g class="particles">{"".join(particles)}</g>'
        f'<g class="counter">{"".join(counter)}</g>'
        f"{robot}"
        "</svg>\n"
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an animated contribution-grid robot SVG."
    )
    parser.add_argument("--username", required=True, help="GitHub login to render")
    parser.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN", ""),
        help="GitHub PAT with read:user (defaults to $GITHUB_TOKEN)",
    )
    parser.add_argument(
        "--out",
        default="dist/contribution-robot.svg",
        type=Path,
        help="Where to write the SVG",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help="Render from a saved JSON payload instead of calling the API",
    )
    return parser.parse_args(argv)


def load_payload(args: argparse.Namespace) -> tuple[dict[str, Any], bool]:
    if args.fixture is not None:
        if not args.fixture.is_file():
            raise GeneratorError(f"Fixture not found: {args.fixture}")
        try:
            return json.loads(args.fixture.read_text(encoding="utf-8")), False
        except json.JSONDecodeError as exc:
            raise GeneratorError(f"Fixture is not valid JSON: {exc}") from exc

    if not args.token:
        raise GeneratorError(
            "No GitHub token. Pass --token or set $GITHUB_TOKEN "
            "(a classic PAT with the 'read:user' scope), or use --fixture "
            "to render from saved data.",
            EXIT_NO_TOKEN,
        )
    return fetch_calendar(args.username, args.token), True


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload, live = load_payload(args)
        weeks, year_total = extract_weeks(payload)
        grid = build_grid(weeks)
        svg = render_svg(grid, args.username, year_total)
    except GeneratorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code

    out: Path = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")

    if live:
        cache = out.parent / "last_fetch.json"
        cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"saved payload -> {cache}")

    size = out.stat().st_size
    print(f"wrote {out} ({size:,} bytes, {size / 1024:.1f} KB)")
    if size > 150_000:
        print("warning: output is over the 150KB budget", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
