# Sentinel CRT - AI Assistant Guide

This document provides comprehensive guidance for AI assistants working on the Sentinel CRT codebase.

## Project Overview

Sentinel CRT is a Python-based monitoring interface designed with a retro CRT aesthetic. It runs on a Raspberry Pi connected to a CRT television, providing a heads-up display for real-time events from a Frigate NVR instance and nearby air traffic via MQTT.

### Core Purpose
- Monitor security camera feeds with object detection from Frigate NVR
- Display air traffic radar when aircraft are detected overhead
- Provide a modular, extensible framework for additional monitoring screens
- Deliver a retro terminal/CRT aesthetic with scanlines and pixel fonts

## Technology Stack

- **Language**: Python 3
- **Display**: Pygame (with SDL2 backend)
- **Video**: OpenCV (cv2)
- **Communication**: Paho-MQTT
- **Configuration**: PyYAML + optional config.py
- **Hardware Target**: Raspberry Pi 3B+ or newer with composite/HDMI output

## Repository Structure

```
sentinel-crt/
├── sentinel_crt.py           # Main application entry point
├── config.py.example         # Example legacy configuration file
├── requirements.txt          # Python dependencies
├── README.md                 # User-facing documentation
├── scripts/
│   ├── install_rpi.sh        # Automated Raspberry Pi installation script
│   └── run_via_xinit.sh      # X11 fallback launcher
├── settings/                 # YAML-based configuration system
│   ├── README.md             # Configuration documentation
│   ├── priorities.yaml       # Screen priority and idle cycle configuration
│   ├── modules/              # Per-module configuration YAML files
│   └── services/             # Per-service configuration YAML files
├── docs/                     # Module and service documentation
│   ├── modules/              # Individual module documentation
│   └── services/             # Individual service documentation
└── sentinel/                 # Main application package
    ├── config/               # Configuration loading utilities
    ├── core/                 # Core framework components
    │   ├── event_bus.py      # Pub/sub event system
    │   ├── module.py         # Base ScreenModule class
    │   ├── module_manager.py # Module lifecycle and priority system
    │   └── service_manager.py# Background service orchestration
    ├── modules/              # Screen modules (camera, radar, etc.)
    │   ├── camera/           # Frigate camera integration
    │   ├── radar/            # Air traffic radar display
    │   ├── neo/              # Near-Earth Object tracker
    │   ├── eonet/            # EONET Earth events globe
    │   └── common/           # Shared module utilities
    ├── services/             # Background services
    │   ├── mqtt.py           # MQTT client wrapper
    │   └── video.py          # RTSP video stream handler
    ├── ui/                   # UI utilities (patterns, drawing helpers)
    ├── tools/                # Development and migration tools
    └── assets/               # Static assets (fonts, images)
        └── fonts/
            └── VT323-Regular.ttf  # Retro CRT font
```

## Architecture Overview

### Core Components

#### 1. SentinelApp (sentinel_crt.py)
The main application class that orchestrates the entire system:
- Initializes Pygame display and fonts
- Loads configuration from YAML and config.py
- Creates EventBus, ServiceManager, and ModuleManager
- Runs the main game loop (event handling, update, render)
- Manages application lifecycle and hard resets

#### 2. EventBus (sentinel/core/event_bus.py)
Thread-safe pub/sub system for decoupling components:
- Services publish events (e.g., MQTT messages, video frames)
- Modules subscribe to relevant events
- Common events:
  - `system.restart` - Trigger application restart
  - `ui.alert` - Change UI theme (danger/warning/default)
  - `services.mqtt.detection` - Frigate detection event
  - `services.mqtt.flights` - Flight data from MQTT
  - `services.mqtt.status` - MQTT connection status

#### 3. ModuleManager (sentinel/core/module_manager.py)
Manages screen modules and automatic screen switching:
- Loads modules from configuration
- Handles module lifecycle (load, show, hide, unload)
- Implements priority-based screen switching
- Supports idle cycling between modules
- Routes events to active module
- Manages module state reporting for automatic transitions

#### 4. ServiceManager (sentinel/core/service_manager.py)
Manages background services:
- Starts services in background threads
- Stops services gracefully on shutdown
- Services include MQTT client, video streaming, etc.

