"""Tests for the contribution-robot SVG generator."""

from __future__ import annotations

import json
import random
import re
import sys
from itertools import pairwise
from pathlib import Path
from xml.etree import ElementTree

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import generate_robot_svg as gen
import robot_sprite as sprite

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "sample_calendar.json"
LATE_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "late_start_calendar.json"


def _grid(path: Path) -> gen.Grid:
    weeks, _ = gen.extract_weeks(json.loads(path.read_text(encoding="utf-8")))
    return gen.build_grid(weeks)


def _walk(grid: gen.Grid) -> list[tuple[int, int]]:
    return gen.build_path(grid, random.Random(gen.grid_end_date(grid).isoformat()))


def _empty_grid(active_from: int | None) -> gen.Grid:
    """A grid whose columns before ``active_from`` have no contributions."""
    weeks = [
        {
            "contributionDays": [
                {
                    "date": "2024-01-07",
                    "contributionCount": (
                        0 if active_from is None or col < active_from else col + 1
                    ),
                    "weekday": row,
                }
                for row in range(7)
            ]
        }
        for col in range(gen.COLS)
    ]
    return gen.build_grid(weeks)


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def grid(payload: dict) -> gen.Grid:
    weeks, _ = gen.extract_weeks(payload)
    return gen.build_grid(weeks)


@pytest.fixture(scope="module")
def svg(grid: gen.Grid, payload: dict) -> str:
    _, total = gen.extract_weeks(payload)
    return gen.render_svg(grid, "merna-s-saad", total)


# ---------------------------------------------------------------- normalising


def test_grid_is_always_53_by_7(grid: gen.Grid) -> None:
    assert len(grid) == gen.COLS
    assert all(len(column) == gen.ROWS for column in grid)


def test_partial_weeks_are_padded_not_skipped(grid: gen.Grid, payload: dict) -> None:
    """The fixture's first week starts on a Thursday and its last ends Friday."""
    weeks, _ = gen.extract_weeks(payload)
    first_weekday = weeks[0]["contributionDays"][0]["weekday"]
    last_weekday = weeks[-1]["contributionDays"][-1]["weekday"]
    assert first_weekday > 0 and last_weekday < 6, "fixture must have partial weeks"

    # Leading gap is empty, and the real days sit on their true weekday rows.
    assert all(grid[0][row] is None for row in range(first_weekday))
    assert all(grid[0][row] is not None for row in range(first_weekday, gen.ROWS))
    assert all(grid[-1][row] is None for row in range(last_weekday + 1, gen.ROWS))

    # Every real day survived normalisation.
    day_count = sum(len(week["contributionDays"]) for week in weeks)
    kept = sum(1 for column in grid for cell in column if cell is not None)
    assert kept == day_count


def test_grid_keeps_the_most_recent_weeks_when_the_api_sends_extra() -> None:
    weeks = [
        {
            "contributionDays": [
                {
                    "date": f"2024-01-{(index % 28) + 1:02d}",
                    "contributionCount": index,
                    "weekday": row,
                }
                for row in range(7)
            ]
        }
        for index in range(60)
    ]
    grid = gen.build_grid(weeks)
    assert len(grid) == gen.COLS
    assert grid[-1][0].count == 59  # last week retained


def test_grid_pads_short_calendars_on_the_left() -> None:
    weeks = [
        {
            "contributionDays": [
                {"date": "2024-05-06", "contributionCount": 1, "weekday": 0}
            ]
        }
    ]
    grid = gen.build_grid(weeks)
    assert len(grid) == gen.COLS
    assert all(cell is None for column in grid[:-1] for cell in column)


def test_levels_span_the_palette(grid: gen.Grid) -> None:
    levels = {cell.level for column in grid for cell in column if cell}
    assert levels == {0, 1, 2, 3, 4}


# --------------------------------------------------------------------- path


def test_path_is_a_valid_non_repeating_walk(grid: gen.Grid) -> None:
    rng = random.Random(gen.grid_end_date(grid).isoformat())
    path = gen.build_path(grid, rng)

    assert len(path) == len(set(path)), "the robot must never revisit a cell"
    assert path[0][0] == 0, "starts at the left edge"
    assert path[-1][0] == gen.COLS - 1, "crosses to the right edge"
    assert all(0 <= c < gen.COLS and 0 <= r < gen.ROWS for c, r in path)


