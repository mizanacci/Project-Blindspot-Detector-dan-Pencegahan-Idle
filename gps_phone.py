import copy
import threading
import time
from datetime import datetime

from flask import Flask, jsonify, request


PHONE_GPS_TIMEOUT_S = 5.0
DEFAULT_MAX_ACCEPTABLE_PHONE_ACCURACY_M = 30.0


class PhoneGPSReceiver:
    """Thread-safe receiver for Android GPS sent over Wi-Fi HTTP."""

    def __init__(self, timeout_s=PHONE_GPS_TIMEOUT_S, max_accuracy_m=DEFAULT_MAX_ACCEPTABLE_PHONE_ACCURACY_M, host="0.0.0.0", port=8765):
        self.lock = threading.Lock()
        self.timeout_s = timeout_s
        self.max_accuracy_m = max_accuracy_m
        self.host = host
        self.port = port
        self.latest = {
            "source": "phone",
            "fix": False,
            "latitude": None,
            "longitude": None,
            "accuracy_m": None,
            "altitude_m": None,
            "speed_mps": None,
            "timestamp": None,
            "received_at": None,
            "age_s": None,
            "status": "PHONE GPS NO DATA",
        }
        self.app = Flask(__name__)
        self._register_routes()

    @staticmethod
    def _is_number(value):
        try:
            return value is not None and float(value) == float(value)
        except (TypeError, ValueError):
            return False

    def validate_payload(self, payload):
        if not isinstance(payload, dict):
            return False

        lat = payload.get("latitude")
        lon = payload.get("longitude")
        if self._is_number(lat) is False or self._is_number(lon) is False:
            return False
        if not (-90.0 <= float(lat) <= 90.0):
            return False
        if not (-180.0 <= float(lon) <= 180.0):
            return False

        accuracy = payload.get("accuracy_m")
        if accuracy is not None and self._is_number(accuracy) is False:
            return False
        if accuracy is not None and float(accuracy) < 0:
            return False

        altitude = payload.get("altitude_m")
        if altitude is not None and self._is_number(altitude) is False:
            return False

        speed = payload.get("speed_mps")
        if speed is not None and self._is_number(speed) is False:
            return False

        return True

    def update_from_payload(self, payload):
        if not self.validate_payload(payload):
            return False

        lat = float(payload["latitude"])
        lon = float(payload["longitude"])
        accuracy = float(payload.get("accuracy_m", 0.0) or 0.0)
        altitude = payload.get("altitude_m")
        speed = payload.get("speed_mps")
        timestamp = payload.get("timestamp") or datetime.now().isoformat(timespec="seconds")
        now = time.time()

        with self.lock:
            self.latest = {
                "source": "phone",
                "fix": True,
                "latitude": lat,
                "longitude": lon,
                "accuracy_m": accuracy,
                "altitude_m": float(altitude) if altitude is not None else None,
                "speed_mps": float(speed) if speed is not None else None,
                "timestamp": timestamp,
                "received_at": now,
                "age_s": 0.0,
                "status": "PHONE GPS FIX ACTIVE",
            }
        return True

    def get_latest(self):
        with self.lock:
            latest = copy.deepcopy(self.latest)
            if latest.get("received_at") is not None:
                latest["age_s"] = max(0.0, time.time() - float(latest["received_at"]))
            return latest

    def get_latest_for_manager(self):
        latest = self.get_latest()
        if not latest.get("fix"):
            return {"fix": False, "source": None, "latitude": None, "longitude": None, "accuracy_m": None, "altitude_m": None, "speed_mps": None, "timestamp": None, "status": "PHONE GPS NO DATA"}

        if latest.get("age_s", 0.0) > self.timeout_s:
            return {"fix": False, "source": None, "latitude": None, "longitude": None, "accuracy_m": latest.get("accuracy_m"), "altitude_m": latest.get("altitude_m"), "speed_mps": latest.get("speed_mps"), "timestamp": latest.get("timestamp"), "status": "PHONE GPS STALE"}

        if latest.get("accuracy_m") is not None and float(latest["accuracy_m"]) > self.max_accuracy_m:
            return {"fix": False, "source": None, "latitude": None, "longitude": None, "accuracy_m": latest.get("accuracy_m"), "altitude_m": latest.get("altitude_m"), "speed_mps": latest.get("speed_mps"), "timestamp": latest.get("timestamp"), "status": "PHONE GPS ACCURACY TOO LOW"}

        return {
            "fix": True,
            "source": "phone",
            "latitude": latest.get("latitude"),
            "longitude": latest.get("longitude"),
            "accuracy_m": latest.get("accuracy_m"),
            "altitude_m": latest.get("altitude_m"),
            "speed_mps": latest.get("speed_mps"),
            "timestamp": latest.get("timestamp"),
            "status": "PHONE GPS FIX ACTIVE",
        }

    def _register_routes(self):
        @self.app.route("/gps", methods=["POST"])
        def post_gps():
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify({"ok": False, "error": "JSON invalid"}), 400
            if not self.validate_payload(payload):
                return jsonify({"ok": False, "error": "payload invalid"}), 400
            self.update_from_payload(payload)
            return jsonify({"ok": True})

        @self.app.route("/gps", methods=["GET"])
        def get_gps():
            latest = self.get_latest()
            if not latest.get("fix"):
                return jsonify({
                    "source": "phone",
                    "fix": False,
                    "latitude": None,
                    "longitude": None,
                    "accuracy_m": None,
                    "altitude_m": None,
                    "speed_mps": None,
                    "timestamp": None,
                    "status": "PHONE GPS NO DATA",
                })
            return jsonify({
                "source": "phone",
                "fix": True,
                "latitude": latest.get("latitude"),
                "longitude": latest.get("longitude"),
                "accuracy_m": latest.get("accuracy_m"),
                "altitude_m": latest.get("altitude_m"),
                "speed_mps": latest.get("speed_mps"),
                "timestamp": latest.get("timestamp"),
                "status": "PHONE GPS FIX ACTIVE",
            })

    def start_server(self, host=None, port=None):
        host = host or self.host
        port = int(port or self.port)
        thread = threading.Thread(
            target=lambda: self.app.run(host=host, port=port, threaded=True, debug=False, use_reloader=False),
            daemon=True,
        )
        thread.start()
        return thread


def create_phone_gps_server(timeout_s=PHONE_GPS_TIMEOUT_S, max_accuracy_m=DEFAULT_MAX_ACCEPTABLE_PHONE_ACCURACY_M):
    return PhoneGPSReceiver(timeout_s=timeout_s, max_accuracy_m=max_accuracy_m)
