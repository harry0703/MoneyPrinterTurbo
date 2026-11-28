"""Character definitions. Tiko is the reference articulated character.

A character is only a palette plus a component tree; adding a new character
means declaring parts here (or in user code) and reusing the same renderer,
expressions and animation presets.
"""

from __future__ import annotations

from app.services.cartoon_animation.models import (
    AnimationError,
    Character,
    Part,
    Shape,
)

TIKO_PALETTE: dict[str, str] = {
    "ink": "#1D2B3A",
    "blue": "#4A90D9",
    "blue_dark": "#2F6FA8",
    "blue_light": "#AEDCF7",
    "yellow": "#FFD24A",
    "white": "#FFFFFF",
    "mouth": "#5B2333",
    "pink": "#F49AC1",
}


def _tiko_parts() -> tuple[Part, ...]:
    parts: list[Part] = []

    # Legs and feet sit behind the body.
    for side, x, rotation in (
        ("left", -44.0, "left_leg_rotation"),
        ("right", 44.0, "right_leg_rotation"),
    ):
        parts.append(
            Part(
                name=f"{side}_leg",
                shape=Shape(
                    "capsule", 30, 92, "blue_dark", "ink", 3, offset=(0, 46)
                ),
                parent=None,
                anchor=(x, 34),
                layer=10,
                rotation_channel=rotation,
            )
        )
        parts.append(
            Part(
                name=f"{side}_foot",
                shape=Shape("ellipse", 48, 24, "blue_dark", "ink", 3, offset=(0, 10)),
                parent=f"{side}_leg",
                anchor=(0, 92),
                layer=11,
            )
        )

    parts.append(
        Part(
            name="body",
            shape=Shape(
                "rounded_rect", 176, 196, "blue", "ink", 4, radius=58, offset=(0, -45)
            ),
            parent=None,
            anchor=(0, 0),
            layer=20,
            rotation_channel="body_rotation",
        )
    )
    # A lighter chest plate keeps the silhouette readable at 720x1280.
    parts.append(
        Part(
            name="chest",
            shape=Shape(
                "rounded_rect", 104, 92, "blue_light", "", 0, radius=34, offset=(0, -48)
            ),
            parent="body",
            anchor=(0, 0),
            layer=21,
        )
    )

    for side, x, rotation in (
        ("left", -84.0, "left_arm_rotation"),
        ("right", 84.0, "right_arm_rotation"),
    ):
        parts.append(
            Part(
                name=f"{side}_arm",
                shape=Shape(
                    "capsule", 26, 108, "blue_dark", "ink", 3, offset=(0, 50)
                ),
                parent="body",
                anchor=(x, -112),
                layer=25,
                rotation_channel=rotation,
            )
        )
        parts.append(
            Part(
                name=f"{side}_hand",
                shape=Shape("ellipse", 38, 38, "blue_light", "ink", 3),
                parent=f"{side}_arm",
                anchor=(0, 106),
                layer=26,
            )
        )

    parts.append(
        Part(
            name="head",
            shape=Shape(
                "rounded_rect", 200, 172, "blue_light", "ink", 4, radius=54, offset=(0, -80)
            ),
            parent="body",
            anchor=(0, -146),
            layer=40,
            rotation_channel="head_rotation",
            translation_channels=("head_x", "head_y"),
        )
    )
    # Visor strip behind the eyes.
    parts.append(
        Part(
            name="visor",
            shape=Shape(
                "rounded_rect", 156, 82, "white", "ink", 3, radius=36, offset=(0, -98)
            ),
            parent="head",
            anchor=(0, 0),
            layer=41,
        )
    )

    for side, x in (("left", -42.0), ("right", 42.0)):
        parts.append(
            Part(
                name=f"{side}_eye",
                shape=Shape("ellipse", 56, 64, "white", "ink", 3),
                parent="head",
                anchor=(x, -100),
                layer=44,
                dynamic="eye",
            )
        )
        parts.append(
            Part(
                name=f"{side}_pupil",
                shape=Shape("ellipse", 24, 28, "ink"),
                parent=f"{side}_eye",
                anchor=(0, 0),
                layer=46,
                dynamic="pupil",
            )
        )
        parts.append(
            Part(
                name=f"{side}_brow",
                shape=Shape("rounded_rect", 38, 9, "ink", "", 0, radius=4),
                parent="head",
                anchor=(x, -142),
                layer=47,
                dynamic="brow",
            )
        )
        parts.append(
            Part(
                name=f"{side}_blush",
                shape=Shape("ellipse", 32, 16, "pink"),
                parent="head",
                anchor=(x * 1.65, -60),
                layer=43,
                dynamic="blush",
            )
        )

    parts.append(
        Part(
            name="mouth",
            shape=Shape(
                "rounded_rect", 54, 44, "mouth", "ink", 2, radius=18
            ),
            parent="head",
            anchor=(0, -44),
            layer=45,
            dynamic="mouth",
        )
    )

    parts.append(
        Part(
            name="antenna",
            shape=Shape("capsule", 12, 58, "yellow", "ink", 2, offset=(0, -29)),
            parent="head",
            anchor=(0, -162),
            layer=48,
            rotation_channel="antenna_rotation",
        )
    )
    parts.append(
        Part(
            name="antenna_ball",
            shape=Shape("ellipse", 30, 30, "yellow", "ink", 3),
            parent="antenna",
            anchor=(0, -58),
            layer=49,
        )
    )
    return tuple(parts)


def tiko(palette: dict[str, str] | None = None) -> Character:
    colors = dict(TIKO_PALETTE)
    if palette:
        unknown = set(palette) - set(colors)
        if unknown:
            raise AnimationError(
                f"unknown Tiko palette keys: {', '.join(sorted(unknown))}"
            )
        colors.update(palette)
    return Character(
        id="tiko",
        name="Tiko",
        palette=colors,
        parts=_tiko_parts(),
        canvas=(480.0, 660.0),
        origin=(240.0, 500.0),
    )


CHARACTER_PRESETS = {"tiko": tiko}


def get_character(name: str = "tiko", palette: dict[str, str] | None = None) -> Character:
    try:
        factory = CHARACTER_PRESETS[name]
    except KeyError as exc:
        choices = ", ".join(sorted(CHARACTER_PRESETS))
        raise AnimationError(f"character preset must be one of {choices}") from exc
    return factory(palette)
