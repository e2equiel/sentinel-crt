import argparse
import pygame
import sys
import time
import random
import threading
import traceback
from pathlib import Path
from typing import Optional, Sequence

# Import configuration from the separate config file
import config

from sentinel.config import load_configuration
from sentinel.core import EventBus, ModuleManager, ServiceManager
from sentinel.ui import draw_diagonal_pattern

# --- Constants ---
COLOR_BLACK = (0, 0, 0)


class SentinelApp:
    def __init__(self, fullscreen: Optional[bool] = None):
        """Initialize the Sentinel runtime, services, and module manager."""

        pygame.init()

        self.settings = load_configuration()
        self.core_settings = dict(self.settings.core)

        if hasattr(config, "CONFIG") and isinstance(config.CONFIG, dict):
            config.CONFIG.update(self.core_settings)
        else:
            config.CONFIG = dict(self.core_settings)

        base_theme = getattr(config, "THEME_COLORS", {})
        if not isinstance(base_theme, dict):
            base_theme = {}
        self.theme_colors = dict(base_theme)
        self.theme_colors.update(self.settings.theme_colors)
        config.THEME_COLORS = self.theme_colors

        fullscreen_enabled = bool(fullscreen) if fullscreen is not None else False
        self.core_settings["fullscreen"] = fullscreen_enabled
        config.CONFIG["fullscreen"] = fullscreen_enabled

        if fullscreen_enabled:
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            width = self.core_settings.get("screen_width", 640)
            height = self.core_settings.get("screen_height", 480)
            self.screen = pygame.display.set_mode((width, height))

        pygame.mouse.set_visible(False)
        self.clock = pygame.time.Clock()

        font_path = Path(__file__).resolve().parent / "sentinel" / "assets" / "fonts" / "VT323-Regular.ttf"
        try:
            font_file = str(font_path)
            self.font_large = pygame.font.Font(font_file, 24)
            self.font_medium = pygame.font.Font(font_file, 20)
            self.font_small = pygame.font.Font(font_file, 16)
            self.font_tiny = pygame.font.Font(font_file, 12)
        except pygame.error as e:
            print(f"Error loading font VT323-Regular.ttf: {e}")
            print(f"Please make sure the font file is available at {font_path}.")
            sys.exit()

        self.event_bus = EventBus()
        self.service_manager = ServiceManager(self, self.settings.services)

        self.running = True
        self.data_lock = threading.RLock()
        self.reset_pending = False
        self.current_screen = None

        self.alert_level = "none"
        self.current_theme_color = self.theme_colors['default']
        self.header_title_text = "S.E.N.T.I.N.E.L. v1.0"

        self.spinner_angle = 0
        self.pattern_phase = 0.0
        self.pattern_speed_px_s = 10.0
        self.sys_load_string = "000000"
        self.sys_load_update_timer = 0.0
        self.level_bars_heights = [random.randint(2, 18) for _ in range(5)]
        self.level_bars_update_timer = 0.0

        self.event_bus.subscribe("system.restart", self._handle_restart_event)
        self.event_bus.subscribe("ui.alert", self._handle_alert_event)

        self.module_manager = self._initialize_modules()
        self.service_manager.start_all()

    # ------------------------------------------------------------------ setup helpers
    def _initialize_modules(self) -> ModuleManager:
        modules_to_load = {}
        for name, module_settings in self.settings.modules.items():
            if not module_settings.enabled:
                continue
            try:
                module = ModuleManager.create_from_config(
                    {"module": module_settings.path, "config": dict(module_settings.settings)}
                )
            except Exception as exc:
                print(f"[ModuleManager] Unable to load module '{name}': {exc}")
                continue
            modules_to_load[name] = module

        if not modules_to_load:
            print("[ModuleManager] No modules enabled; module manager will start empty.")

        priorities_cfg = self.settings.priorities if isinstance(self.settings.priorities, dict) else {}
        idle_cycle = None
        if isinstance(priorities_cfg, dict):
            idle_section = priorities_cfg.get("idle", {})
            if isinstance(idle_section, dict):
                cycle = idle_section.get("cycle")
                if cycle:
                    idle_cycle = list(cycle)

        manager = ModuleManager(
            self,
            modules_to_load,
            priorities=priorities_cfg,
            idle_cycle=idle_cycle,
        )

        startup_screen = self.core_settings.get("startup_screen", "camera")
        if isinstance(startup_screen, str) and startup_screen.lower() == "auto":
            startup_screen = None

        if startup_screen and startup_screen in manager.modules:
            manager.set_active(startup_screen)
        elif manager.modules:
            first_screen = next(iter(manager.modules))
            manager.set_active(first_screen)

        return manager

    # ------------------------------------------------------------------ event handlers
    def _handle_restart_event(self, _payload=None) -> None:
        print("INFO: Restart command received. Flagging for reset.")
        self.reset_pending = True

    def _handle_alert_event(self, payload) -> None:
        level = "none"
        title = None
        if isinstance(payload, dict):
            level = payload.get("level", "none")
            title = payload.get("title")
        elif isinstance(payload, str):
            level = payload

        self.alert_level = level
        if level == "danger":
            self.current_theme_color = self.theme_colors['danger']
            self.header_title_text = title or "DANGER"
        elif level == "warning":
            self.current_theme_color = self.theme_colors['warning']
            self.header_title_text = title or "WARNING"
        else:
            self.current_theme_color = self.theme_colors['default']
            self.header_title_text = title or "S.E.N.T.I.N.E.L. v1.0"

    def _execute_hard_reset(self) -> None:
        """Restart services and reload the module manager."""

        print("INFO: Executing hard reset...")
        print("INFO: Stopping background services...")
        self.service_manager.stop_all()
        print("INFO: Services stopped.")

        if self.module_manager:
            print("INFO: Reinitializing modules...")
            self.module_manager.shutdown()
            self.module_manager = self._initialize_modules()

        print("INFO: Restarting background services...")
        self.service_manager.start_all()
        print("INFO: Hard reset complete.")

    # ------------------------------------------------------------------ main loop
    def run(self) -> int:
        """Run the application's main loop until stopped."""

        exit_code = 0
        try:
            while self.running:
                dt = self.clock.tick(self.core_settings.get("fps", 30)) / 1000.0
                self.handle_events()
                self.update(dt)
                self.draw()
        except KeyboardInterrupt:
            print("INFO: Keyboard interrupt received. Exiting main loop.")
            exit_code = 130
        except Exception:
            print("ERROR: Unhandled exception in main loop:")
            traceback.print_exc()
            exit_code = 1
        finally:
            self.shutdown()
        return exit_code

    def shutdown(self) -> None:
        """Shut down background services and release application resources."""

        print("Closing application...")
        self.running = False
        if self.module_manager:
            self.module_manager.shutdown()
        self.service_manager.stop_all()
        pygame.quit()

    # ------------------------------------------------------------------ frame lifecycle
    def handle_events(self) -> None:
        """Poll Pygame events and forward them to the active module."""

        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                self.running = False
                continue
            if self.module_manager:
                self.module_manager.handle_event(event)

    def update(self, dt: float) -> None:
        """Advance the application's state by one frame."""

        if self.reset_pending:
            self._execute_hard_reset()
            self.reset_pending = False
            return

        if self.module_manager:
            self.module_manager.update(dt)

        self._update_header_effects(dt)

    def _update_header_effects(self, dt: float) -> None:
        now = time.time()
        self.spinner_angle = (self.spinner_angle + 180 * dt) % 360
        self.pattern_phase += self.pattern_speed_px_s * dt
        if now > self.sys_load_update_timer:
            self.sys_load_string = f"{random.randint(0, 0xFFFFFF):06X}"
            self.sys_load_update_timer = now + 0.2
        if now > self.level_bars_update_timer:
            self.level_bars_heights = [random.randint(2, 18) for _ in range(5)]
            self.level_bars_update_timer = now + 0.3

    # ------------------------------------------------------------------ rendering
    def draw(self) -> None:
        """Render the active UI screen and header to the main display surface."""

        self.screen.fill(COLOR_BLACK)

        if self.module_manager:
            self.module_manager.render(self.screen)
        else:
            self._draw_placeholder()

        if config.CONFIG.get('show_header', True):
            self.draw_header()

        pygame.display.flip()

    def _draw_placeholder(self) -> None:
        message = "MODULE MANAGER OFFLINE"
        surface = self.font_large.render(message, True, self.current_theme_color)
        self.screen.blit(surface, surface.get_rect(center=self.screen.get_rect().center))

    def draw_header(self) -> None:
        margins = config.CONFIG['margins']
        header_rect = pygame.Rect(
            margins['left'],
            margins['top'] - 5,
            self.screen.get_width() - (margins['left'] + margins['right']),
            30,
        )
        color = self.current_theme_color

        pygame.draw.line(self.screen, color, (header_rect.left, header_rect.bottom), (header_rect.right, header_rect.bottom), 2)
        title_surface = self.font_large.render(self.header_title_text, True, color)
        title_rect = title_surface.get_rect(topleft=(header_rect.left, header_rect.top + 2))
        self.screen.blit(title_surface, title_rect)

        bar_x = header_rect.right - 5 * 8
        for i, height in enumerate(self.level_bars_heights):
            pygame.draw.rect(self.screen, color, (bar_x + i * 8, header_rect.centery - height/2 + 1, 4, height))
        sys_load_surface = self.font_medium.render(f"SYS-LOAD: {self.sys_load_string}", True, color)
        sys_load_rect = sys_load_surface.get_rect(right=bar_x - 15, centery=header_rect.centery)
        self.screen.blit(sys_load_surface, sys_load_rect)
        spinner_char_surf = self.font_medium.render("+", True, color)
        original_spinner_rect = spinner_char_surf.get_rect(right=sys_load_rect.left - 10, centery=header_rect.centery)
        rotated_spinner = pygame.transform.rotate(spinner_char_surf, self.spinner_angle)
        rotated_spinner_rect = rotated_spinner.get_rect(center=original_spinner_rect.center)
        self.screen.blit(rotated_spinner, rotated_spinner_rect)

        pattern_left_margin = 10
        pattern_right_margin = 24
        pattern_start_x = title_rect.right + pattern_left_margin
        pattern_end_x = sys_load_rect.left - pattern_right_margin
        pattern_width = max(0, pattern_end_x - pattern_start_x)

        pattern_rect = pygame.Rect(
            pattern_start_x,
            header_rect.top + 6,
            pattern_width,
            header_rect.height - 12
        )
        draw_diagonal_pattern(
            self.screen,
            color,
            pattern_rect,
            -45,
            spacing=8,
            line_width=4,
            phase=self.pattern_phase,
        )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments for the Sentinel CRT application."""

    parser = argparse.ArgumentParser(description="Sentinel CRT user interface")
    parser.set_defaults(fullscreen=None)
    parser.add_argument(
        "--fullscreen",
        dest="fullscreen",
        action="store_true",
        help="Launch the interface in fullscreen mode.",
    )
    return parser.parse_args(argv)


if __name__ == '__main__':
    args = parse_args()
    app = SentinelApp(fullscreen=args.fullscreen)
    sys.exit(app.run())