def test_path_is_eight_way_connected(grid: gen.Grid) -> None:
    rng = random.Random(gen.grid_end_date(grid).isoformat())
    path = gen.build_path(grid, rng)
    for (c1, r1), (c2, r2) in pairwise(path):
        assert max(abs(c2 - c1), abs(r2 - r1)) == 1, "steps must be 8-way neighbours"


def test_path_wanders_rather_than_sweeping(grid: gen.Grid) -> None:
    rng = random.Random(gen.grid_end_date(grid).isoformat())
    path = gen.build_path(grid, rng)
    backtracks = sum(1 for (c1, _), (c2, _) in pairwise(path) if c2 <= c1)
    assert backtracks > 0, "a pure left-to-right sweep is not a wander"
    assert len(path) > gen.COLS, "a wander is longer than a straight march"

    vertical = sum(1 for (_, r1), (_, r2) in pairwise(path) if r1 != r2)
    assert vertical > len(path) // 3, "should move up and down, not just across"
    # Not every row -- the fixture's weekends are empty, and a robot chasing
    # contributions is right to ignore them.
    assert len({r for _, r in path}) >= 5


def test_path_is_deterministic_for_the_same_calendar(grid: gen.Grid) -> None:
    seed = gen.grid_end_date(grid).isoformat()
    first = gen.build_path(grid, random.Random(seed))
    second = gen.build_path(grid, random.Random(seed))
    assert first == second


def test_render_is_byte_identical_across_runs(grid: gen.Grid) -> None:
    assert gen.render_svg(grid, "merna-s-saad", 742) == gen.render_svg(
        grid, "merna-s-saad", 742
    )


# ------------------------------------------------------------- start column


@pytest.mark.parametrize("active_from", [0, 1, 2, 3, 14, 30])
def test_start_backs_up_two_columns_from_the_first_active_one(
    active_from: int,
) -> None:
    grid = _empty_grid(active_from)
    assert gen.first_active_column(grid) == active_from
    assert gen.start_column(grid) == max(0, active_from - gen.LEAD_IN_COLS)


def test_a_completely_empty_grid_falls_back_to_column_zero() -> None:
    grid = _empty_grid(None)
    assert gen.first_active_column(grid) is None
    assert gen.start_column(grid) == 0


def test_walk_never_enters_the_dead_region() -> None:
    grid = _grid(LATE_FIXTURE)
    start = gen.start_column(grid)
    assert start > 0, "fixture must have a dead lead-in"
    path = _walk(grid)
    assert path[0][0] == start
    assert min(col for col, _ in path) == start, "nothing left of the start"
    assert path[-1][0] == gen.COLS - 1, "still crosses to the right edge"


def test_dead_columns_still_render_as_normal_cells() -> None:
    grid = _grid(LATE_FIXTURE)
    svg = gen.render_svg(grid, "merna-s-saad", 818)
    start = gen.start_column(grid)
    for col in range(start):
        assert f'x="{gen.num(gen.cell_x(col))}"' in svg
    # ...but none of them is animated, because the robot never lands there.
    steps = gen.build_timeline(grid, _walk(grid))
    assert all(step.col >= start for step in steps)
    assert svg.count(" col\"") == len(steps)


def test_shorter_span_walks_fewer_cells_at_a_slower_pace() -> None:
    full, late = _grid(FIXTURE), _grid(LATE_FIXTURE)
    assert gen.start_column(full) == 0 and gen.start_column(late) > 0

    def base_step(grid: gen.Grid) -> float:
        steps = gen.build_timeline(grid, _walk(grid))
        normal = next(step for step in steps if not step.dwell)
        return normal.depart - normal.arrive

    assert len(_walk(late)) < len(_walk(full)), "shorter span, fewer cells"
    assert base_step(late) > base_step(full), "and a more deliberate pace"


def test_target_cells_scales_with_the_span_and_has_a_floor() -> None:
    # A full-width calendar reproduces the original tuning exactly.
    assert gen.target_cells(0) == gen.MIN_CELLS
    assert gen.target_cells(20) < gen.target_cells(0)
    # A tiny active region does not collapse to a handful of very long steps.
    assert gen.target_cells(gen.COLS - 3) >= min(
        gen.MIN_CELLS_FLOOR, 3 * gen.ROWS
    )


