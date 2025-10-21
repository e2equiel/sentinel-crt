# Camera Module

## Overview

`CameraModule` renders the Frigate camera feed, overlays detections, and manages alert levels inside the CRT interface. It listens to MQTT detections and frames delivered by the video capture service to maintain a snapshot, bounding boxes, and a zoomed viewport for objects of interest.

## Configuration

The module relies on the core configuration loaded into `config.CONFIG`:

- `camera_name`, `camera_rtsp_url`, and `frigate_host` identify the camera and the Frigate instance that emits MQTT events.
- `frigate_resolution` defines the native frame resolution so the zoom viewport can be scaled correctly.
- `zoom_labels`, `zoom_level`, `zoom_reset_time`, and `zoom_speed` tune the adaptive zoom controller, while `bbox_delay` governs how long detections stay visible.
- `alert_zones.warning` and `alert_zones.danger` describe the Frigate zones that trigger UI alert colors.
- Layout values such as `margins`, `screen_width`, `screen_height`, and `show_header` determine how the module arranges the live view and status panel.

## Event Flow

On load the module subscribes to:

- `services.mqtt.detection` for Frigate detection payloads.
- `services.mqtt.status` for MQTT connection updates.
- `services.video.frame` for decoded frames provided by the video capture service.
- `services.video.status` for capture status text.

Whenever alert levels change the module publishes `ui.alert` events so the global header can react.

## Display Elements

The status panel shows target metadata, MQTT activity, and service status, while the main viewport renders the live or zoomed frame. Optional grid overlays visualize zoom focus areas and bounding boxes highlight tracked detections.
