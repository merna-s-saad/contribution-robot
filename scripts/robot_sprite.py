"""Robot sprite symbols for the contribution-grid SVG.

Exposes :data:`ROBOT_DEFS` (a run of ``<symbol>`` elements for the SVG
``<defs>``) and :func:`robot_use`, which emits a ``<use>`` reference.

All symbols share the viewBox ``-20 -8 40 72`` so every pose has the same
origin at the head centre and they can be swapped in place without the sprite
jumping. Colours reference the CSS custom properties defined by the generator
(``--robot-body``, ``--robot-visor``, ``--robot-eye``) rather than literal hex,
so the palette stays retunable in one place. Custom properties are inherited,
so they cascade into the shadow content a ``<use>`` clones.

Two families of symbols:

* ``robot-stand`` / ``robot-step`` / ``robot-grab`` -- the detailed poses,
  meant for a larger standalone render.
* ``robot-mini`` / ``robot-mini-step`` / ``robot-mini-grab`` -- the same poses
  with the chest panel dropped and the strokes bumped to 2, because at ~22px
  tall over 13px cells the panel and thin strokes turn to mud. These are what
  the walking animation uses.
"""

from __future__ import annotations

SPRITE_VIEWBOX = "-20 -8 40 72"
SPRITE_HEIGHT = 22.0
SPRITE_WIDTH = 40.0 / 72.0 * SPRITE_HEIGHT  # keep the viewBox aspect ratio

BODY_FILL = "var(--robot-body)"
LINE = "var(--robot-visor)"
EYE_FILL = "var(--robot-eye)"

POSES = ("stand", "step", "grab")


def _n(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _limbs(pose: str) -> str:
    """Legs then arms, in paint order (they sit behind the torso)."""
    if pose == "step":
        return (
            '<rect x="-17" y="46" width="10" height="14" rx="4" '
            'transform="rotate(-16 -12 48)"/>'
            '<rect x="5" y="46" width="10" height="14" rx="4" '
            'transform="rotate(16 10 48)"/>'
            '<rect x="-20" y="26" width="8" height="20" rx="4" '
            'transform="rotate(18 -16 30)"/>'
            '<rect x="12" y="26" width="8" height="20" rx="4" '
            'transform="rotate(-18 16 30)"/>'
        )

    legs = (
        '<rect x="-13" y="46" width="10" height="14" rx="4"/>'
        '<rect x="3" y="46" width="10" height="14" rx="4"/>'
    )
    left_arm = '<rect x="-18" y="26" width="8" height="20" rx="4"/>'
    if pose == "grab":
        right_arm = (
            '<rect x="12" y="4" width="8" height="20" rx="4" '
            'transform="rotate(38 16 14)"/>'
        )
    else:
        right_arm = '<rect x="10" y="26" width="8" height="20" rx="4"/>'
    return legs + left_arm + right_arm


def _symbol(symbol_id: str, pose: str, mini: bool) -> str:
    limb_stroke = "2" if mini else "1.2"
    main_stroke = "2" if mini else "1.4"
    # The step pose looks 1px ahead of itself.
    eye_left, eye_right = (-6, 4) if pose == "step" else (-5, 5)

    panel = (
        ""
        if mini
        else (
            f'<rect x="-5" y="31" width="10" height="9" rx="3" '
            f'fill="{LINE}" stroke-width="{limb_stroke}"/>'
        )
    )

    return (
        f'<symbol id="{symbol_id}" viewBox="{SPRITE_VIEWBOX}" overflow="visible">'
        f'<g fill="{BODY_FILL}" stroke="{LINE}" stroke-linejoin="round">'
        f'<g stroke-width="{limb_stroke}">{_limbs(pose)}</g>'
        f'<rect x="-12" y="24" width="24" height="24" rx="7" '
        f'stroke-width="{main_stroke}"/>'
        f"{panel}"
        f'<g stroke-width="{limb_stroke}">'
        f'<ellipse cx="-17" cy="10" rx="4" ry="5"/>'
        f'<ellipse cx="17" cy="10" rx="4" ry="5"/>'
        f"</g>"
        f'<rect x="-16" y="-4" width="32" height="28" rx="12" '
        f'stroke-width="{main_stroke}"/>'
        f'<rect x="-12" y="2" width="24" height="16" rx="8" '
        f'fill="{LINE}" stroke-width="{main_stroke}"/>'
        f'<circle cx="{eye_left}" cy="10" r="3" fill="{EYE_FILL}" stroke="none"/>'
        f'<circle cx="{eye_right}" cy="10" r="3" fill="{EYE_FILL}" stroke="none"/>'
        f"</g>"
        f"</symbol>"
    )


#: Every symbol, ready to drop into ``<defs>``.
ROBOT_DEFS: str = "".join(
    [_symbol(f"robot-{pose}", pose, mini=False) for pose in POSES]
    + [
        _symbol("robot-mini" + ("" if pose == "stand" else f"-{pose}"), pose, mini=True)
        for pose in POSES
    ]
)

#: Pose name -> symbol id, for the small on-grid sprite.
MINI_SYMBOLS: dict[str, str] = {
    "stand": "robot-mini",
    "step": "robot-mini-step",
    "grab": "robot-mini-grab",
}


def robot_use(
    x: float,
    y: float,
    facing: int = 1,
    symbol: str = "robot-mini",
    extra: str = "",
) -> str:
    """A ``<use>`` of ``symbol``, centred on ``(x, y)``.

    ``facing`` of -1 mirrors the sprite horizontally about its own x centre so
    it turns around when the path moves leftward. Never flips vertically. The
    sprite box is symmetric about its centre, so the mirrored element occupies
    exactly the same rectangle.
    """
    width, height = SPRITE_WIDTH, SPRITE_HEIGHT
    left, top = x - width / 2.0, y - height / 2.0
    flip = (
        f' transform="translate({_n(2.0 * x)} 0) scale(-1 1)"' if facing < 0 else ""
    )
    return (
        f'<use href="#{symbol}" xlink:href="#{symbol}" '
        f'x="{_n(left)}" y="{_n(top)}" '
        f'width="{_n(width)}" height="{_n(height)}"{flip}{extra}/>'
    )