#### 5. ScreenModule Base Class (sentinel/core/module.py)
Abstract base class for all screen modules:
- **Lifecycle hooks**: `on_load()`, `on_unload()`, `on_show()`, `on_hide()`
- **Frame methods**: `update(dt)`, `render(surface)`, `handle_event(event)`
- **State reporting**: `report_state(state, metadata, weight, expires_in)`
- Each module has access to `self.app`, `self.manager`, `self.config`

### Module System

Modules are independent screens that can be displayed. Each module:
1. Extends `ScreenModule` base class
2. Implements required `render(surface)` method
3. Optionally implements lifecycle hooks and event handlers
4. Can report state changes to trigger automatic screen switching
5. Receives configuration from YAML files

**Available Modules:**
- **camera**: Displays RTSP camera feed with Frigate object detection overlays
- **radar**: Shows air traffic on a Mapbox-based radar display
- **neo_tracker**: Displays near-Earth object tracking data
- **eonet_globe**: Shows Earth events on an ASCII globe visualization

### Service System

Services are background threads that run continuously:
- **mqtt**: Connects to MQTT broker, subscribes to topics, publishes events
- **video**: Manages RTSP video stream decoding and frame buffering

Services communicate with modules via the EventBus.

## Configuration System

Sentinel uses a layered configuration approach:

### Configuration Loading Order
1. **Built-in defaults** (hardcoded in the application)
2. **YAML fragments** in `settings/` directory
3. **config.py** overrides (legacy, optional)

### YAML Configuration Structure

#### Core Settings (settings/core.yaml)
```yaml
mqtt_host: mqtt.local
mqtt_port: 1883
mqtt_user: username
mqtt_password: password
frigate_topic: frigate/events
flight_topic: flights/overhead
camera_name: front_door
camera_rtsp_url: rtsp://...
screen_width: 640
screen_height: 480
fps: 30
startup_screen: auto  # or specific module name
show_header: true
margins:
  top: 10
  bottom: 10
  left: 10
  right: 10
```

#### Priority Configuration (settings/priorities.yaml)
Defines automatic screen switching logic:
```yaml
timeout_seconds: 15          # State expiration timeout
idle:
  cycle:                     # Modules to cycle when idle
    - camera
    - neo_tracker
  dwell_seconds: 20          # Time on each screen
rules:
  - when:
      module: camera
      state: [danger, warning]
    weight: 100              # Higher weight = higher priority
    screen: camera
```

#### Module Configuration (settings/modules/*.yaml)
Per-module settings:
```yaml
enabled: true
path: sentinel.modules.camera
settings:
  zoom_level: 2.5
  zoom_labels: [person, car]
```

### Configuration Migration
Use the migration tool to convert legacy config.py to YAML:
```bash
python -m sentinel.tools.migrate_config --output settings
```

## Development Workflows

### Adding a New Module

1. **Create module package**: `sentinel/modules/mymodule/`
2. **Implement ScreenModule**:
   ```python
   from sentinel.core import ScreenModule

   class MyModule(ScreenModule):
       slug = "mymodule"

       def on_load(self):
           # Subscribe to events
           self.app.event_bus.subscribe("some.event", self._handle_event)

       def on_show(self):
           # Module is now visible
           pass

       def update(self, dt):
           # Update logic every frame
           pass

       def render(self, surface):
           # Required: draw to the pygame surface
           surface.fill((0, 0, 0))

       def _handle_event(self, payload):
           # Report state to trigger screen switching
           self.report_state("active", weight=50, expires_in=10.0)
   ```

3. **Create entry point**: `sentinel/modules/mymodule.py`
   ```python
   from .mymodule.screen import MyModule
   __all__ = ["MyModule"]
   ```

4. **Add configuration**: `settings/modules/mymodule.yaml`
   ```yaml
   enabled: true
   path: sentinel.modules.mymodule.MyModule
   settings:
     custom_option: value
   ```

5. **Update priorities**: Add rules in `settings/priorities.yaml`

6. **Document the module**: Create `docs/modules/mymodule.md`

### Adding a New Service