def test_late_start_render_still_meets_every_budget() -> None:
    grid = _grid(LATE_FIXTURE)
    steps = gen.build_timeline(grid, _walk(grid))
    assert 20.0 <= steps[-1].depart <= 25.0
    svg = gen.render_svg(grid, "merna-s-saad", 818)
    assert "<script" not in svg.lower()
    assert len(svg.encode("utf-8")) < 150_000
    assert gen.render_svg(grid, "merna-s-saad", 818) == svg, "still deterministic"


# ------------------------------------------------------------------- timing


def test_walk_runs_between_20_and_25_seconds(grid: gen.Grid) -> None:
    rng = random.Random(gen.grid_end_date(grid).isoformat())
    steps = gen.build_timeline(grid, gen.build_path(grid, rng))
    assert 20.0 <= steps[-1].depart <= 25.0
    assert steps[-1].depart == pytest.approx(gen.RUN_SECONDS)


def test_timeline_slots_are_contiguous_and_ordered(grid: gen.Grid) -> None:
    rng = random.Random(gen.grid_end_date(grid).isoformat())
    steps = gen.build_timeline(grid, gen.build_path(grid, rng))
    assert steps[0].arrive == 0.0
    for current, following in pairwise(steps):
        assert current.depart == pytest.approx(following.arrive)
        assert current.arrive <= current.hold_until <= current.depart


def test_top_quartile_cells_dwell_about_three_times_longer(grid: gen.Grid) -> None:
    rng = random.Random(gen.grid_end_date(grid).isoformat())
    steps = gen.build_timeline(grid, gen.build_path(grid, rng))
    dwells = [s for s in steps if s.dwell]
    normal = [s for s in steps if not s.dwell]
    assert dwells and normal, "the fixture should produce both kinds of step"

    threshold = gen.dwell_threshold(grid)
    assert all(step.count >= threshold for step in dwells)
    dwell_slot = dwells[0].depart - dwells[0].arrive
    normal_slot = normal[0].depart - normal[0].arrive
    assert dwell_slot == pytest.approx(3.0 * normal_slot)


def test_pose_segments_tile_the_cycle_without_overlap(grid: gen.Grid) -> None:
    rng = random.Random(gen.grid_end_date(grid).isoformat())
    steps = gen.build_timeline(grid, gen.build_path(grid, rng))
    segments = gen.build_pose_segments(steps)

    assert segments[0][0] == 0.0
    assert segments[-1][1] == pytest.approx(gen.CYCLE_SECONDS)
    for current, following in pairwise(segments):
        assert current[1] == pytest.approx(following[0]), "exactly one pose at a time"
    assert {pose for _, _, pose, _ in segments} == {"stand", "step", "grab"}
    assert {facing for *_, facing in segments} <= {-1, 1}


def test_grab_pose_covers_every_dwell_beat(grid: gen.Grid) -> None:
    rng = random.Random(gen.grid_end_date(grid).isoformat())
    steps = gen.build_timeline(grid, gen.build_path(grid, rng))
    grabs = [(s, e) for s, e, pose, _ in gen.build_pose_segments(steps) if pose == "grab"]
    for step in (s for s in steps if s.dwell):
        assert any(
            start <= step.arrive + 1e-9 and end >= step.hold_until - 1e-9
            for start, end in grabs
        ), "the grab pose must start when the particle launches"


def test_robot_turns_around_when_the_path_goes_left(grid: gen.Grid) -> None:
    rng = random.Random(gen.grid_end_date(grid).isoformat())
    steps = gen.build_timeline(grid, gen.build_path(grid, rng))
    facings = gen.build_facings(steps)
    for index, step in enumerate(steps[:-1]):
        delta = steps[index + 1].col - step.col
        if delta < 0:
            assert facings[index] == -1
        elif delta > 0:
            assert facings[index] == 1


# ------------------------------------------------------------------- sprite


def test_all_six_symbols_are_defined() -> None:
    for symbol_id in (
        "robot-stand",
        "robot-step",
        "robot-grab",
        "robot-mini",
        "robot-mini-step",
        "robot-mini-grab",
    ):
        assert f'id="{symbol_id}"' in sprite.ROBOT_DEFS


def test_symbols_share_one_viewbox_and_origin() -> None:
    viewboxes = re.findall(r'viewBox="([^"]+)"', sprite.ROBOT_DEFS)
    assert len(viewboxes) == 6
    assert set(viewboxes) == {"-20 -8 40 72"}


