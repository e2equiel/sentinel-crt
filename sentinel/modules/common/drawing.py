"""Shared drawing helpers for Sentinel modules."""

from __future__ import annotations

import math
from typing import Tuple

import pygame

Color = Tuple[int, int, int]


def draw_dashed_line(
    surface: pygame.Surface,
    color: Color,
    start_pos: Tuple[float, float],
    end_pos: Tuple[float, float],
    width: int = 1,
    dash_length: int = 5,
) -> None:
    """Draw a dashed line on ``surface``."""

    x1, y1 = start_pos
    x2, y2 = end_pos
    if x1 == x2 and y1 == y2:
        return

    dx = x2 - x1
    dy = y2 - y1
    dist = math.hypot(dx, dy)
    if dist == 0:
        return

    dashes = max(1, int(dist / dash_length))
    for i in range(dashes // 2):
        start = (
            x1 + dx * (i * 2) / dashes,
            y1 + dy * (i * 2) / dashes,
        )
        end = (
            x1 + dx * (i * 2 + 1) / dashes,
            y1 + dy * (i * 2 + 1) / dashes,
        )
        pygame.draw.line(surface, color, start, end, width)


def draw_diagonal_pattern(
    surface: pygame.Surface,
    color: Color,
    rect: pygame.Rect,
    angle: float,
    *,
    spacing: int = 5,
    line_width: int = 1,
    phase: float = 0,
) -> None:
    """Fill ``rect`` within ``surface`` using a diagonal hatch pattern."""

    diagonal = int(math.hypot(rect.width, rect.height))
    temp_surface = pygame.Surface((diagonal, diagonal), pygame.SRCALPHA)

    phase_int = int(phase)
    for x in range(-diagonal, diagonal, spacing):
        x_pos = x + (phase_int % spacing)
        pygame.draw.line(temp_surface, color, (x_pos, 0), (x_pos, diagonal), line_width)

    rotated_surface = pygame.transform.rotozoom(temp_surface, angle, 1)
    rotated_rect = rotated_surface.get_rect(center=rect.center)

    original_clip = surface.get_clip()
    surface.set_clip(rect)
    surface.blit(rotated_surface, rotated_rect)
    surface.set_clip(original_clip)


__all__ = ["draw_dashed_line", "draw_diagonal_pattern"]