1. **Create service class**: `sentinel/services/myservice.py`
   ```python
   class MyService:
       def __init__(self, *, app, config, event_bus):
           self.app = app
           self.config = config
           self.event_bus = event_bus

       def start(self):
           # Start background thread/work
           pass

       def stop(self):
           # Graceful shutdown
           pass
   ```

2. **Register in ServiceManager**: Update service discovery logic

3. **Add configuration**: `settings/services/myservice.yaml`

4. **Document the service**: Create `docs/services/myservice.md`

### Modifying the Core Framework

When working on core components:
- **EventBus**: Ensure thread safety with locks
- **ModuleManager**: Test priority resolution thoroughly
- **ServiceManager**: Ensure graceful shutdown
- **Configuration Loader**: Maintain backward compatibility

### Testing on Raspberry Pi

1. **Use the installation script**:
   ```bash
   curl -sSL https://raw.githubusercontent.com/e2equiel/sentinel-crt/main/scripts/install_rpi.sh | sudo bash
   ```

2. **Manual testing**:
   ```bash
   python3 sentinel_crt.py          # Windowed mode
   python3 sentinel_crt.py --fullscreen  # Fullscreen mode
   ```

3. **Check service status**:
   ```bash
   sudo systemctl status sentinel-crt.service
   sudo journalctl -u sentinel-crt.service -f
   ```

### Debugging

- **Enable verbose logging**: Add print statements (no formal logging framework yet)
- **Check event flow**: Add debug prints in EventBus handlers
- **Module state**: Print `self.name`, `self.active`, `self.config` in modules
- **MQTT debugging**: Monitor MQTT topics with `mosquitto_sub`

## Code Conventions

### Python Style
- Follow PEP 8 guidelines
- Use type hints where practical (existing code is partially typed)
- Docstrings use reStructuredText style
- Private methods/attributes prefixed with `_`

### Naming Conventions
- **Classes**: PascalCase (e.g., `ScreenModule`, `EventBus`)
- **Functions/Methods**: snake_case (e.g., `load_configuration`, `on_load`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `COLOR_BLACK`, `THEME_COLORS`)
- **Module files**: snake_case (e.g., `event_bus.py`, `module_manager.py`)

### Module Structure
- Keep modules self-contained in their package
- Use `__init__.py` to expose public API
- Place shared utilities in `sentinel/modules/common/`
- Avoid circular imports (use TYPE_CHECKING for type hints)

### Event Naming
Use hierarchical dot notation:
- `system.*` - System-level events (restart, shutdown)
- `services.{service}.*` - Service-specific events
- `ui.*` - UI-related events (alert, theme change)
- `modules.{module}.*` - Module-specific events (optional)

### Configuration Keys
- Use snake_case for all keys
- Prefix module-specific keys when in core config
- Keep settings flat when possible, nest sparingly

## Common Patterns

### Subscribing to Events in Modules
```python
def on_load(self):
    self.app.event_bus.subscribe("some.event", self._handle_event)

def on_unload(self):
    self.app.event_bus.unsubscribe("some.event", self._handle_event)

def _handle_event(self, payload):
    # Process event
    pass
```

### Reporting Module State
```python
def update(self, dt):
    if self.should_show:
        # Report state with weight and expiry
        self.report_state("alert", weight=100, expires_in=5.0)
    else:
        # Clear state
        self.report_state(None)
```

### Accessing Configuration
```python
def on_load(self):
    # Module-specific config
    zoom_level = self.config.get("zoom_level", 2.0)

    # Core config via app
    screen_width = self.app.core_settings.get("screen_width", 640)
```

### Thread-Safe Data Access
```python
def update(self, dt):
    with self.app.data_lock:
        # Access shared data safely
        data = self.shared_data.copy()
```

### Drawing with Theme Colors
```python
def render(self, surface):
    color = self.app.current_theme_color  # Changes with alert level
    pygame.draw.rect(surface, color, rect)
```

## Important Constraints

### Display Considerations
- Target resolution: 640x480 (CRT standard)
- Use VT323 font for retro aesthetic
- Respect margins defined in config
- All drawing should work in both windowed and fullscreen modes

