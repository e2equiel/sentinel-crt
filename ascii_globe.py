import pygame
import numpy as np
import math
import random

class ASCIIGlobe:
    """
    Maneja la creación, rotación y dibujo de un globo terráqueo en ASCII
    cargando la forma de los continentes desde un archivo de texto.
    """
    def __init__(self, screen_width, screen_height, radius, center_pos, map_file):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.radius = radius
        self.center_x, self.center_y = center_pos
        self.map_file = map_file

        self.chars = ".,-~:;=!*#$@"
        
        self.points = []
        self.rotated_points = []
        
        self._generate_points_from_map()

    def _generate_points_from_map(self):
        """Genera la esfera de puntos 3D a partir de un mapa de texto."""
        try:
            with open(self.map_file, 'r') as f:
                lines = f.readlines()
        except FileNotFoundError:
            print(f"ERROR: No se encontró el archivo del mapa: {self.map_file}")
            print("Asegúrate de que 'earth_W140_H35.txt' está en la misma carpeta.")
            return

        map_height = len(lines)
        map_width = len(lines[0].strip())

        self.points = []
        for r, line in enumerate(lines):
            for c, char in enumerate(line):
                if char == '+': # Solo procesamos los puntos de 'tierra'
                    lon = math.pi * (c / (map_width / 2) - 1)
                    lat = math.pi * (r / map_height - 0.5)
                    
                    x = self.radius * math.cos(lat) * math.cos(lon)
                    y = self.radius * math.sin(lat)
                    z = self.radius * math.cos(lat) * math.sin(lon)
                    
                    self.points.append(np.array([-x, y, z]))


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
        
        self.rotated_points = [np.dot(rotation_y, p) for p in self.points]
        self.rotated_points = [np.dot(rotation_x, p) for p in self.rotated_points]

    def draw(self, surface, font, color):
        """Dibuja el globo ASCII en la superficie de Pygame."""
        light_vector = np.array([0, 0, -1])
        
        for p in self.rotated_points:
            x, y, z = p[0], p[1], p[2]

            if z > 0:
                screen_x = int(x + self.center_x)
                screen_y = int(y + self.center_y)
                
                if not (0 <= screen_x < self.screen_width and 0 <= screen_y < self.screen_height):
                    continue

                norm_p = np.linalg.norm(p)
                if norm_p == 0: continue
                normal = p / norm_p
                
                luminance = np.dot(normal, light_vector)
                
                if luminance > 0:
                    char_index = int(luminance * len(self.chars))
                    char_index = min(len(self.chars) - 1, char_index)
                    alpha = int(50 + 205 * (z / self.radius))
                    
                    char_surf = font.render(self.chars[char_index], True, color + (alpha,))
                    surface.blit(char_surf, (screen_x, screen_y))

