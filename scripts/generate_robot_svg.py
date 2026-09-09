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
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

try:  # running as a script: scripts/ is already on sys.path
    import grid_font
    from robot_sprite import MINI_SYMBOLS, ROBOT_DEFS, robot_use
except ImportError:  # imported as scripts.robot_sprite from the repo root
    from scripts import grid_font
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

RUN_SECONDS = 22.0  # the outbound walk; fixed, never compressed
SETTLE_SECONDS = 2.0  # wordmark mode only: hold, then reset
WORDMARK_CYCLE = RUN_SECONDS + SETTLE_SECONDS
MOVE_FRACTION = 0.55  # share of a base step spent translating between cells
PARTICLE_SECONDS = 0.9
COLLECT_SECONDS = 0.25  # how long a cell takes to flip to the collected colour
RESET_SECONDS = 1.0
GAIT_PERIOD = 0.4  # full stand -> step -> stand cycle while travelling

# The walk home. The robot turns at the right edge, walks back over ground it
# has already collected, then everything resets.
TURN_SECONDS = 0.6  # pause at the right edge while it flips facing
RETURN_SPEEDUP = 1.5  # return step is the outbound step divided by this
ARRIVAL_SECONDS = 0.8  # short settle once it is home
MAX_CYCLE_SECONDS = 35.0  # hard ceiling on the whole loop

# --------------------------------------------------------------------------
# Path generation
# --------------------------------------------------------------------------

# Path length scales with the active span, so a short span means a slower,
# more deliberate pace rather than the same sprint over fewer cells. 2.24
# cells per column puts the outbound step at ~0.30s on the current calendar:
# a 30-column active span asks for 67 cells, the wander delivers 64, and the
# five dwells push the unit count to 72 over the fixed 22s. Raise it for a
# denser walk, not a longer one -- RUN_SECONDS never moves. Note the step is
# 22s / *units*, and a dwell costs three units, so cells alone don't set it.
CELLS_PER_COLUMN = 2.24
MIN_CELLS_FLOOR = 24  # below this a single step gets long enough to look broken
LEAD_IN_COLS = 2  # blank columns kept before the first active one
GATE_SLACK = 2  # columns the walk may run ahead of its pace
MAX_STEPS = 260  # headroom for the denser walk plus the return leg
LOOKAHEAD_COLS = 3
BASE_DRIFT = 0.6
JITTER = 0.15
TRAP_PENALTY = 10.0  # steering away from cells that would dead-end the walk
RETRACE_PENALTY = 0.6  # soft nudge away from the outbound route on the way home
DENSITY_SHARE = 0.70  # the walk starts where this much of the year is still ahead
MIN_SPAN_COLS = 30  # never skip so far that the walk has fewer columns than this

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
class RenderMode:
    """What "collecting" a cell means, which differs between the two modes.

    In contribution mode the robot takes commits, so a collected cell darkens
    to ``--collected`` and gains an outline. In wordmark mode there is nothing
    to take -- the robot is lighting the letters up -- so a collected cell goes
    from ``--empty`` to the brightest level, and there is no counter to feed.
    """

    collect_fill: str
    outline: bool
    counter: bool
    dwell: bool
    reset_at: float  # when collected cells start returning to their idle colour


CONTRIBUTION_MODE = RenderMode(
    collect_fill="var(--collected)",
    outline=True,
    counter=True,
    dwell=True,
    reset_at=RUN_SECONDS,
)
# Dwell is off: every letter cell carries the same weight, so the top-quartile
# rule would mark all of them and triple the step count, roughly halving the
# pace. Nothing about the wordmark is "worth lingering on" more than the rest.
# The finished word is the payoff, so it holds through the settle and only
# fades over the last second. Contribution mode starts its reset at t=22, which
# would fade the wordmark the instant the final letter cell lit up.
WORDMARK_MODE = RenderMode(
    collect_fill="var(--l4)",
    outline=False,
    counter=False,
    dwell=False,
    reset_at=WORDMARK_CYCLE - RESET_SECONDS,
)


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
    collecting: bool = True  # False on the walk home: it is not re-harvesting


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