### Performance
- Target 30 FPS on Raspberry Pi 3B+
- Minimize allocations in render/update loops
- Use frame deltas (dt) for animations
- Cache fonts, surfaces when possible

### MQTT
- Handle reconnection gracefully
- Don't block on MQTT operations
- Validate all incoming message formats
- Use QoS 0 for frequent updates

### Video Streaming
- RTSP streams handled by video service
- Frame decoding happens in background thread
- Modules should never block waiting for frames

## Git Workflow

### Branch Strategy
- `main` - Production-ready code
- Feature branches: `feature/description` or `claude/session-id`
- Bug fixes: `fix/description`

### Commit Messages
- Use imperative mood ("Add feature" not "Added feature")
- Reference issues/PRs when applicable
- Format: `[Component] Brief description`
  - Examples: `[Camera] Add zoom animation smoothing`, `[MQTT] Fix reconnection logic`

### Pull Requests
- Keep PRs focused on a single feature/fix
- Update documentation in the same PR
- Test on Raspberry Pi if hardware-related
- Update CLAUDE.md if architecture changes

## Testing Checklist

Before submitting changes:
- [ ] Code runs without errors in windowed mode
- [ ] Fullscreen mode works correctly
- [ ] MQTT connection/reconnection works
- [ ] No regressions in existing modules
- [ ] Configuration loading works with YAML and config.py
- [ ] Documentation updated if API changed
- [ ] No Python linter warnings (if applicable)
- [ ] Tested on actual hardware (Raspberry Pi) for hardware-related changes

## Security Considerations

- **config.py is gitignored** - Contains credentials
- **YAML files can be committed** - Use environment variables for secrets
- **MQTT credentials** - Always use authentication
- **RTSP URLs** - Contain camera credentials, never log them
- **Network exposure** - Application is client-only, no server component

## Common Issues and Solutions

### Module Not Loading
- Check `enabled: true` in module YAML config
- Verify Python import path in `path:` field
- Look for exceptions in console output during startup

### Screen Not Switching
- Check priority rules in `settings/priorities.yaml`
- Verify module is calling `report_state()` correctly
- Check state expiry times (may be too short)
- Ensure timeout_seconds allows transitions

### MQTT Connection Failing
- Verify broker address and port
- Check credentials in core.yaml or config.py
- Test with `mosquitto_sub` on same network
- Check firewall rules on broker

### Video Stream Not Showing
- Verify RTSP URL is accessible
- Check camera credentials
- Test URL with VLC or ffplay
- Ensure OpenCV compiled with FFMPEG support

### Font Not Loading
- Verify `sentinel/assets/fonts/VT323-Regular.ttf` exists
- Check file permissions
- Font loading happens early, check console for errors

## Resources

### Documentation
- Main README: `README.md`
- Settings Guide: `settings/README.md`
- Module Docs: `docs/modules/*.md`
- Service Docs: `docs/services/*.md`

### External Dependencies
- [Pygame Documentation](https://www.pygame.org/docs/)
- [Paho-MQTT Documentation](https://www.eclipse.org/paho/index.php?page=clients/python/docs/index.php)
- [OpenCV Python](https://docs.opencv.org/4.x/d6/d00/tutorial_py_root.html)
- [Frigate NVR](https://frigate.video/)

### Related Projects
- Home Assistant FlightRadar24 Integration
- ADS-B Exchange Integration
- Mapbox API for radar maps

## Maintenance Notes

### Backward Compatibility
- Config.py support must be maintained
- YAML configuration is preferred for new features
- Migration tool should handle config.py → YAML conversion

### Future Enhancements
Consider these architectural patterns for future work:
- Formal logging framework (replace print statements)
- Plugin system for third-party modules
- REST API for remote control
- Web-based configuration UI
- Unit tests for core components
- CI/CD pipeline for automated testing

## Contact and Support

- **Repository**: https://github.com/e2equiel/sentinel-crt
- **Issues**: Report bugs and feature requests via GitHub Issues
- **Pull Requests**: Contributions welcome, follow the guidelines above

---

**Last Updated**: 2025-11-13
**Version**: Based on commit 392743f
