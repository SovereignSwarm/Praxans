from __future__ import annotations

import os
from dataclasses import dataclass

import pygame


@dataclass(frozen=True)
class UIFontSet:
    display: pygame.font.Font
    heading: pygame.font.Font
    label: pygame.font.Font
    body: pygame.font.Font
    caption: pygame.font.Font
    data: pygame.font.Font


@dataclass(frozen=True)
class UIPalette:
    parchment: tuple[int, int, int]
    parchment_soft: tuple[int, int, int]
    ink: tuple[int, int, int]
    slate: tuple[int, int, int]
    slate_soft: tuple[int, int, int]
    moss: tuple[int, int, int]
    ochre: tuple[int, int, int]
    copper: tuple[int, int, int]
    frost: tuple[int, int, int]
    danger: tuple[int, int, int]
    warning: tuple[int, int, int]
    success: tuple[int, int, int]
    panel_fill: tuple[int, int, int]
    panel_fill_alt: tuple[int, int, int]
    panel_border: tuple[int, int, int]
    overlay: tuple[int, int, int]
    muted_text: tuple[int, int, int]
    bright_text: tuple[int, int, int]
    note_strategy: tuple[int, int, int]
    note_crisis: tuple[int, int, int]
    note_birth: tuple[int, int, int]
    note_faction: tuple[int, int, int]
    note_discovery: tuple[int, int, int]
    note_trade: tuple[int, int, int]
    note_diplomacy: tuple[int, int, int]
    note_cultural: tuple[int, int, int]
    note_disaster: tuple[int, int, int]


@dataclass(frozen=True)
class UIMotion:
    fade_seconds: float
    slide_seconds: float
    pulse_seconds: float
    camera_focus_seconds: float


@dataclass(frozen=True)
class UITheme:
    fonts: UIFontSet
    palette: UIPalette
    motion: UIMotion
    spacing_unit: int
    radius_large: int
    radius_medium: int
    radius_small: int
    shadow_alpha: int


def _font_path(filename: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "ui", "fonts", filename))


def _load_font(font_path: str, size: int) -> pygame.font.Font:
    if os.path.exists(font_path):
        return pygame.font.Font(font_path, size)
    return pygame.font.Font(None, size)


def build_ui_theme(width: int, height: int) -> UITheme:
    scale = max(0.9, min(1.15, width / 1920))
    display_font = _load_font(_font_path("DisplaySerif.ttf"), int(42 * scale))
    heading_font = _load_font(_font_path("BodySans.ttf"), int(24 * scale))
    label_font = _load_font(_font_path("BodySans.ttf"), int(18 * scale))
    body_font = _load_font(_font_path("BodySans.ttf"), int(20 * scale))
    caption_font = _load_font(_font_path("BodySans.ttf"), int(16 * scale))
    data_font = _load_font(_font_path("DataMono.otf"), int(17 * scale))
    fonts = UIFontSet(
        display=display_font,
        heading=heading_font,
        label=label_font,
        body=body_font,
        caption=caption_font,
        data=data_font,
    )
    palette = UIPalette(
        parchment=(232, 223, 200),
        parchment_soft=(216, 206, 184),
        ink=(32, 34, 38),
        slate=(48, 59, 62),
        slate_soft=(67, 79, 83),
        moss=(106, 129, 97),
        ochre=(187, 147, 88),
        copper=(171, 110, 79),
        frost=(153, 194, 196),
        danger=(184, 79, 69),
        warning=(204, 161, 85),
        success=(119, 156, 110),
        panel_fill=(22, 28, 31),
        panel_fill_alt=(29, 36, 39),
        panel_border=(121, 119, 107),
        overlay=(10, 12, 14),
        muted_text=(175, 173, 160),
        bright_text=(236, 231, 219),
        note_strategy=(129, 165, 184),
        note_crisis=(190, 99, 86),
        note_birth=(166, 181, 116),
        note_faction=(165, 133, 186),
        note_discovery=(106, 171, 167),
        note_trade=(196, 170, 94),
        note_diplomacy=(98, 168, 156),
        note_cultural=(172, 148, 204),
        note_disaster=(196, 92, 78),
    )
    motion = UIMotion(
        fade_seconds=0.16,
        slide_seconds=0.2,
        pulse_seconds=0.55,
        camera_focus_seconds=3.5,
    )
    return UITheme(
        fonts=fonts,
        palette=palette,
        motion=motion,
        spacing_unit=max(6, int(8 * scale)),
        radius_large=max(16, int(20 * scale)),
        radius_medium=max(10, int(14 * scale)),
        radius_small=max(6, int(9 * scale)),
        shadow_alpha=72,
    )