def test_sprite_uses_css_variables_not_literal_hex() -> None:
    assert not re.search(r"#[0-9A-Fa-f]{3,6}\b", sprite.ROBOT_DEFS)
    for variable in ("--robot-body", "--robot-visor", "--robot-eye"):
        assert f"var({variable})" in sprite.ROBOT_DEFS


def test_mini_symbols_drop_the_chest_panel_and_thicken_strokes() -> None:
    mini = sprite.ROBOT_DEFS[sprite.ROBOT_DEFS.index('id="robot-mini"') :]
    mini = mini[: mini.index("</symbol>")]
    assert 'y="31"' not in mini, "chest panel must be gone at small sizes"
    assert 'stroke-width="2"' in mini
    assert 'stroke-width="1.2"' not in mini and 'stroke-width="1.4"' not in mini
    # ...but the detailed stand pose keeps it.
    detailed = sprite.ROBOT_DEFS[: sprite.ROBOT_DEFS.index("</symbol>")]
    assert 'y="31"' in detailed


def test_facing_left_mirrors_in_place_and_never_flips_vertically() -> None:
    right = sprite.robot_use(100.0, 50.0, 1)
    left = sprite.robot_use(100.0, 50.0, -1)
    assert "scale(-1 1)" in left and "scale" not in right
    assert "scale(1 -1)" not in left
    # Same box: the sprite is symmetric about its own centre.
    box = re.compile(r'x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="([\d.]+)"')
    assert box.search(right).groups() == box.search(left).groups()


def test_robot_use_centres_the_sprite_on_the_given_point() -> None:
    markup = sprite.robot_use(100.0, 50.0, 1)
    x = float(re.search(r' x="([-\d.]+)"', markup).group(1))
    y = float(re.search(r' y="([-\d.]+)"', markup).group(1))
    assert x + sprite.SPRITE_WIDTH / 2 == pytest.approx(100.0, abs=0.01)
    assert y + sprite.SPRITE_HEIGHT / 2 == pytest.approx(50.0, abs=0.01)


# ---------------------------------------------------------------------- svg


def test_svg_stacks_one_use_per_pose_and_facing(svg: str, grid: gen.Grid) -> None:
    rng = random.Random(gen.grid_end_date(grid).isoformat())
    steps = gen.build_timeline(grid, gen.build_path(grid, rng))
    keys = {(pose, facing) for _, _, pose, facing in gen.build_pose_segments(steps)}
    assert svg.count('class="rp"') == len(keys)
    for index in range(len(keys)):
        assert f"@keyframes rp{index}{{" in svg


def test_leftward_travel_mirrors_the_sprite(svg: str, grid: gen.Grid) -> None:
    rng = random.Random(gen.grid_end_date(grid).isoformat())
    path = gen.build_path(grid, rng)
    assert any(c2 < c1 for (c1, _), (c2, _) in pairwise(path)), "fixture must backtrack"
    assert "scale(-1 1)" in svg
    assert "scale(1 -1)" not in svg, "never flip vertically"


def test_svg_is_well_formed_xml(svg: str) -> None:
    root = ElementTree.fromstring(svg)
    assert root.tag.endswith("svg")


def test_svg_scales_to_its_container(svg: str) -> None:
    header = svg[: svg.index(">") + 1]
    assert "viewBox=" in header
    assert " width=" not in header and " height=" not in header


def test_svg_carries_no_javascript(svg: str) -> None:
    lowered = svg.lower()
    assert "<script" not in lowered
    assert "javascript:" not in lowered
    assert not re.search(r"\son\w+=", lowered), "no inline event handlers"


def test_svg_is_accessible(svg: str) -> None:
    assert "<title" in svg and "<desc" in svg
    assert 'role="img"' in svg
    assert "742" in svg, "the desc should quote the year's total"


def test_palette_is_defined_once_as_custom_properties(svg: str) -> None:
    style = svg[svg.index("<style>") : svg.index("</style>")]
    for key, value in gen.PALETTE.items():
        assert f"--{key}:{value}" in style
    # Colours are referenced through the variables, not repeated as hex.
    body = svg[svg.index("</style>") :]
    assert not re.search(r"#[0-9A-Fa-f]{6}", body)


