# MQTT Service

## Overview

`MQTTService` maintains a background connection to the configured broker, subscribes to Frigate detection topics, flight tracking topics, and an optional restart topic, and translates incoming payloads into internal events.

## Configuration

The service merges options provided in `settings.services` with global `core_settings`:

- `mqtt_host`, `mqtt_port`, `mqtt_user`, and `mqtt_password` authenticate the client.
- `frigate_topic`, `flight_topic`, and `mqtt_restart_topic` define subscriptions.
- `mqtt_restart_payload` guards the restart command.
- Event names can be overridden via `detection_event`, `flights_event`, `restart_event`, and `status_event`.

## Event Flow

When connected the service:

- Publishes status changes through `services.mqtt.status` (or the configured override).
- Dispatches detection payloads on `services.mqtt.detection`.
- Dispatches flight lists on `services.mqtt.flights`.
- Emits `system.restart` when the restart topic receives the expected payload.

The client runs on a background thread started with `loop_start()` and is stopped during shutdown.