def column_totals(grid: Grid) -> list[int]:
    """Contributions per column."""
    return [sum(cell.count for cell in column if cell) for column in grid]


def first_active_column(grid: Grid) -> int | None:
    """Index of the leftmost column with any contributions at all."""
    for col, column in enumerate(grid):
        if any(cell and cell.count > 0 for cell in column):
            return col
    return None


def dense_column(grid: Grid, share: float = DENSITY_SHARE) -> int | None:
    """The furthest-right column that still has ``share`` of the year ahead of it.

    Note this is the *latest* such column, not the earliest. Taken literally,
    "the earliest column whose remaining span holds at least 70%" is always
    column 0 -- the whole grid trivially holds 100% -- which would make the
    robot walk more empty space, not less. The useful reading is to skip as far
    right as possible while keeping most of the data still ahead.
    """
    totals = column_totals(grid)
    year = sum(totals)
    if year <= 0:
        return None
    remaining = year
    best = 0
    for col, total in enumerate(totals):
        if remaining < share * year:
            break
        best = col
        remaining -= total
    return best


def start_column(grid: Grid) -> int:
    """Where the robot enters the grid.

    Two things are traded off. Skipping a sparse opening stops the robot
    trudging through a faint stretch for most of the animation. But skipping
    too far leaves too few cells to fill the fixed 22s, and the walk crawls --
    a calendar with 90% of its commits in the last five columns will push the
    density point almost to the right edge. So the skip is capped so the active
    span never falls below MIN_SPAN_COLS.

    Everything left of the start still renders as normal cells; it is real data
    and stays visible. The robot simply never walks there.
    """
    if first_active_column(grid) is None:
        return 0  # nothing anywhere: start at the left edge
    dense = dense_column(grid)
    if dense is None:
        return 0
    return max(0, min(dense - LEAD_IN_COLS, COLS - MIN_SPAN_COLS))


