# Video Capture Service

## Overview

`VideoCaptureService` opens the configured RTSP stream with OpenCV, continuously reads frames on a background thread, and publishes them to the event bus for the camera module.

## Configuration

- `camera_rtsp_url` supplies the stream URL (service-specific options take precedence over core settings).
- `reconnect_delay` controls how long to wait before retrying after an error.
- `frigate_resolution` (from the core settings) is used to request a specific frame size.
- Event names can be overridden via `frame_event` and `status_event`.

## Event Flow

While running the service publishes:

- Status updates (`INITIALIZING`, `ONLINE`, `RECONNECTING...`, etc.) on `services.video.status`.
- Frames tagged with timestamps on `services.video.frame`.

If the connection drops the loop releases the capture device, broadcasts a reconnecting status, waits the configured delay, and tries again.
