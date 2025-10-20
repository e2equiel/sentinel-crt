import math
from importlib import resources
from typing import Optional

import numpy as np
import pygame

class ASCIIGlobe:
    """
    Maneja la creación, rotación y dibujo de un globo terráqueo en ASCII
    cargando la forma de los continentes desde un archivo de texto.
    """
    def __init__(self, screen_width, screen_height, radius, center_pos, map_file: Optional[str] = None):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.radius = radius
        self.center_x, self.center_y = center_pos
        if map_file is None:
            with resources.as_file(resources.files(__package__) / "assets" / "earth_W140_H35.txt") as default_path:
                self.map_file = str(default_path)
        else:
            self.map_file = map_file
        
        # --- REFACTORIZADO: Una sola lista para todos los puntos ---
        # Cada elemento será una tupla: (vector_3d, caracter)
        self.all_points = []
        self.rotated_points = []
        
        # --- Caché para las superficies de los caracteres pre-renderizados ---
        self.char_surfaces = {}
        self.last_color = None
        
        self._generate_points_from_map()

    def _generate_points_from_map(self):
        """Genera la esfera de puntos 3D a partir de un mapa de texto."""
        try:
            with open(self.map_file, 'r') as f:
                lines = f.readlines()
        except FileNotFoundError:
            print(f"ERROR: No se encontró el archivo del mapa: {self.map_file}")
            return

        map_height = len(lines)
        map_width = len(lines[0].strip())
        self.all_points = []
        step = 1
        
        for r in range(0, map_height, step):
            for c in range(0, map_width, step):
                char = lines[r][c]
                if char == '+' or char == '.':
                    lon = math.pi * (c / (map_width / 2) - 1)
                    lat = math.pi * (0.5 - r / map_height)
                    
                    x = self.radius * math.cos(lat) * math.cos(lon)
                    y = self.radius * math.sin(lat)
                    z = -self.radius * math.cos(lat) * math.sin(lon)
                    
                    point_3d = np.array([x, y, z])
                    
                    # --- REFACTORIZADO: Añadimos el punto y su carácter a la misma lista ---
                    self.all_points.append((point_3d, char))

    def update(self, angle_x, angle_y):
        """Rota los puntos del globo usando matrices de rotación."""
        rotation_y = np.array([
            [math.cos(angle_y), 0, math.sin(angle_y)],
            [0, 1, 0],
            [-math.sin(angle_y), 0, math.cos(angle_y)]
        ])
        rotation_x = np.array([
            [1, 0, 0],
            [0, math.cos(angle_x), -math.sin(angle_x)],
            [0, math.sin(angle_x), math.cos(angle_x)]
        ])
        
        self.rotated_points = []
        for point, char in self.all_points:
            # --- REFACTORIZADO: Rotamos el punto y lo volvemos a guardar con su carácter ---
            rotated_p = np.dot(rotation_y, point)
            rotated_p = np.dot(rotation_x, rotated_p)
            self.rotated_points.append((rotated_p, char))

    def draw(self, surface, font, color):
        """Dibuja el globo ASCII en la superficie de Pygame."""
        
        # Pre-renderiza los caracteres si el color ha cambiado o si no existen
        if color != self.last_color:
            self.char_surfaces = {
                '+': font.render("+", True, color + (255,)),
                '.': font.render(".", True, color + (80,))
            }
            self.last_color = color

        # --- REFACTORIZADO: Un solo bucle para dibujar todos los puntos ---
        for point, char in self.rotated_points:
            x, y, z = point[0], point[1], point[2]
            
            if z > 0: # Si el punto es visible
                screen_x = int(x + self.center_x)
                screen_y = int(self.center_y - y)
                
                if 0 <= screen_x < self.screen_width and 0 <= screen_y < self.screen_height:
                    # Dibuja la superficie pre-renderizada para el carácter correspondiente
                    surface.blit(self.char_surfaces[char], (screen_x, screen_y))