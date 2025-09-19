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
        self.sea_points = []
        self.rotated_points = []
        self.rotated_sea_points = []
        
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
        self.sea_points = []
        for r, line in enumerate(lines):
            for c, char in enumerate(line):
                if char == '+' or char == '.':
                    # Usamos la fórmula de longitud estándar (sin offsets)
                    lon = math.pi * (c / (map_width / 2) - 1)
                    
                    lat = math.pi * (0.5 - r / map_height)
                    
                    x = self.radius * math.cos(lat) * math.cos(lon)
                    y = self.radius * math.sin(lat)
                    # <-- CORRECCIÓN: Negamos Z para invertir el frente/detrás del globo
                    z = -self.radius * math.cos(lat) * math.sin(lon)
                    
                    point_3d = np.array([x, y, z])

                    if char == '+':
                        self.points.append(point_3d)
                    else:
                        self.sea_points.append(point_3d)

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
        
        self.rotated_sea_points = [np.dot(rotation_y, p) for p in self.sea_points]
        self.rotated_sea_points = [np.dot(rotation_x, p) for p in self.rotated_sea_points]

    def draw(self, surface, font, color):
        """Dibuja el globo ASCII en la superficie de Pygame."""
        light_vector = np.array([0, 0, 1])
        
        sea_char_surf = font.render(".", True, color + (60,))
        for p in self.rotated_sea_points:
            x, y, z = p[0], p[1], p[2]
            if z > 0:
                # <-- CORREGIDO: Usamos (centro - y) para invertir el eje Y y que coincida con los eventos
                screen_x = int(x + self.center_x)
                screen_y = int(self.center_y - y)
                if 0 <= screen_x < self.screen_width and 0 <= screen_y < self.screen_height:
                    surface.blit(sea_char_surf, (screen_x, screen_y))
        
        for p in self.rotated_points:
            x, y, z = p[0], p[1], p[2]

            if z > 0:
                # <-- CORREGIDO: Usamos (centro - y) aquí también
                screen_x = int(x + self.center_x)
                screen_y = int(self.center_y - y)
                
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