def target_cells(start: int) -> int:
    """How many cells the walk should cover, given where it starts."""
    span = COLS - start
    reachable = span * ROWS
    scaled = round(CELLS_PER_COLUMN * span)
    return max(min(MIN_CELLS_FLOOR, reachable), min(scaled, reachable))


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

    The walk starts at the first active column rather than at column 0, and
    both the gate and the target length are measured over that shorter span.
    """
    scale = float(
        max(
            1,
            max((cell.count for column in grid for cell in column if cell), default=1),
        )
    )
    start = start_column(grid)
    span = COLS - 1 - start
    wanted = target_cells(start)

    row = rng.randrange(ROWS)
    col = start
    path: list[tuple[int, int]] = [(col, row)]
    visited: set[tuple[int, int]] = {(col, row)}

    while len(path) < MAX_STEPS:
        if col == COLS - 1:
            break

        gate = min(COLS - 1, start + span * len(path) // wanted + GATE_SLACK)

        best: tuple[int, int] | None = None
        best_score = float("-inf")
        loose: tuple[int, int] | None = None
        loose_score = float("-inf")
        for dc, dr in NEIGHBOURS:
            nc, nr = col + dc, row + dr
            if not (start <= nc < COLS and 0 <= nr < ROWS):
                continue
            if (nc, nr) in visited:
                continue
            score = (
                lookahead_score(grid, nc, nr, scale)
                + BASE_DRIFT * dc
                + rng.random() * JITTER
            )
            if not _has_escape(visited, nc, nr, start):
                score -= TRAP_PENALTY  # would strand the robot next step
            if score > loose_score:
                loose_score, loose = score, (nc, nr)
            if nc <= gate and score > best_score:
                best_score, best = score, (nc, nr)

        # Ignore the gate rather than stall. If genuinely boxed in, step back
        # onto ground it has already walked: a denser walk traps itself often
        # enough that this fires on real calendars, and retracing a cell is
        # far less jarring than teleporting across the grid. Cells reached this
        # way are not collected twice.
        best = best or loose or _retrace(grid, col, row, path, scale, start, rng)
        col, row = best
        path.append(best)
        visited.add(best)

    return path


def _has_escape(
    visited: set[tuple[int, int]], col: int, row: int, start: int
) -> bool:
    """True if (col, row) still has an unvisited 8-way neighbour.

    Columns left of ``start`` do not count -- the robot never walks there, so
    an "escape" into the dead region is not an escape at all.
    """
    return any(
        start <= col + dc < COLS
        and 0 <= row + dr < ROWS
        and (col + dc, row + dr) not in visited
        for dc, dr in NEIGHBOURS
    )


def _retrace(
    grid: Grid,
    col: int,
    row: int,
    path: Sequence[tuple[int, int]],
    scale: float,
    start: int,
    rng: random.Random,
) -> tuple[int, int]:
    """Best 8-way neighbour when every unvisited one is gone.

    Visited cells are allowed here -- that is the point -- but the cell just
    left is excluded so the robot cannot oscillate between two squares. At
    least two candidates always remain, so this never fails.
    """
    previous = path[-2] if len(path) > 1 else None
    candidates = [
        (col + dc, row + dr)
        for dc, dr in NEIGHBOURS
        if start <= col + dc < COLS and 0 <= row + dr < ROWS
    ]
    fresh = [c for c in candidates if c != previous] or candidates
    return max(
        fresh,
        key=lambda c: (
            lookahead_score(grid, c[0], c[1], scale)
            + BASE_DRIFT * (c[0] - col)
            + rng.random() * JITTER
        ),
    )


def build_word_grid(word: str, end_day: date) -> Grid:
    """A 53x7 grid whose lit cells spell ``word``, centred on the canvas.

    Cells still carry real dates from the same trailing-12-month span the
    contribution calendar uses, so the month and weekday labels render exactly
    as they do in contribution mode and the two SVGs read as a matched pair.
    """
    columns = grid_font.layout(word.upper())
    if len(columns) > COLS:
        raise GeneratorError(
            f"{word!r} needs {len(columns)} columns but the grid is only {COLS} "
            f"wide. Use at most {(COLS + 1) // (grid_font.GLYPH_WIDTH + 1)} letters."
        )
    offset = (COLS - len(columns)) // 2

    # Mirror GitHub's calendar exactly, or the month labels drift out of step
    # with the contribution SVG beside it. GitHub returns *whole* weeks: the
    # first column starts on the Sunday on or before a year ago and is
    # complete, and only the last column is partial, stopping at end_day. That
    # is 370 days for a Friday end date, not 365 -- truncating to exactly a
    # year leaves column 0 with two cells and shifts the first month label.
    last_sunday = end_day - timedelta(days=end_day.isoweekday() % 7)

    grid: Grid = []
    for col in range(COLS):
        sunday = last_sunday - timedelta(days=(COLS - 1 - col) * 7)
        column: list[Cell | None] = []
        for row in range(ROWS):
            day = sunday + timedelta(days=row)
            if day > end_day:
                column.append(None)
                continue
            lit = 0 <= col - offset < len(columns) and columns[col - offset][row]
            column.append(Cell(day=day, count=1 if lit else 0, level=4 if lit else 0))
        grid.append(column)
    return grid


def lit_cells(grid: Grid) -> set[tuple[int, int]]:
    """Every cell the wordmark wants the robot to reach."""
    return {
        (col, row)
        for col in range(COLS)
        for row in range(ROWS)
        if count_at(grid, col, row) > 0
    }


def build_word_path(grid: Grid) -> list[tuple[int, int]]:
    """A connected walk that reaches every lit cell of the wordmark.

    Boustrophedon: work left to right, sweeping each column that contains any
    glyph pixel through its **full height**, alternating direction so the exit
    row of one column is one step from the entry row of the next. Columns with
    nothing in them (the gaps between letters) are crossed at whatever row the
    robot is already on, so the letters cost seven cells each and the gaps cost
    one.

    Sweeping the full height rather than just each column's lit range is what
    makes the coverage a guarantee. A range-only sweep strands the robot
    whenever the previous column's exit row lands *inside* the next column's
    range: it would have to cover cells on both sides of its entry point, and
    the only routes back are through cells it has already walked.

    Fully deterministic -- no RNG -- because the coverage guarantee is the
    point and a seeded tie-break could only weaken it. Cells the robot merely
    passes over are not lit; only glyph cells animate, so the connective walks
    across the gaps do not smear the word.
    """
    targets = lit_cells(grid)
    if not targets:
        return [(0, 0)]

    lit_columns = sorted({col for col, _ in targets})
    first_col, last_col = lit_columns[0], lit_columns[-1]
    lit_set = set(lit_columns)

    row = 0
    path: list[tuple[int, int]] = []

    # Lead-in: walk in from a couple of blank columns, mirroring the
    # contribution version's approach to the first active column.
    for col in range(max(0, first_col - LEAD_IN_COLS), first_col):
        path.append((col, row))

    descending = True
    for col in range(first_col, last_col + 1):
        if col in lit_set:
            rows = range(ROWS) if descending else range(ROWS - 1, -1, -1)
            path.extend((col, r) for r in rows)
            row = ROWS - 1 if descending else 0
            descending = not descending
        else:
            path.append((col, row))  # blank gap: cross it, don't sweep it

    # Lead-out, mirroring the lead-in.
    for col in range(last_col + 1, min(COLS, last_col + 1 + LEAD_IN_COLS)):
        path.append((col, row))

    return path


def build_return_path(
    outbound: Sequence[tuple[int, int]], rng: random.Random
) -> list[tuple[int, int]]:
    """The walk home: right edge back to the start column.

    Deliberately not the outbound route reversed, which reads as mechanical.
    Cells on the outbound path are penalised rather than forbidden, so the
    robot threads fresh ground where it can and crosses its own trail where it
    must. Same 8-way steps and same facing rule as the outbound wander; it
    just does not collect anything.
    """
    target = outbound[0][0]
    col, row = outbound[-1]
    on_outbound = set(outbound)
    visited = {(col, row)}
    path: list[tuple[int, int]] = []

    while col > target and len(path) < MAX_STEPS:
        best: tuple[int, int] | None = None
        best_score = float("-inf")
        for dc, dr in NEIGHBOURS:
            nc, nr = col + dc, row + dr
            if not (target <= nc < COLS and 0 <= nr < ROWS):
                continue
            if (nc, nr) in visited:
                continue
            score = -BASE_DRIFT * dc + rng.random() * JITTER
            if (nc, nr) in on_outbound:
                score -= RETRACE_PENALTY
            if not _has_escape(visited, nc, nr, target):
                score -= TRAP_PENALTY
            if score > best_score:
                best_score, best = score, (nc, nr)
        if best is None:
            break
        col, row = best
        path.append(best)
        visited.add(best)
    return path


def build_timeline(
    grid: Grid, path: Sequence[tuple[int, int]], *, allow_dwell: bool = True
) -> list[Step]:
    """Assign every path cell a slot so the whole walk fills RUN_SECONDS."""
    threshold = dwell_threshold(grid) if allow_dwell else 0
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


@dataclass(frozen=True)
class Timeline:
    """The whole loop: an outbound walk, a turn, a walk home, then a reset."""

    steps: list[Step]
    cycle: float
    reset_at: float
    turn_index: int | None
    outbound_step: float
    return_step: float


def build_round_trip(
    grid: Grid, outbound: Sequence[tuple[int, int]], rng: random.Random
) -> Timeline:
    """Outbound wander, a pause to turn, then the walk home.

    The outbound leg keeps its fixed RUN_SECONDS -- it is never compressed to
    make room. The return leg is sized from the outbound step and then, only if
    the loop would breach MAX_CYCLE_SECONDS, walked faster still.
    """
    steps = build_timeline(grid, outbound, allow_dwell=True)
    outbound_step = min(step.depart - step.arrive for step in steps)
    turn_index = len(steps) - 1

    # The turn: hold at the right edge, flipping facing, before heading back.
    # hold_until must stay strictly below depart. If they are equal, this
    # step's hold keyframe lands on the same percentage as the next step's
    # arrival keyframe, the later declaration wins, and the robot slides off
    # the edge during its pause instead of standing still.
    last = steps[turn_index]
    turn_depart = last.depart + TURN_SECONDS
    steps[turn_index] = Step(
        col=last.col,
        row=last.row,
        count=last.count,
        dwell=last.dwell,
        arrive=last.arrive,
        hold_until=turn_depart - outbound_step * MOVE_FRACTION,
        depart=turn_depart,
    )

    home = build_return_path(outbound, rng)
    return_step = outbound_step / RETURN_SPEEDUP
    if home:
        budget = (
            MAX_CYCLE_SECONDS
            - RUN_SECONDS
            - TURN_SECONDS
            - ARRIVAL_SECONDS
            - RESET_SECONDS
        )
        return_step = min(return_step, budget / len(home))

    move = return_step * MOVE_FRACTION
    t = steps[turn_index].depart
    for index, (col, row) in enumerate(home):
        slot = return_step + (ARRIVAL_SECONDS if index == len(home) - 1 else 0.0)
        hold = t + (slot if index == len(home) - 1 else max(slot - move, slot * 0.15))
        steps.append(
            Step(
                col=col,
                row=row,
                count=count_at(grid, col, row),
                dwell=False,
                arrive=t,
                hold_until=hold,
                depart=t + slot,
                collecting=False,  # walking home, not re-harvesting
            )
        )
        t += slot

    reset_at = steps[-1].depart
    return Timeline(
        steps=steps,
        cycle=reset_at + RESET_SECONDS,
        reset_at=reset_at,
        turn_index=turn_index,
        outbound_step=outbound_step,
        return_step=return_step,
    )


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


def build_pose_segments(
    steps: Sequence[Step], cycle: float, turn_index: int | None = None
) -> list[tuple[float, float, str, int]]:
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

    for index, (step, facing) in enumerate(zip(steps, facings)):
        if index == turn_index:
            # Arrive facing the way it was going, stand still, then turn round
            # halfway through the pause and set off home.
            middle = (step.arrive + step.hold_until) / 2.0
            segments.append((step.arrive, middle, "stand", 1))
            segments.append((middle, step.hold_until, "stand", -1))
            alternate(step.hold_until, step.depart, facing)
        elif step.dwell:
            segments.append((step.arrive, step.hold_until, "grab", facing))
            alternate(step.hold_until, step.depart, facing)
        else:
            alternate(step.arrive, step.depart, facing)

    # Settle: stand still until the cycle resets.
    segments.append((steps[-1].depart, cycle, "stand", facings[-1]))

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


def pct(seconds: float, cycle: float) -> str:
    """Seconds on the cycle timeline -> a keyframe percentage."""
    value = max(0.0, min(100.0, seconds / cycle * 100.0))
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


def opacity_keyframes(
    name: str, windows: Sequence[tuple[float, float]], cycle: float
) -> str:
    """Show the element only during ``windows``; base opacity is 0.

    Paired with ``animation-timing-function: steps(1, end)`` so each stop holds
    its value until the next one rather than cross-fading.
    """
    parts: list[str] = []
    if not windows or windows[0][0] > 0.0:
        parts.append("0%{opacity:0}")
    for start, end in windows:
        parts.append(f"{pct(start, cycle)}{{opacity:1}}")
        if end < cycle:
            parts.append(f"{pct(end, cycle)}{{opacity:0}}")
    if not windows or windows[-1][1] < cycle:
        parts.append("100%{opacity:0}")
    return f"@keyframes {name}{{" + "".join(parts) + "}"


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def render_style(
    steps: Sequence[Step],
    collected: Sequence[tuple[int, Step, int]],
    mode: RenderMode = CONTRIBUTION_MODE,
    cycle: float = WORDMARK_CYCLE,
    reset_at: float | None = None,
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
    outline = (
        "stroke:var(--collected-edge);stroke-width:1;stroke-opacity:0;"
        if mode.outline
        else ""
    )
    lines.append(
        f".col{{{outline}"
        f"animation-duration:{num(cycle)}s;animation-iteration-count:infinite;"
        "animation-timing-function:ease-out}"
    )
    lines.append(
        f".lbl{{fill:var(--label);font:400 9px {FONT}}}"
        f".pre{{fill:var(--label);font:400 10px {FONT};letter-spacing:.4px}}"
    )
    lines.append(
        f".cv{{fill:var(--counter);font:700 15px {FONT};opacity:0;"
        f"animation-duration:{num(cycle)}s;animation-iteration-count:infinite;"
        "animation-timing-function:steps(1,end)}"
    )
    lines.append(
        f".p{{fill:var(--counter);opacity:0;animation:fly {num(cycle)}s "
        "linear infinite}"
    )
    lines.append(
        f".robot{{animation:walk {num(cycle)}s linear infinite}}"
        f".rp{{opacity:0;animation-duration:{num(cycle)}s;"
        "animation-iteration-count:infinite;animation-timing-function:steps(1,end)}"
    )

    # Particles: one shared flight, aimed per element via --dx/--dy.
    lines.append(
        "@keyframes fly{0%{opacity:1;transform:translate(0,0)}"
        f"{pct(PARTICLE_SECONDS, cycle)}{{opacity:0;"
        "transform:translate(var(--dx),var(--dy))}"
        "100%{opacity:0;transform:translate(var(--dx),var(--dy))}}"
    )

    # Robot: an explicit keyframe pair per waypoint, so dwells read as a held
    # position rather than an eased slowdown.
    walk: list[str] = []
    for step in steps:
        x, y = cell_centre(step.col, step.row)
        position = f"transform:translate({num(x)}px,{num(y)}px)"
        walk.append(f"{pct(step.arrive, cycle)}{{{position}}}")
        if step.hold_until > step.arrive:
            walk.append(f"{pct(step.hold_until, cycle)}{{{position}}}")
    last = steps[-1]
    lx, ly = cell_centre(last.col, last.row)
    walk.append(f"100%{{transform:translate({num(lx)}px,{num(ly)}px)}}")
    lines.append("@keyframes walk{" + "".join(walk) + "}")

    # Cells: empty -> collected on arrival, held through the settle, then reset.
    # The idle colour has to be named explicitly: `fill: inherit` would take
    # the parent group's fill (black) rather than the cell's own level class,
    # because an animation overrides the class for the whole cycle.
    reset_start = mode.reset_at if reset_at is None else reset_at
    reset_end = min(cycle, reset_start + RESET_SECONDS)
    edge_off, edge_on = ("stroke-opacity:0", "stroke-opacity:1") if mode.outline else ("", "")
    for index, step, level in collected:
        idle = "var(--empty)" if level == 0 else f"var(--l{level})"
        flip = min(step.arrive + COLLECT_SECONDS, reset_start)
        lines.append(
            f"@keyframes k{index}{{"
            f"0%,{pct(step.arrive, cycle)}{{fill:{idle}"
            f"{';' + edge_off if edge_off else ''}}}"
            f"{pct(flip, cycle)},{pct(reset_start, cycle)}{{fill:{mode.collect_fill}"
            f"{';' + edge_on if edge_on else ''}}}"
            f"{pct(reset_end, cycle)},100%{{fill:{idle}"
            f"{';' + edge_off if edge_off else ''}}}}}"
        )
    return "\n".join(lines)


def render_robot(
    steps: Sequence[Step], cycle: float, turn_index: int | None = None
) -> tuple[str, str]:
    """The robot group plus the keyframes driving its pose swaps."""
    segments = build_pose_segments(steps, cycle, turn_index)

    windows: dict[tuple[str, int], list[tuple[float, float]]] = {}
    for start, end, pose, facing in segments:
        windows.setdefault((pose, facing), []).append((start, end))

    uses: list[str] = []
    keyframes: list[str] = []
    for index, ((pose, facing), spans) in enumerate(sorted(windows.items())):
        name = f"rp{index}"
        keyframes.append(opacity_keyframes(name, spans, cycle))
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


def render_svg(
    grid: Grid, username: str, year_total: int, word: str | None = None
) -> str:
    mode = WORDMARK_MODE if word else CONTRIBUTION_MODE

    if word:
        # Deterministic serpentine, so every letter cell is reached. No return
        # leg here: the payoff is the finished word, held and then reset.
        steps = build_timeline(grid, build_word_path(grid), allow_dwell=False)
        cycle, reset_at, turn_index = WORDMARK_CYCLE, mode.reset_at, None
    else:
        rng = random.Random(grid_end_date(grid).isoformat())
        trip = build_round_trip(grid, build_path(grid, rng), rng)
        steps, cycle = trip.steps, trip.cycle
        reset_at, turn_index = trip.reset_at, trip.turn_index

    def level_at(col: int, row: int) -> int:
        cell = grid[col][row]
        return cell.level if cell else 0

    # In wordmark mode only glyph cells animate. The robot walks the gaps
    # between letters, but lighting those up would smear the word.
    # Only the outbound leg collects; the walk home leaves everything as it
    # found it. In wordmark mode only glyph cells count.
    seen: set[tuple[int, int]] = set()
    collected: list[tuple[int, Step, int]] = []
    for index, step in enumerate(steps):
        if not step.collecting or (word and step.count <= 0):
            continue
        if (step.col, step.row) in seen:
            continue  # retraced cell: collect once, on first arrival
        seen.add((step.col, step.row))
        collected.append((index, step, 0 if word else level_at(step.col, step.row)))
    step_by_position = {(step.col, step.row): index for index, step, _ in collected}

    # Counter windows: the value only changes when a cell with commits is hit.
    counter_x = GRID_X + COUNTER_NUM_DX
    particles: list[str] = []
    values: list[int] = [0]
    starts: list[float] = [0.0]
    running = 0
    for _, step, _level in collected if mode.counter else ():
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

    # The final value holds to the end of the cycle, so the counter stays put
    # while the robot walks home.
    counter_windows = (
        [
            (start, starts[i + 1] if i + 1 < len(starts) else cycle)
            for i, start in enumerate(starts)
        ]
        if mode.counter
        else []
    )

    robot, pose_keyframes = render_robot(steps, cycle, turn_index)
    style = "\n".join(
        [
            render_style(steps, collected, mode, cycle, reset_at),
            "\n".join(
                opacity_keyframes(f"v{i}", [window], cycle)
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
            # Wordmark cells all start dark; the robot is what lights them.
            level = 0 if word else (cell.level if cell else 0)
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
    # Dropped in wordmark mode: there are no contributions, and a number
    # ticking up on decorative cells would be misleading.
    counter: list[str] = []
    if mode.counter:
        counter.append(
            f'<text class="pre" x="{num(GRID_X)}" y="{num(COUNTER_Y)}">'
            f"commits collected</text>"
        )
        counter += [
            f'<text class="cv" x="{num(counter_x)}" y="{num(COUNTER_Y)}" '
            f'style="animation-name:v{i}">{value:,}</text>'
            for i, value in enumerate(values)
        ]

    safe_user = escape(username)
    if word:
        safe_word = escape(word.upper())
        title = f"{safe_word} drawn by a contribution robot"
        desc = (
            f"A contribution-grid wordmark spelling {safe_word}. A small robot "
            f"walks {len(steps)} cells over {num(RUN_SECONDS)} seconds, lighting "
            f"all {len(collected)} letter cells as it reaches them, then the "
            "animation resets and repeats."
        )
    else:
        title = f"{safe_user}&#8217;s contribution robot"
        desc = (
            f"An animated GitHub contribution grid for {safe_user}. "
            f"The year&#8217;s total is {year_total:,} contributions. "
            f"A small robot wanders {len(collected)} of the {COLS * ROWS} cells "
            f"and collects {values[-1]:,} contributions over "
            f"{num(RUN_SECONDS)} seconds, then walks back to where it started "
            f"before the animation resets and repeats every {num(cycle)} "
            "seconds."
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
    parser.add_argument(
        "--word",
        default=None,
        help=(
            "Draw a wordmark (A-Z and space) instead of contribution data. "
            "Skips the API entirely; the robot lights the letters as it walks."
        ),
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
    payload: dict[str, Any] = {}
    live = False
    try:
        if args.word:
            # No contribution data is involved, so the API is skipped entirely.
            grid = build_word_grid(args.word, datetime.now(tz=UTC).date())
            svg = render_svg(grid, args.username, 0, word=args.word)
        else:
            payload, live = load_payload(args)
            weeks, year_total = extract_weeks(payload)
            grid = build_grid(weeks)
            svg = render_svg(grid, args.username, year_total)
    except grid_font.UnsupportedCharacter as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_DATA
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
