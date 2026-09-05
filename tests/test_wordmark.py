"""Tests for the 5x7 grid font and the generator's wordmark mode."""

from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path
from xml.etree import ElementTree

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import generate_robot_svg as gen
import grid_font

# Fixed so the calendar dates -- and therefore the whole render -- are stable.
END_DAY = date(2026, 9, 4)

# Exactly as specified in the brief.
MERNA = {
    "M": ["10001", "11011", "10101", "10001", "10001", "10001", "10001"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
}


@pytest.fixture(scope="module")
def grid() -> gen.Grid:
    return gen.build_word_grid("MERNA", END_DAY)


@pytest.fixture(scope="module")
def svg(grid: gen.Grid) -> str:
    return gen.render_svg(grid, "merna-s-saad", 0, word="MERNA")


# ---------------------------------------------------------------------- font


def test_merna_glyphs_are_exactly_as_specified() -> None:
    for char, rows in MERNA.items():
        assert grid_font.GLYPHS[char] == rows


def test_every_letter_and_space_is_defined_at_five_by_seven() -> None:
    expected = {chr(code) for code in range(ord("A"), ord("Z") + 1)} | {" "}
    assert set(grid_font.GLYPHS) == expected
    for char, rows in grid_font.GLYPHS.items():
        assert len(rows) == grid_font.GLYPH_HEIGHT, char
        assert all(len(row) == grid_font.GLYPH_WIDTH for row in rows), char
        assert set("".join(rows)) <= {"0", "1"}, char


def test_glyphs_stay_inside_the_five_column_box() -> None:
    """Every letter touches its first column, so the weight reads evenly."""
    for char, rows in grid_font.GLYPHS.items():
        if char == " ":
            continue
        assert any("1" in row for row in rows), char


def test_layout_separates_letters_by_one_blank_column_and_none_at_the_ends() -> None:
    columns = grid_font.layout("ME")
    assert len(columns) == grid_font.width("ME") == 11
    assert any(columns[0]) and any(columns[-1]), "no padding at the ends"
    assert not any(columns[grid_font.GLYPH_WIDTH]), "one blank column between"
    # The M half matches the glyph, transposed.
    for col in range(grid_font.GLYPH_WIDTH):
        for row in range(grid_font.GLYPH_HEIGHT):
            assert columns[col][row] == (MERNA["M"][row][col] == "1")


@pytest.mark.parametrize(("word", "cols"), [("A", 5), ("ME", 11), ("MERNA", 29)])
def test_width_matches_the_layout(word: str, cols: int) -> None:
    assert grid_font.width(word) == cols == len(grid_font.layout(word))


def test_layout_is_case_insensitive_and_handles_the_empty_word() -> None:
    assert grid_font.layout("merna") == grid_font.layout("MERNA")
    assert grid_font.layout("") == []


def test_unsupported_characters_are_rejected() -> None:
    with pytest.raises(grid_font.UnsupportedCharacter, match="No glyph"):
        grid_font.layout("MERNA!")


# ---------------------------------------------------------------------- grid


def test_word_grid_is_the_same_shape_as_a_contribution_grid(grid: gen.Grid) -> None:
    assert len(grid) == gen.COLS
    assert all(len(column) == gen.ROWS for column in grid)


def test_word_is_centred_on_the_canvas(grid: gen.Grid) -> None:
    columns = sorted({col for col, _ in gen.lit_cells(grid)})
    width = grid_font.width("MERNA")
    expected = (gen.COLS - width) // 2
    assert columns[0] == expected
    assert columns[-1] <= expected + width - 1
    left, right = expected, gen.COLS - (expected + width)
    assert abs(left - right) <= 1, "centred to within a column"


def test_lit_cells_spell_the_word(grid: gen.Grid) -> None:
    columns = grid_font.layout("MERNA")
    offset = (gen.COLS - len(columns)) // 2
    for col in range(gen.COLS):
        for row in range(gen.ROWS):
            inside = 0 <= col - offset < len(columns)
            expected = inside and columns[col - offset][row]
            assert (gen.count_at(grid, col, row) > 0) is bool(expected), (col, row)
    assert len(gen.lit_cells(grid)) == 88


def test_word_grid_matches_githubs_calendar_span(grid: gen.Grid) -> None:
    """Whole weeks, exactly as the API returns them.

    GitHub does not truncate at exactly one year: the first column starts on
    the Sunday on or before a year ago and is *complete*, and only the last
    column is partial. Truncating to 365 days leaves column 0 with two cells
    and shifts the first month label, which is precisely the drift this mode
    exists to avoid.
    """
    assert gen.grid_end_date(grid) == END_DAY
    days = [cell.day for column in grid for cell in column if cell]
    assert max(days) == END_DAY

    # Column 0 is a full week; only the final column is cut short.
    assert all(cell is not None for cell in grid[0])
    assert all(cell is not None for column in grid[:-1] for cell in column)
    assert grid[-1][END_DAY.isoweekday() % 7] is not None
    assert all(
        grid[-1][row] is None for row in range(END_DAY.isoweekday() % 7 + 1, gen.ROWS)
    )

    expected = (gen.COLS - 1) * 7 + (END_DAY.isoweekday() % 7) + 1
    assert len(days) == expected == 370
    assert min(days).isoweekday() % 7 == 0, "starts on a Sunday"
    assert len(gen.month_labels(grid)) >= 10, "a full year of month labels"


def test_word_grid_lines_up_with_a_real_contribution_grid() -> None:
    """The pair only stacks if both grids agree cell for cell on dates."""
    weeks = []
    day = date(2025, 8, 31)  # the Sunday GitHub would start this calendar on
    while day <= END_DAY:
        days = []
        for row in range(gen.ROWS):
            current = day + timedelta(days=row)
            if current > END_DAY:
                break
            days.append(
                {"date": current.isoformat(), "contributionCount": 1, "weekday": row}
            )
        weeks.append({"contributionDays": days})
        day += timedelta(days=7)

    contribution = gen.build_grid(weeks)
    wordmark = gen.build_word_grid("MERNA", END_DAY)

    assert gen.month_labels(contribution) == gen.month_labels(wordmark)
    for col in range(gen.COLS):
        for row in range(gen.ROWS):
            left, right = contribution[col][row], wordmark[col][row]
            assert (left is None) == (right is None), (col, row)
            if left is not None:
                assert left.day == right.day, (col, row)


def test_a_word_too_wide_for_the_grid_is_rejected() -> None:
    with pytest.raises(gen.GeneratorError, match="columns"):
        gen.build_word_grid("ABCDEFGHIJ", END_DAY)


# ---------------------------------------------------------------------- path


def test_the_robot_reaches_every_single_letter_cell(grid: gen.Grid) -> None:
    path = gen.build_word_path(grid)
    assert gen.lit_cells(grid) <= set(path), "every glyph cell must be walked"


@pytest.mark.parametrize("word", ["A", "MERNA", "HELLO", "WXYZ", "III"])
def test_coverage_holds_for_other_words(word: str) -> None:
    grid = gen.build_word_grid(word, END_DAY)
    path = gen.build_word_path(grid)
    assert gen.lit_cells(grid) <= set(path)


def test_the_walk_is_connected_and_never_teleports(grid: gen.Grid) -> None:
    path = gen.build_word_path(grid)
    for (c1, r1), (c2, r2) in pairwise(path):
        assert max(abs(c2 - c1), abs(r2 - r1)) == 1, "8-way steps only, no hops"


def test_the_walk_never_repeats_a_cell(grid: gen.Grid) -> None:
    path = gen.build_word_path(grid)
    assert len(path) == len(set(path))


def test_the_walk_leads_in_and_out_of_the_word(grid: gen.Grid) -> None:
    path = gen.build_word_path(grid)
    lit_columns = sorted({col for col, _ in gen.lit_cells(grid)})
    assert path[0][0] == lit_columns[0] - gen.LEAD_IN_COLS
    assert path[-1][0] == lit_columns[-1] + gen.LEAD_IN_COLS


def test_the_path_is_deterministic(grid: gen.Grid) -> None:
    assert gen.build_word_path(grid) == gen.build_word_path(grid)


def test_an_empty_word_grid_does_not_crash() -> None:
    grid = gen.build_word_grid(" ", END_DAY)
    assert gen.lit_cells(grid) == set()
    assert gen.build_word_path(grid) == [(0, 0)]


# -------------------------------------------------------------------- timing


def test_wordmark_runs_the_same_twenty_to_twenty_five_seconds(grid: gen.Grid) -> None:
    steps = gen.build_timeline(grid, gen.build_word_path(grid), allow_dwell=False)
    assert 20.0 <= steps[-1].depart <= 25.0


def test_nothing_dwells_in_wordmark_mode(grid: gen.Grid) -> None:
    steps = gen.build_timeline(grid, gen.build_word_path(grid), allow_dwell=False)
    assert not any(step.dwell for step in steps)
    slots = {round(step.depart - step.arrive, 6) for step in steps}
    assert len(slots) == 1, "every step is the same length"


def test_the_gait_still_alternates_stand_and_step(grid: gen.Grid) -> None:
    steps = gen.build_timeline(grid, gen.build_word_path(grid), allow_dwell=False)
    poses = {pose for _, _, pose, _ in gen.build_pose_segments(steps)}
    assert {"stand", "step"} <= poses
    assert "grab" not in poses, "grab is the dwell pose; there are no dwells"


# --------------------------------------------------------------------- render


def test_wordmark_svg_is_well_formed_and_scriptless(svg: str) -> None:
    assert ElementTree.fromstring(svg).tag.endswith("svg")
    lowered = svg.lower()
    assert "<script" not in lowered and "javascript:" not in lowered
    assert not re.search(r"\son\w+=", lowered)


def test_the_counter_is_dropped(svg: str) -> None:
    assert "commits collected" not in svg
    assert 'class="cv"' not in svg
    assert 'class="p"' not in svg, "no particles either -- nothing to fly to"
    assert "@keyframes v" not in svg


def test_the_chrome_matches_the_contribution_version(svg: str, grid: gen.Grid) -> None:
    """Same canvas and same labels, so the two stack as a matched pair."""
    assert f'viewBox="0 0 {gen.num(gen.SVG_W)} {gen.num(gen.SVG_H)}"' in svg
    for name in ("Mon", "Wed", "Fri"):
        assert f">{name}</text>" in svg
    for _, month in gen.month_labels(grid):
        assert f">{month}</text>" in svg


def test_letters_start_dark_and_are_lit_by_the_robot(svg: str, grid: gen.Grid) -> None:
    # Every cell renders as empty; only the animation brightens it.
    assert 'class="l4"' not in svg
    assert svg.count('class="l0 col"') == len(gen.lit_cells(grid))
    assert "fill:var(--l4)" in svg, "collected letter cells brighten"
    assert "var(--collected)" not in svg, "the darkening style is not used here"
    assert "stroke-opacity" not in svg, "no outline on a lit letter"


def test_only_glyph_cells_animate(svg: str, grid: gen.Grid) -> None:
    """The robot crosses the gaps between letters without smearing the word."""
    lit = gen.lit_cells(grid)
    path = gen.build_word_path(grid)
    assert len(path) > len(lit), "the walk really does cross non-glyph cells"
    assert svg.count(" col\"") == len(lit)
    assert svg.count("@keyframes k") == len(lit)


def test_the_finished_word_holds_before_it_resets(svg: str) -> None:
    """The payoff frame must last, not flash for an instant at t=22s."""
    assert gen.WORDMARK_MODE.reset_at > gen.RUN_SECONDS
    hold = gen.pct(gen.WORDMARK_MODE.reset_at)
    assert f",{hold}{{fill:var(--l4)}}" in svg


def test_wordmark_render_is_deterministic_and_within_budget(grid: gen.Grid) -> None:
    first = gen.render_svg(grid, "merna-s-saad", 0, word="MERNA")
    assert first == gen.render_svg(grid, "merna-s-saad", 0, word="MERNA")
    assert len(first.encode("utf-8")) < 150_000


def test_the_description_names_the_word(svg: str) -> None:
    assert "<title" in svg and "<desc" in svg
    assert "MERNA" in svg


# ------------------------------------------------------------------------ cli


def test_word_mode_skips_the_api_entirely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("--word must not touch the network")

    monkeypatch.setattr(gen, "fetch_calendar", explode)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    out = tmp_path / "wordmark.svg"
    assert gen.main(["--username", "merna-s-saad", "--word", "MERNA", "--out", str(out)]) == 0
    assert out.is_file()
    assert not (out.parent / "last_fetch.json").exists(), "no payload to cache"


def test_a_bad_word_fails_with_a_readable_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = gen.main(
        ["--username", "u", "--word", "MERNA!", "--out", str(tmp_path / "x.svg")]
    )
    assert code == gen.EXIT_DATA
    assert "no glyph" in capsys.readouterr().err.lower()


def test_without_word_the_generator_is_unchanged(tmp_path: Path) -> None:
    """The contribution path must be untouched by wordmark mode existing."""
    out = tmp_path / "contribution.svg"
    fixture = REPO_ROOT / "tests" / "fixtures" / "sample_calendar.json"
    assert (
        gen.main(
            ["--username", "merna-s-saad", "--fixture", str(fixture), "--out", str(out)]
        )
        == 0
    )
    rendered = out.read_text(encoding="utf-8")
    assert "commits collected" in rendered
    assert "var(--collected)" in rendered
