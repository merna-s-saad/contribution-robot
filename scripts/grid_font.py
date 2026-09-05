"""A 5x7 bitmap font sized for a GitHub contribution grid.

Each glyph is seven row-strings of five characters, ``1`` for a lit cell and
``0`` for a blank one. :func:`layout` turns a word into grid columns, with a
single blank column between letters and none at either end.

The grid is 53 columns wide, so at 5 columns per letter plus a separator a
word of up to 8 characters fits.
"""

from __future__ import annotations

GLYPH_WIDTH = 5
GLYPH_HEIGHT = 7

GLYPHS: dict[str, list[str]] = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01110", "10001", "10000", "10111", "10001", "10001", "01111"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    "J": ["00111", "00010", "00010", "00010", "00010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10001", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "11011", "10001"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    " ": ["00000"] * GLYPH_HEIGHT,
}


class UnsupportedCharacter(ValueError):
    """Raised for a character the font has no glyph for."""


def glyph_columns(char: str) -> list[list[bool]]:
    """One glyph as ``GLYPH_WIDTH`` columns of ``GLYPH_HEIGHT`` booleans."""
    rows = GLYPHS.get(char.upper())
    if rows is None:
        raise UnsupportedCharacter(
            f"No glyph for {char!r}. Supported: A-Z and space."
        )
    return [
        [rows[row][col] == "1" for row in range(GLYPH_HEIGHT)]
        for col in range(GLYPH_WIDTH)
    ]


def layout(word: str) -> list[list[bool]]:
    """A word as grid columns, one blank column between letters, none at the ends."""
    if not word:
        return []
    columns: list[list[bool]] = []
    for index, char in enumerate(word):
        if index:
            columns.append([False] * GLYPH_HEIGHT)
        columns.extend(glyph_columns(char))
    return columns


def width(word: str) -> int:
    """Columns a word occupies, separators included."""
    return 0 if not word else len(word) * (GLYPH_WIDTH + 1) - 1
