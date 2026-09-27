import csv
import json
import math
import os
import time
from datetime import datetime, timezone
from uuid import uuid4


DEFAULT_CONFIG = {
    "STATIONARY_RADIUS_M": 2.0,
    "STATIONARY_DURATION_S": 10,
    "TILT_WARNING_DEG": 12.0,
    "TILT_CRITICAL_DEG": 18.0,
    "VIBRATION_WARNING_RMS": 0.15,
    "VIBRATION_CRITICAL_RMS": 0.25,
    "TILT_DURATION_S": 8.0,
    "VIBRATION_DURATION_S": 8.0,
}

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "safety_config.json")


def load_runtime_config(path=CONFIG_PATH):
    config = DEFAULT_CONFIG.copy()
    try:
        with open(path, "r") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            config.update({k: v for k, v in loaded.items() if v is not None})
    except (FileNotFoundError, TypeError, ValueError, OSError):
        return config
    return config


class TripTracker:
    def __init__(self, base_dir="."):
        self.base_dir = base_dir
        self.active = False
        self.start_time = None
        self.end_time = None
        self.start_lat = None
        self.start_lon = None
        self.end_lat = None
        self.end_lon = None
        self.track_points = []
        self.total_distance_km = 0.0
        self.trip_id = None
        self._last_point = None
        self._ensure_log()

    def _ensure_log(self):
        os.makedirs(self.base_dir, exist_ok=True)
        path = os.path.join(self.base_dir, "log_trip.csv")
        if os.path.exists(path):
            return
        with open(path, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([
                "timestamp", "trip_id", "event_type", "latitude", "longitude",
                "distance_km", "elapsed_s", "status"
            ])

    def start_trip(self, lat=None, lon=None):
        now = datetime.now().isoformat(timespec="seconds")
        self.active = True
        self.start_time = now
        self.end_time = None
        self.start_lat = lat
        self.start_lon = lon
        self.end_lat = None
        self.end_lon = None
        self.trip_id = f"trip-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"
        self.track_points = []
        self.total_distance_km = 0.0
        self._last_point = (lat, lon) if lat is not None and lon is not None else None
        self._append_log(now, "START", lat, lon, 0.0, 0, "ACTIVE")

    def update_position(self, lat, lon, now=None):
        if not self.active:
            return
        if lat is None or lon is None:
            return
        if self._last_point is not None:
            distance_km = self._haversine_km(self._last_point, (lat, lon))
            self.total_distance_km += distance_km
        else:
            distance_km = 0.0
        self._last_point = (lat, lon)
        self.track_points.append({
            "timestamp": now or datetime.now().isoformat(timespec="seconds"),
            "lat": lat,
            "lon": lon,
            "distance_km": round(self.total_distance_km, 4),
        })

    def end_trip(self, lat=None, lon=None):
        if not self.active:
            return
        now = datetime.now().isoformat(timespec="seconds")
        self.end_time = now
        self.end_lat = lat
        self.end_lon = lon
        self.active = False
        elapsed_s = 0
        if self.start_time:
            try:
                start_dt = datetime.fromisoformat(self.start_time)
                end_dt = datetime.fromisoformat(now)
                elapsed_s = int((end_dt - start_dt).total_seconds())
            except Exception:
                elapsed_s = 0
        self._append_log(now, "END", lat, lon, round(self.total_distance_km, 4), elapsed_s, "COMPLETED")

    def _append_log(self, timestamp, event_type, lat, lon, distance_km, elapsed_s, status):
        path = os.path.join(self.base_dir, "log_trip.csv")
        with open(path, "a", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([
                timestamp,
                self.trip_id or "",
                event_type,
                "" if lat is None else lat,
                "" if lon is None else lon,
                distance_km,
                elapsed_s,
                status,
            ])

    @staticmethod
    def _haversine_km(point_a, point_b):
        if point_a is None or point_b is None:
            return 0.0
        lat1, lon1 = map(math.radians, point_a)
        lat2, lon2 = map(math.radians, point_b)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return 2 * 6371.0 * math.asin(math.sqrt(a))

    def snapshot(self):
        elapsed_s = 0
        if self.start_time and self.active:
            try:
                elapsed_s = int((datetime.now() - datetime.fromisoformat(self.start_time)).total_seconds())
            except Exception:
                elapsed_s = 0
        return {
            "active": self.active,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "start_lat": self.start_lat,
            "start_lon": self.start_lon,
            "end_lat": self.end_lat,
            "end_lon": self.end_lon,
            "total_distance_km": round(self.total_distance_km, 4),
            "elapsed_s": elapsed_s,
            "track_points": len(self.track_points),
            "trip_id": self.trip_id,
        }


class SafetyEventEngine:
    def __init__(self, base_dir=".", config=None):
        self.base_dir = base_dir
        self.config = load_runtime_config()
        if config:
            self.config.update(config)
        self.trip = TripTracker(base_dir=base_dir)
        self._stationary_event = None
        self._terrain_event = None
        self._gps_last_valid = None
        self._stationary_started = None
        self._stationary_vibration_count = 0
        self._terrain_started = None
        self._terrain_count = 0
        self._ensure_logs()

    def _ensure_logs(self):
        os.makedirs(self.base_dir, exist_ok=True)
        for name in [
            "log_stationary_vibration.csv",
            "log_terrain_stability.csv",
            "log_blindspot.csv",
            "log_sensor_tambahan.csv",
        ]:
            path = os.path.join(self.base_dir, name)
            if os.path.exists(path):
                continue
            with open(path, "w", newline="") as handle:
                writer = csv.writer(handle)
                if name == "log_stationary_vibration.csv":
                    writer.writerow([
                        "timestamp", "event_id", "event_type", "duration_s", "latitude",
                        "longitude", "gps_status", "vibration_rms", "vibration_peak",
                        "sw420_event_count", "machine_state", "severity", "reason"
                    ])
                elif name == "log_terrain_stability.csv":
                    writer.writerow([
                        "timestamp", "event_id", "event_type", "duration_s", "latitude",
                        "longitude", "tilt_x", "tilt_y", "vibration_rms", "vibration_peak",
                        "sw420_event_count", "machine_state", "severity", "trigger_reason"
                    ])
                elif name == "log_blindspot.csv":
                    writer.writerow([
                        "timestamp", "event_id", "event_type", "severity", "person_count",
                        "nearest_distance_m", "duration_s", "status"
                    ])
                else:
                    writer.writerow([
                        "timestamp", "event_id", "event_type", "severity", "status"
                    ])

    def _event_id(self, prefix="evt"):
        return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"

    def _haversine_m(self, point_a, point_b):
        if point_a is None or point_b is None:
            return float("inf")
        lat1, lon1 = map(math.radians, point_a)
        lat2, lon2 = map(math.radians, point_b)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return 2 * 6371000.0 * math.asin(math.sqrt(a))

    def _write_csv(self, path_name, row):
        path = os.path.join(self.base_dir, path_name)
        with open(path, "a", newline="") as handle:
            csv.writer(handle).writerow(row)

    def check_stationary_vibration(self, fix, lat, lon, gps_status, vibration_rms, vibration_peak, sw420_event_count, machine_state, timestamp=None):
        if fix != 1 or lat in (None, 0.0) or lon in (None, 0.0):
            self._stationary_started = None
            return None
        point = (lat, lon)
        if self._gps_last_valid is None:
            self._gps_last_valid = point
        movement_m = self._haversine_m(self._gps_last_valid, point)
        if movement_m <= self.config["STATIONARY_RADIUS_M"]:
            if self._stationary_started is None:
                self._stationary_started = time.time()
            duration_s = time.time() - self._stationary_started
            if vibration_rms >= self.config["VIBRATION_WARNING_RMS"] and duration_s >= self.config["STATIONARY_DURATION_S"]:
                event = {
                    "event_id": self._event_id("stationary"),
                    "timestamp": timestamp or datetime.now().isoformat(timespec="seconds"),
                    "duration_s": round(duration_s, 1),
                    "latitude": lat,
                    "longitude": lon,
                    "gps_status": gps_status,
                    "vibration_rms": round(float(vibration_rms), 4),
                    "vibration_peak": round(float(vibration_peak), 4),
                    "sw420_event_count": int(sw420_event_count),
                    "machine_state": machine_state,
                    "severity": "WARNING" if vibration_rms < self.config["VIBRATION_CRITICAL_RMS"] else "HIGH RISK",
                    "reason": "stationary with vibration over threshold",
                }
                self._stationary_event = event
                self._write_csv(
                    "log_stationary_vibration.csv",
                    [
                        event["timestamp"], event["event_id"], "STATIONARY VIBRATION", event["duration_s"],
                        event["latitude"], event["longitude"], event["gps_status"], event["vibration_rms"],
                        event["vibration_peak"], event["sw420_event_count"], event["machine_state"], event["severity"], event["reason"]
                    ]
                )
                return event
        else:
            self._stationary_started = None
            self._gps_last_valid = point
        self._gps_last_valid = point
        return None

    def check_terrain_stability(self, fix, lat, lon, gps_status, tilt_x, tilt_y, vibration_rms, vibration_peak, sw420_event_count, machine_state, timestamp=None):
        if fix != 1 or lat in (None, 0.0) or lon in (None, 0.0):
            self._terrain_started = None
            return None
        tilt_abs = max(abs(float(tilt_x)), abs(float(tilt_y)))
        vibration = float(vibration_rms)
        sw420_count = int(sw420_event_count)
        threshold_reason = []
        if tilt_abs >= self.config["TILT_WARNING_DEG"]:
            threshold_reason.append("tilt")
        if vibration >= self.config["VIBRATION_WARNING_RMS"]:
            threshold_reason.append("vibration")
        if sw420_count > 0:
            threshold_reason.append("sw420")
        if not threshold_reason:
            self._terrain_started = None
            return None
        if self._terrain_started is None:
            self._terrain_started = time.time()
        duration_s = time.time() - self._terrain_started
        if duration_s < self.config["TILT_DURATION_S"] and duration_s < self.config["VIBRATION_DURATION_S"]:
            return None
        severity = "WARNING"
        if tilt_abs >= self.config["TILT_CRITICAL_DEG"] or vibration >= self.config["VIBRATION_CRITICAL_RMS"] or sw420_count >= 2:
            severity = "HIGH RISK"
        event = {
            "event_id": self._event_id("terrain"),
            "timestamp": timestamp or datetime.now().isoformat(timespec="seconds"),
            "duration_s": round(duration_s, 1),
            "latitude": lat,
            "longitude": lon,
            "gps_status": gps_status,
            "tilt_x": round(float(tilt_x), 2),
            "tilt_y": round(float(tilt_y), 2),
            "vibration_rms": round(vibration, 4),
            "vibration_peak": round(float(vibration_peak), 4),
            "sw420_event_count": sw420_count,
            "machine_state": machine_state,
            "severity": severity,
            "trigger_reason": ", ".join(threshold_reason),
        }
        self._terrain_event = event
        self._write_csv(
            "log_terrain_stability.csv",
            [
                event["timestamp"], event["event_id"], "TERRAIN STABILITY", event["duration_s"],
                event["latitude"], event["longitude"], event["tilt_x"], event["tilt_y"],
                event["vibration_rms"], event["vibration_peak"], event["sw420_event_count"],
                event["machine_state"], event["severity"], event["trigger_reason"]
            ]
        )
        return event

    def update(self, gps_fix, gps_lat, gps_lon, gps_status, vibration_rms, vibration_peak, sw420_event_count, machine_state, tilt_x, tilt_y, timestamp=None):
        stationary = self.check_stationary_vibration(
            gps_fix, gps_lat, gps_lon, gps_status,
            float(vibration_rms or 0.0), float(vibration_peak or 0.0),
            sw420_event_count, machine_state, timestamp=timestamp
        )
        terrain = self.check_terrain_stability(
            gps_fix, gps_lat, gps_lon, gps_status,
            tilt_x, tilt_y,
            float(vibration_rms or 0.0), float(vibration_peak or 0.0),
            sw420_event_count, machine_state, timestamp=timestamp
        )
        trip_snapshot = self.trip.snapshot()
        return {
            "stationary_vibration": stationary,
            "terrain_stability": terrain,
            "trip": trip_snapshot,
            "gps_status": gps_status,
            "last_valid_point": self._gps_last_valid,
        }

    def start_trip(self, lat=None, lon=None):
        self.trip.start_trip(lat, lon)

    def end_trip(self, lat=None, lon=None):
        self.trip.end_trip(lat, lon)

    def record_trip_point(self, lat, lon, timestamp=None):
        self.trip.update_position(lat, lon, timestamp)


if __name__ == "__main__":
    engine = SafetyEventEngine(base_dir=".")
    event = engine.check_stationary_vibration(1, -6.2, 106.8, "GPS FIX AKTIF", 0.22, 0.33, 1, "ON", "2026-09-27T00:00:00")
    print(event)
