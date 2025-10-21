"""UI drawing helpers shared across Sentinel screens."""

from __future__ import annotations

import math
from typing import Tuple

import pygame

Color = Tuple[int, int, int]


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

    if rect.width <= 0 or rect.height <= 0:
        return

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


__all__ = ["draw_diagonal_pattern"]