def test_every_visited_cell_animates_and_nothing_else_does(
    svg: str, grid: gen.Grid
) -> None:
    rng = random.Random(gen.grid_end_date(grid).isoformat())
    steps = gen.build_timeline(grid, gen.build_path(grid, rng))
    assert svg.count('class="l0 col"') + sum(
        svg.count(f'class="l{level} col"') for level in range(1, 5)
    ) == len(steps)
    for index in range(len(steps)):
        assert f"@keyframes k{index}{{" in svg
        assert f"animation-name:k{index}" in svg


def test_counter_is_a_stack_of_cumulative_values(svg: str) -> None:
    assert "commits collected" in svg
    values = [
        int(value.replace(",", ""))
        for value in re.findall(r'style="animation-name:v\d+">([\d,]+)</text>', svg)
    ]
    assert values[0] == 0
    assert values == sorted(values), "the counter only ever goes up"
    assert len(set(values)) == len(values)


def test_one_particle_per_scoring_cell(svg: str, grid: gen.Grid) -> None:
    rng = random.Random(gen.grid_end_date(grid).isoformat())
    steps = gen.build_timeline(grid, gen.build_path(grid, rng))
    scoring = [step for step in steps if step.count > 0]
    assert svg.count('class="p"') == len(scoring)
    for step in scoring:
        assert f"animation-delay:{gen.num(step.arrive)}s" in svg


def test_animations_share_one_duration_so_delays_stay_in_lockstep(svg: str) -> None:
    durations = set(re.findall(r"animation-duration:([\d.]+)s", svg))
    inline = set(re.findall(r"animation:\w+ ([\d.]+)s", svg))
    assert durations | inline == {gen.num(gen.CYCLE_SECONDS)}


def test_animation_loops_forever(svg: str) -> None:
    assert svg.count("animation-iteration-count:infinite") + svg.count(
        " infinite"
    ) >= 5


# ---------------------------------------------------------------------- cli


def test_cli_renders_from_a_fixture_without_touching_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("--fixture must not hit the API")

    monkeypatch.setattr(gen, "fetch_calendar", explode)
    out = tmp_path / "dist" / "robot.svg"
    code = gen.main(
        [
            "--username",
            "merna-s-saad",
            "--fixture",
            str(FIXTURE),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    assert out.is_file()
    assert not (out.parent / "last_fetch.json").exists()


def test_output_stays_under_the_150kb_budget(tmp_path: Path) -> None:
    out = tmp_path / "robot.svg"
    gen.main(
        ["--username", "merna-s-saad", "--fixture", str(FIXTURE), "--out", str(out)]
    )
    size = out.stat().st_size
    assert size < 150_000, f"{size} bytes exceeds the budget"


def test_missing_token_fails_with_a_clear_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    code = gen.main(
        ["--username", "merna-s-saad", "--out", str(tmp_path / "robot.svg")]
    )
    assert code == gen.EXIT_NO_TOKEN
    assert "token" in capsys.readouterr().err.lower()


def test_missing_fixture_fails_clearly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = gen.main(
        [
            "--username",
            "merna-s-saad",
            "--fixture",
            str(tmp_path / "nope.json"),
            "--out",
            str(tmp_path / "robot.svg"),
        ]
    )
    assert code == gen.EXIT_DATA
    assert "not found" in capsys.readouterr().err.lower()


@pytest.mark.parametrize(
    ("bad_payload", "fragment"),
    [
        ({"errors": [{"message": "Bad credentials"}]}, "weeks"),
        ({"data": {"user": None}}, "no user"),
        ({"data": {"user": {"contributionsCollection": {}}}}, "weeks"),
    ],
)
def test_bad_api_payloads_raise_a_readable_error(
    bad_payload: dict, fragment: str
) -> None:
    with pytest.raises(gen.GeneratorError) as excinfo:
        gen.extract_weeks(bad_payload)
    assert fragment in str(excinfo.value).lower()


def test_empty_calendar_is_rejected() -> None:
    with pytest.raises(gen.GeneratorError, match="empty"):
        gen.extract_weeks({"weeks": []})


def test_zero_contribution_year_still_renders() -> None:
    weeks = [
        {
            "contributionDays": [
                {"date": "2024-01-07", "contributionCount": 0, "weekday": row}
                for row in range(7)
            ]
        }
    ] * 53
    grid = gen.build_grid(weeks)
    assert gen.dwell_threshold(grid) == 0
    svg = gen.render_svg(grid, "nobody", 0)
    assert "<script" not in svg
    assert 'style="animation-name:v0">0</text>' in svg