def with_alpha(color: tuple[int, int, int], alpha: int) -> tuple[int, int, int, int]:
    return (int(color[0]), int(color[1]), int(color[2]), max(0, min(255, int(alpha))))


def draw_panel(
    surface: pygame.Surface,
    rect: pygame.Rect,
    theme: UITheme,
    *,
    fill: tuple[int, int, int] | None = None,
    border: tuple[int, int, int] | None = None,
    alpha: int = 230,
    radius: int | None = None,
) -> None:
    radius = radius or theme.radius_medium
    fill_color = fill or theme.palette.panel_fill
    border_color = border or theme.palette.panel_border
    shadow_rect = rect.move(0, 6)
    shadow = pygame.Surface(shadow_rect.size, pygame.SRCALPHA)
    pygame.draw.rect(shadow, with_alpha((0, 0, 0), theme.shadow_alpha), shadow.get_rect(), border_radius=radius)
    surface.blit(shadow, shadow_rect.topleft)
    panel = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(panel, with_alpha(fill_color, alpha), panel.get_rect(), border_radius=radius)
    pygame.draw.rect(panel, border_color, panel.get_rect(), width=2, border_radius=radius)
    surface.blit(panel, rect.topleft)


def draw_button(
    surface: pygame.Surface,
    rect: pygame.Rect,
    theme: UITheme,
    label: str,
    *,
    hotkey: str | None = None,
    active: bool = False,
    accent: tuple[int, int, int] | None = None,
    subtle: bool = False,
) -> None:
    accent_color = accent or theme.palette.ochre
    fill = theme.palette.panel_fill_alt if not active else accent_color
    border = theme.palette.panel_border if not active else theme.palette.parchment
    draw_panel(surface, rect, theme, fill=fill, border=border, alpha=235, radius=theme.radius_small)
    if subtle and not active:
        inner = pygame.Rect(rect.x + 1, rect.y + 1, rect.w - 2, rect.h - 2)
        pygame.draw.rect(surface, theme.palette.slate_soft, inner, width=1, border_radius=theme.radius_small)
    text_color = theme.palette.ink if active else theme.palette.bright_text
    label_surface = theme.fonts.label.render(label, True, text_color)
    surface.blit(
        label_surface,
        (rect.x + 12, rect.y + rect.h // 2 - label_surface.get_height() // 2),
    )
    if hotkey:
        hotkey_surface = theme.fonts.caption.render(hotkey, True, theme.palette.parchment)
        surface.blit(
            hotkey_surface,
            (rect.right - hotkey_surface.get_width() - 12, rect.y + rect.h // 2 - hotkey_surface.get_height() // 2),
        )


def draw_badge(
    surface: pygame.Surface,
    theme: UITheme,
    rect: pygame.Rect,
    text: str,
    *,
    fill: tuple[int, int, int],
    text_color: tuple[int, int, int] | None = None,
) -> None:
    draw_panel(surface, rect, theme, fill=fill, border=theme.palette.panel_border, alpha=240, radius=theme.radius_small)
    badge_text = theme.fonts.caption.render(text, True, text_color or theme.palette.bright_text)
    surface.blit(
        badge_text,
        (rect.x + rect.w // 2 - badge_text.get_width() // 2, rect.y + rect.h // 2 - badge_text.get_height() // 2),
    )


def draw_divider(surface: pygame.Surface, theme: UITheme, start: tuple[int, int], end: tuple[int, int]) -> None:
    pygame.draw.line(surface, theme.palette.panel_border, start, end, 1)


def wrap_text(font: pygame.font.Font, text: str, max_width: int) -> list[str]:
    text = str(text or "").strip()
    if not text:
        return []
    words = text.split()
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if font.size(candidate)[0] <= max_width:
            current = candidate
            continue
        lines.append(current)
        current = word
    lines.append(current)
    return lines
