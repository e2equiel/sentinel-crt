from __future__ import annotations

import math
from typing import Tuple

import pygame

from sentinel.ui import draw_diagonal_pattern

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


__all__ = ["draw_dashed_line", "draw_diagonal_pattern"]
