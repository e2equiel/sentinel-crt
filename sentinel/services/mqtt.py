"""MQTT client wrapper used by the Sentinel runtime."""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Mapping, Optional

import paho.mqtt.client as mqtt


class MQTTService:
    """Background MQTT client that publishes events via the runtime bus."""

    def __init__(self, *, app: Any, config: Optional[Mapping[str, Any]], event_bus: Any) -> None:
        self._core: Mapping[str, Any] = getattr(app, "core_settings", {})
        self._options: Mapping[str, Any] = config or {}
        self._event_bus = event_bus
        self._client: Optional[mqtt.Client] = None
        self._lock = threading.Lock()
        self.status = "OFFLINE"
        self._detection_event = self._options.get("detection_event", "services.mqtt.detection")
        self._flights_event = self._options.get("flights_event", "services.mqtt.flights")
        self._restart_event = self._options.get("restart_event", "system.restart")
        self._status_event = self._options.get("status_event", "services.mqtt.status")

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        """Create and start the MQTT client loop."""
        self.stop()
        try:
            client_id = f"sentinel_crt_ui_{time.time()}"
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
            username = self._get_setting("mqtt_user")
            password = self._get_setting("mqtt_password")
            if username or password:
                client.username_pw_set(username, password)
            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_message = self._on_message
            host = self._get_setting("mqtt_host", "localhost")
            port = int(self._get_setting("mqtt_port", 1883))
            client.connect_async(host, port, 60)
            client.loop_start()
            self._client = client
            self._set_status("CONNECTING...")
        except Exception as exc:
            print(f"Error starting MQTT client: {exc}")
            self._client = None
            self._set_status("ERROR")

    def stop(self) -> None:
        """Stop the MQTT loop and disconnect the client."""
        with self._lock:
            client = self._client
            self._client = None
        if client is None:
            return
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass
        self._set_status("DISCONNECTED")

    # ------------------------------------------------------------------ internal callbacks
    def _set_status(self, value: str) -> None:
        self.status = value
        if self._status_event and self._event_bus:
            try:
                self._event_bus.publish(self._status_event, value)
            except Exception as exc:
                print(f"Error publishing MQTT status: {exc}")

    def _get_setting(self, key: str, default: Any = None) -> Any:
        if key in self._options:
            return self._options[key]
        return self._core.get(key, default)

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:  # noqa: D401
        if reason_code.value == 0:
            self._set_status("CONNECTED")
            detection_topic = self._get_setting("frigate_topic")
            flight_topic = self._get_setting("flight_topic")
            restart_topic = self._get_setting("mqtt_restart_topic")
            if detection_topic:
                client.subscribe(detection_topic)
            if flight_topic:
                client.subscribe(flight_topic)
            if restart_topic:
                client.subscribe(restart_topic)
        else:
            self._set_status(f"FAILED ({reason_code.value})")

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:  # noqa: D401
        if reason_code is not None and reason_code.value != 0:
            self._set_status("DISCONNECTED")

    def _on_message(self, client, userdata, msg) -> None:  # noqa: D401
        topic = msg.topic
        try:
            payload_text = msg.payload.decode("utf-8")
        except UnicodeDecodeError:
            print(f"Error decoding MQTT payload from topic {topic}")
            return

        restart_topic = self._get_setting("mqtt_restart_topic")
        restart_payload = self._get_setting("mqtt_restart_payload")
        if restart_topic and topic == restart_topic and payload_text == restart_payload:
            if self._restart_event and self._event_bus:
                self._event_bus.publish(self._restart_event)
            return

        try:
            payload_obj = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            print(f"Error decoding MQTT JSON from topic {topic}: {exc}")
            return

        detection_topic = self._get_setting("frigate_topic")
        flight_topic = self._get_setting("flight_topic")
        try:
            if detection_topic and topic == detection_topic:
                if self._event_bus and self._detection_event:
                    self._event_bus.publish(self._detection_event, payload_obj)
            elif flight_topic and topic == flight_topic:
                if self._event_bus and self._flights_event:
                    self._event_bus.publish(self._flights_event, payload_obj)
        except Exception as exc:
            print(f"Error dispatching MQTT message from topic {topic}: {exc}")


__all__ = ["MQTTService"]
