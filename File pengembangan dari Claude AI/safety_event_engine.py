import csv
import json
import math
import os
import tempfile
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
    "IDLE_DURATION_THRESHOLD_S": 10.0,
    "IDLE_DISTANCE_THRESHOLD_M": 1.5,
    "IDLE_LOG_UPDATE_INTERVAL_S": 30.0,
    "HEAVY_VIBRATION_THRESHOLD": 0.30,
    "TILT_THRESHOLD_DEG": 15.0,
    "IDLE_GEOFENCE": {
        "enabled": False,
        "name": "",
        "bypass_idle": False,
        "points": [],
    },
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


def is_point_inside_idle_geofence(latitude, longitude, polygon_points):
    """Return True for a valid point inside or on the polygon boundary."""
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        return False
    if not isinstance(polygon_points, (list, tuple)) or len(polygon_points) < 3:
        return False

    polygon = []
    for item in polygon_points:
        try:
            point_lat = float(item["lat"])
            point_lon = float(item["lon"])
        except (TypeError, ValueError, KeyError):
            return False
        if not math.isfinite(point_lat) or not math.isfinite(point_lon):
            return False
        polygon.append((point_lat, point_lon))

    inside = False
    for index, (lat_a, lon_a) in enumerate(polygon):
        lat_b, lon_b = polygon[index - 1]
        cross = ((lon_a - longitude) * (lat_b - latitude) -
             (lat_a - latitude) * (lon_b - longitude))
        if (min(lat_a, lat_b) <= latitude <= max(lat_a, lat_b) and
                min(lon_a, lon_b) <= longitude <= max(lon_a, lon_b) and
                abs(cross) <= 1e-12):
            return True
        if ((lat_a > latitude) != (lat_b > latitude)):
            crossing_lon = ((lon_b - lon_a) * (latitude - lat_a) /
                            (lat_b - lat_a) + lon_a)
            if longitude < crossing_lon:
                inside = not inside
    return inside


class TripTracker:
    DETAIL_LOG = "log_trip_details.csv"
    DETAIL_FIELDS = [
        "record_type", "trip_id", "timestamp", "start_timestamp",
        "start_latitude", "start_longitude", "end_timestamp", "end_latitude",
        "end_longitude", "duration_s", "duration_min", "total_distance_km",
        "track_points", "gps_start_status", "gps_end_status", "latitude",
        "longitude", "distance_from_previous_m", "cumulative_distance_km",
        "gps_status",
    ]

    def __init__(self, base_dir=".", min_distance_m=2.0):
        self.base_dir = base_dir
        self.min_distance_m = max(0.0, float(min_distance_m))
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
        self._gps_start_status = None
        self._gps_end_status = None
        self._duration_s = 0.0
        self._ensure_log()

    def _ensure_log(self):
        os.makedirs(self.base_dir, exist_ok=True)
        path = os.path.join(self.base_dir, "log_trip.csv")
        if not os.path.exists(path):
            with open(path, "w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow([
                    "timestamp", "trip_id", "event_type", "latitude", "longitude",
                    "distance_km", "elapsed_s", "status"
                ])
        detail_path = os.path.join(self.base_dir, self.DETAIL_LOG)
        if not os.path.exists(detail_path):
            with open(detail_path, "w", newline="") as handle:
                csv.DictWriter(handle, fieldnames=self.DETAIL_FIELDS).writeheader()

    @staticmethod
    def valid_gps_point(fix, lat, lon):
        if not fix:
            return None
        try:
            latitude = float(lat)
            longitude = float(lon)
        except (TypeError, ValueError):
            return None
        if (not math.isfinite(latitude) or not math.isfinite(longitude) or
                not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0):
            return None
        return latitude, longitude

    @staticmethod
    def _elapsed_seconds(start_timestamp, end_timestamp):
        try:
            start = datetime.fromisoformat(start_timestamp)
            end = datetime.fromisoformat(end_timestamp)
            if start.tzinfo is None and end.tzinfo is not None:
                start = start.replace(tzinfo=end.tzinfo)
            elif start.tzinfo is not None and end.tzinfo is None:
                end = end.replace(tzinfo=start.tzinfo)
            return max(0.0, (end - start).total_seconds())
        except (TypeError, ValueError):
            return 0.0

    def _append_detail(self, row):
        path = os.path.join(self.base_dir, self.DETAIL_LOG)
        with open(path, "a", newline="") as handle:
            csv.DictWriter(handle, fieldnames=self.DETAIL_FIELDS).writerow(row)

    def _append_track_point(self, point, timestamp, distance_m, gps_status):
        cumulative_km = round(self.total_distance_km, 6)
        track_point = {
            "timestamp": timestamp,
            "lat": point[0],
            "lon": point[1],
            "distance_from_previous_m": round(distance_m, 2),
            "distance_km": cumulative_km,
            "gps_status": gps_status,
        }
        self.track_points.append(track_point)
        self._append_detail({
            "record_type": "TRACK_POINT",
            "trip_id": self.trip_id,
            "timestamp": timestamp,
            "latitude": point[0],
            "longitude": point[1],
            "distance_from_previous_m": round(distance_m, 2),
            "cumulative_distance_km": cumulative_km,
            "gps_status": gps_status,
        })

    def start_trip(self, lat=None, lon=None, timestamp=None, gps_status="GPS_VALID"):
        if self.active:
            return self.snapshot()
        point = self.valid_gps_point(gps_status == "GPS_VALID", lat, lon)
        if point is None:
            gps_status = "NO_FIX"

        now = timestamp or datetime.now().astimezone().isoformat(timespec="seconds")
        self.active = True
        self.start_time = now
        self.end_time = None
        self.start_lat = point[0] if point is not None else None
        self.start_lon = point[1] if point is not None else None
        self.end_lat = None
        self.end_lon = None
        self.trip_id = f"trip-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"
        self.track_points = []
        self.total_distance_km = 0.0
        self._duration_s = 0.0
        self._gps_start_status = gps_status
        self._gps_end_status = None
        self._last_point = point
        self._append_log(
            now, "START", self.start_lat, self.start_lon, 0.0, 0, "ACTIVE"
        )
        if point is not None:
            self._append_track_point(point, now, 0.0, gps_status)
        return self.snapshot()

    def update_position(self, lat, lon, now=None, gps_status="GPS_VALID"):
        if not self.active:
            return False
        point = self.valid_gps_point(gps_status == "GPS_VALID", lat, lon)
        if point is None:
            return False
        timestamp = now or datetime.now().astimezone().isoformat(timespec="seconds")
        if self._last_point is not None:
            distance_m = self._haversine_m(self._last_point, point)
            if distance_m < self.min_distance_m:
                return False
        else:
            distance_m = 0.0
            if self.start_lat is None or self.start_lon is None:
                self.start_lat, self.start_lon = point
                self._gps_start_status = "GPS_VALID"
        self.total_distance_km += distance_m / 1000.0
        self._last_point = point
        self._append_track_point(point, timestamp, distance_m, gps_status)
        return True

    def end_trip(self, lat=None, lon=None, timestamp=None, gps_status=None):
        if not self.active:
            return self.snapshot()
        now = timestamp or datetime.now().astimezone().isoformat(timespec="seconds")
        end_status = gps_status or ("GPS_VALID" if lat is not None and lon is not None else "NO_FIX")
        point = self.valid_gps_point(end_status == "GPS_VALID", lat, lon)
        if point is not None:
            self.update_position(point[0], point[1], now=now, gps_status="GPS_VALID")
        elif self._last_point is not None:
            point = self._last_point
            end_status = "LAST_VALID_POINT"
        else:
            end_status = "NO_FIX"

        self.end_time = now
        self.end_lat = point[0] if point is not None else None
        self.end_lon = point[1] if point is not None else None
        self._gps_end_status = end_status
        self.active = False
        self._duration_s = self._elapsed_seconds(self.start_time, self.end_time)
        elapsed_s = round(self._duration_s, 1)
        self._append_log(
            now, "END", self.end_lat, self.end_lon,
            round(self.total_distance_km, 4), elapsed_s, "COMPLETED",
        )
        self._append_detail({
            "record_type": "TRIP_SUMMARY",
            "trip_id": self.trip_id,
            "timestamp": now,
            "start_timestamp": self.start_time,
            "start_latitude": self.start_lat,
            "start_longitude": self.start_lon,
            "end_timestamp": self.end_time,
            "end_latitude": self.end_lat,
            "end_longitude": self.end_lon,
            "duration_s": round(self._duration_s, 1),
            "duration_min": round(self._duration_s / 60.0, 2),
            "total_distance_km": round(self.total_distance_km, 6),
            "track_points": len(self.track_points),
            "gps_start_status": self._gps_start_status,
            "gps_end_status": self._gps_end_status,
        })
        return self.snapshot()

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

    @staticmethod
    def _haversine_m(point_a, point_b):
        return TripTracker._haversine_km(point_a, point_b) * 1000.0

    def snapshot(self, now=None):
        elapsed_s = self._duration_s
        if self.start_time and self.active:
            current_time = now or datetime.now().astimezone().isoformat(timespec="seconds")
            elapsed_s = self._elapsed_seconds(self.start_time, current_time)
        return {
            "active": self.active,
            "status": "ACTIVE" if self.active else ("COMPLETED" if self.end_time else "WAITING_FIX"),
            "trip_id": self.trip_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "start_lat": self.start_lat,
            "start_lon": self.start_lon,
            "end_lat": self.end_lat,
            "end_lon": self.end_lon,
            "gps_start_status": self._gps_start_status,
            "gps_end_status": self._gps_end_status,
            "total_distance_km": round(self.total_distance_km, 6),
            "duration_s": round(elapsed_s, 1),
            "duration_min": round(elapsed_s / 60.0, 2),
            "elapsed_s": round(elapsed_s, 1),
            "track_points": len(self.track_points),
        }

    def summary_text(self):
        summary = self.snapshot()
        start_gps = (f"{self.start_lat:.6f}, {self.start_lon:.6f}"
                     if self.start_lat is not None and self.start_lon is not None else "NO_FIX")
        end_gps = (f"{self.end_lat:.6f}, {self.end_lon:.6f}"
                   if self.end_lat is not None and self.end_lon is not None else "NO_FIX")
        duration = int(summary["duration_s"])
        hours, remainder = divmod(duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        return (
            "=== TRIP SUMMARY ===\n"
            f"Trip ID : {self.trip_id}\n"
            f"Start Time : {self.start_time}\n"
            f"Start GPS : {start_gps}\n"
            f"End Time : {self.end_time}\n"
            f"End GPS : {end_gps}\n"
            f"Duration : {hours:02d}:{minutes:02d}:{seconds:02d}\n"
            f"Total Distance: {summary['total_distance_km']:.4f} km\n"
            f"Track Points : {summary['track_points']}\n"
            f"GPS Status : {self._gps_start_status} -> {self._gps_end_status}\n"
            "===================="
        )


class SafetyEventEngine:
    SAFETY_EVENT_FIELDS = [
        "timestamp", "event_id", "trip_id", "event_type", "event_action",
        "timestamp_start", "timestamp_end", "duration_s",
        "latitude", "longitude", "end_latitude", "end_longitude",
        "gps_status", "vibration_g", "vibration_threshold_g",
        "tilt_deg", "tilt_threshold_deg", "tilt_x_deg", "tilt_y_deg",
        "tilt_reference_valid", "sw420_detected", "machine_state", "message",
        "trigger_reason",
    ]
    STATIONARY_EVENT_FIELDS = [
        "timestamp", "event_id", "event_type", "event_action", "duration_s",
        "latitude", "longitude", "gps_status", "vibration_rms", "vibration_peak",
        "sw420_event_count", "machine_state", "severity", "reason",
    ]
    TERRAIN_EVENT_FIELDS = [
        "timestamp", "event_id", "event_type", "event_action", "duration_s",
        "latitude", "longitude", "gps_status", "tilt_x", "tilt_y", "vibration_rms",
        "vibration_peak", "sw420_event_count", "machine_state", "severity",
        "trigger_reason",
    ]

    def __init__(self, base_dir=".", config=None, clock=None):
        self.base_dir = base_dir
        self.config = load_runtime_config()
        if config:
            self.config.update(config)
        self._clock = clock or time.monotonic
        self._idle_geofence = self.config.get("IDLE_GEOFENCE", {}) or {}
        self.trip = TripTracker(
            base_dir=base_dir,
            min_distance_m=self.config["IDLE_DISTANCE_THRESHOLD_M"],
        )
        self._gps_last_valid = None
        self._idle_state = "NORMAL"
        self._idle_started_monotonic = None
        self._idle_started_at = None
        self._idle_reference_point = None
        self._idle_event = None
        self._idle_last_event = None
        self._idle_last_log_monotonic = None
        self._idle_geofence_inside = False
        self._idle_geofence_position_valid = False
        self._total_idle_duration_s = 0.0
        self._idle_session_count = 0
        self._landslide_latched = False
        self._landslide_event = None
        self._landslide_started_monotonic = None
        self._ensure_logs()

    def _ensure_logs(self):
        os.makedirs(self.base_dir, exist_ok=True)
        for name in [
            "log_stationary_vibration.csv",
            "log_terrain_stability.csv",
            "log_blindspot.csv",
            "log_sensor_tambahan.csv",
            "log_safety_events.csv",
        ]:
            path = os.path.join(self.base_dir, name)
            if os.path.exists(path):
                if name == "log_safety_events.csv":
                    self._ensure_safety_event_schema(path)
                elif name == "log_stationary_vibration.csv":
                    self._ensure_event_log_schema(path, self.STATIONARY_EVENT_FIELDS)
                elif name == "log_terrain_stability.csv":
                    self._ensure_event_log_schema(path, self.TERRAIN_EVENT_FIELDS)
                continue
            with open(path, "w", newline="") as handle:
                writer = csv.writer(handle)
                if name == "log_stationary_vibration.csv":
                    writer.writerow(self.STATIONARY_EVENT_FIELDS)
                elif name == "log_terrain_stability.csv":
                    writer.writerow(self.TERRAIN_EVENT_FIELDS)
                elif name == "log_blindspot.csv":
                    writer.writerow([
                        "timestamp", "event_id", "event_type", "severity", "person_count",
                        "nearest_distance_m", "duration_s", "status"
                    ])
                elif name == "log_safety_events.csv":
                    writer.writerow(self.SAFETY_EVENT_FIELDS)
                else:
                    writer.writerow([
                        "timestamp", "event_id", "event_type", "severity", "status"
                    ])

    def _ensure_safety_event_schema(self, path):
        temporary_path = None
        try:
            with open(path, newline="") as source:
                reader = csv.DictReader(source)
                existing_fields = reader.fieldnames or []
                if existing_fields == self.SAFETY_EVENT_FIELDS:
                    return
                fields = list(self.SAFETY_EVENT_FIELDS)
                fields.extend(field for field in existing_fields if field not in fields)
                with tempfile.NamedTemporaryFile(
                        "w", newline="", dir=self.base_dir, delete=False) as target:
                    temporary_path = target.name
                    writer = csv.DictWriter(target, fieldnames=fields)
                    writer.writeheader()
                    for row in reader:
                        writer.writerow(row)
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def _ensure_event_log_schema(self, path, required_fields):
        temporary_path = None
        try:
            with open(path, newline="") as source:
                reader = csv.DictReader(source)
                existing_fields = reader.fieldnames or []
                if existing_fields == required_fields:
                    return
                fields = list(required_fields)
                fields.extend(field for field in existing_fields if field not in fields)
                with tempfile.NamedTemporaryFile(
                        "w", newline="", dir=self.base_dir, delete=False) as target:
                    temporary_path = target.name
                    writer = csv.DictWriter(target, fieldnames=fields)
                    writer.writeheader()
                    for row in reader:
                        writer.writerow(row)
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None and os.path.exists(temporary_path):
                os.unlink(temporary_path)

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

    def _update_idle_geofence(self, point):
        if point is None:
            self._idle_geofence_position_valid = False
            return self._idle_geofence_inside
        self._idle_geofence_position_valid = True
        if not self._idle_geofence.get("enabled", False):
            self._idle_geofence_inside = False
            return False
        self._idle_geofence_inside = is_point_inside_idle_geofence(
            point[0], point[1], self._idle_geofence.get("points", [])
        )
        return self._idle_geofence_inside

    def _idle_geofence_snapshot(self):
        return {
            "enabled": bool(self._idle_geofence.get("enabled", False)),
            "inside": bool(self._idle_geofence_inside) if self._idle_geofence_position_valid else False,
            "last_valid_inside": bool(self._idle_geofence_inside),
            "position_valid": bool(self._idle_geofence_position_valid),
            "name": self._idle_geofence.get("name", ""),
            "bypass_idle": bool(self._idle_geofence.get("bypass_idle", False)),
            "points": list(self._idle_geofence.get("points", [])),
        }

    def _write_csv(self, path_name, row):
        path = os.path.join(self.base_dir, path_name)
        with open(path, "a", newline="") as handle:
            csv.writer(handle).writerow(row)

    def _write_specialized_event(self, event, action, timestamp,
                                 end_point=None, gps_status=None,
                                 duration_s=None):
        location = end_point
        if location is None and event.get("latitude") is not None and event.get("longitude") is not None:
            location = (event["latitude"], event["longitude"])
        location_status = gps_status or event.get("gps_status")
        duration = round(
            duration_s if duration_s is not None else event.get("duration_s", 0.0),
            1,
        )
        common = {
            "timestamp": timestamp,
            "event_id": event.get("event_id"),
            "event_type": event.get("event_type"),
            "event_action": action,
            "duration_s": duration,
            "latitude": location[0] if location is not None else None,
            "longitude": location[1] if location is not None else None,
            "gps_status": location_status,
            "vibration_rms": event.get("vibration_g"),
            "vibration_peak": event.get("vibration_peak_g"),
            "sw420_event_count": event.get("sw420_event_count"),
            "machine_state": event.get("machine_state"),
        }
        if event.get("event_type") == "IDLE":
            common.update({
                "severity": event.get("severity"),
                "reason": event.get("message"),
            })
            fields = self.STATIONARY_EVENT_FIELDS
            filename = "log_stationary_vibration.csv"
        elif event.get("event_type") == "POTENSI_LONGSOR":
            common.update({
                "gps_status": location_status,
                "tilt_x": event.get("tilt_x_deg"),
                "tilt_y": event.get("tilt_y_deg"),
                "severity": event.get("severity", "POTENSI LONGSOR"),
                "trigger_reason": event.get("trigger_reason"),
            })
            fields = self.TERRAIN_EVENT_FIELDS
            filename = "log_terrain_stability.csv"
        else:
            return
        self._write_csv(filename, [common.get(field) for field in fields])

    @staticmethod
    def _valid_gps_point(fix, latitude, longitude):
        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError):
            return None
        if (not fix or not math.isfinite(latitude) or not math.isfinite(longitude) or
                not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0):
            return None
        return latitude, longitude

    def _write_safety_event(self, event, action, timestamp, end_point=None,
                            gps_status=None, duration_s=None):
        self._write_csv("log_safety_events.csv", [
            timestamp,
            event["event_id"],
            event.get("trip_id"),
            event["event_type"],
            action,
            event.get("timestamp_start"),
            event.get("timestamp_end"),
            round(duration_s if duration_s is not None else event.get("duration_s", 0.0), 1),
            event.get("latitude"),
            event.get("longitude"),
            end_point[0] if end_point is not None else None,
            end_point[1] if end_point is not None else None,
            gps_status or event.get("gps_status"),
            event.get("vibration_g"),
            event.get("vibration_threshold_g"),
            event.get("tilt_deg"),
            event.get("tilt_threshold_deg"),
            event.get("tilt_x_deg"),
            event.get("tilt_y_deg"),
            event.get("tilt_reference_valid"),
            event.get("sw420_detected"),
            event.get("machine_state"),
            event.get("message"),
            event.get("trigger_reason"),
        ])
        self._write_specialized_event(
            event, action, timestamp, end_point=end_point,
            gps_status=gps_status, duration_s=duration_s,
        )

    def _reset_idle_candidate(self):
        self._idle_state = "NORMAL"
        self._idle_started_monotonic = None
        self._idle_started_at = None
        self._idle_reference_point = None
        self._idle_event = None
        self._idle_last_log_monotonic = None

    def _close_idle_session(self, now_monotonic, timestamp, end_point):
        if self._idle_state == "IDLE_ACTIVE" and self._idle_event is not None:
            duration_s = max(0.0, now_monotonic - self._idle_started_monotonic)
            last_valid_point = end_point or self._gps_last_valid
            end_gps_status = "GPS_VALID" if end_point is not None else (
                "LAST_VALID_POINT" if last_valid_point is not None else "NO_FIX"
            )
            self._idle_event.update({
                "active": False,
                "timestamp_end": timestamp,
                "duration_s": round(duration_s, 1),
                "end_latitude": last_valid_point[0] if last_valid_point is not None else None,
                "end_longitude": last_valid_point[1] if last_valid_point is not None else None,
                "gps_status": end_gps_status,
            })
            self._write_safety_event(
                self._idle_event, "END", timestamp, end_point=last_valid_point,
                gps_status=end_gps_status, duration_s=duration_s,
            )
            self._idle_last_event = dict(self._idle_event)
            self._total_idle_duration_s += duration_s
        self._reset_idle_candidate()

    def _update_idle(self, now_monotonic, timestamp, point, sw420_active,
                     vibration_g, vibration_peak, machine_state, trip_id,
                     idle_detection_enabled=True):
        new_idle_event = False
        if not idle_detection_enabled:
            self._close_idle_session(now_monotonic, timestamp, point)
            return False
        machine_state = str(machine_state).upper()
        machine_on = machine_state == "ON" or sw420_active
        machine_off = machine_state in {"MATI", "OFF", "STOP"}
        if self._idle_state == "NORMAL":
            if machine_on:
                self._idle_state = "IDLE_CANDIDATE"
                self._idle_started_monotonic = now_monotonic
                self._idle_started_at = timestamp
                self._idle_reference_point = point
            else:
                return False

        if machine_off:
            self._close_idle_session(now_monotonic, timestamp, point)
            return False

        if point is not None and self._idle_reference_point is None:
            self._idle_reference_point = point
        if (point is not None and self._idle_reference_point is not None and
                self._haversine_m(self._idle_reference_point, point) >
                self.config["IDLE_DISTANCE_THRESHOLD_M"]):
            self._close_idle_session(now_monotonic, timestamp, point)
            return False

        duration_s = max(0.0, now_monotonic - self._idle_started_monotonic)
        event_point = point or self._idle_reference_point or self._gps_last_valid
        event_gps_status = "GPS_VALID" if point is not None else (
            "LAST_VALID_POINT" if event_point is not None else "NO_FIX"
        )
        if self._idle_state == "IDLE_CANDIDATE" and duration_s >= self.config["IDLE_DURATION_THRESHOLD_S"]:
            self._idle_state = "IDLE_ACTIVE"
            self._idle_event = {
                "event_id": self._event_id("idle"),
                "trip_id": trip_id,
                "event_type": "IDLE",
                "active": True,
                "timestamp_start": self._idle_started_at,
                "timestamp_detected": timestamp,
                "duration_s": round(duration_s, 1),
                "latitude": event_point[0] if event_point is not None else None,
                "longitude": event_point[1] if event_point is not None else None,
                "gps_status": event_gps_status,
                "vibration_g": round(float(vibration_g), 4),
                "vibration_peak_g": round(float(vibration_peak), 4),
                "sw420_detected": bool(sw420_active),
                "sw420_event_count": int(sw420_active),
                "machine_state": machine_state,
                "message": "SEGERA MATIKAN MESIN AGAR BAHAN BAKAR LEBIH HEMAT",
            }
            self._idle_last_log_monotonic = now_monotonic
            self._write_safety_event(self._idle_event, "START", timestamp, duration_s=duration_s)
            self._idle_last_event = dict(self._idle_event)
            self._idle_session_count += 1
            new_idle_event = True
        elif self._idle_state == "IDLE_ACTIVE":
            if event_point is not None:
                self._idle_event["latitude"] = event_point[0]
                self._idle_event["longitude"] = event_point[1]
            self._idle_event["gps_status"] = event_gps_status
            self._idle_event["duration_s"] = round(duration_s, 1)
            self._idle_event["vibration_g"] = round(float(vibration_g), 4)
            self._idle_event["vibration_peak_g"] = round(float(vibration_peak), 4)
            self._idle_event["machine_state"] = machine_state
            self._idle_last_event = dict(self._idle_event)
            if (now_monotonic - self._idle_last_log_monotonic >=
                    self.config["IDLE_LOG_UPDATE_INTERVAL_S"]):
                self._write_safety_event(self._idle_event, "UPDATE", timestamp, duration_s=duration_s)
                self._idle_last_log_monotonic = now_monotonic
        return new_idle_event

    def _update_landslide(self, now_monotonic, timestamp, point, vibration_g,
                          vibration_peak, tilt_x, tilt_y,
                          tilt_valid, sw420_active, machine_state, trip_id):
        vibration_threshold = float(self.config["HEAVY_VIBRATION_THRESHOLD"])
        tilt_threshold = float(self.config["TILT_THRESHOLD_DEG"])
        tilt_deg = max(abs(float(tilt_x)), abs(float(tilt_y)))
        heavy_vibration = float(vibration_g) > vibration_threshold
        excessive_tilt = bool(tilt_valid) and tilt_deg > tilt_threshold
        condition = heavy_vibration or excessive_tilt
        if heavy_vibration and excessive_tilt:
            trigger_reason = "GETARAN DAN KEMIRINGAN MELEBIHI THRESHOLD"
        elif heavy_vibration:
            trigger_reason = "GETARAN MELEBIHI THRESHOLD"
        elif excessive_tilt:
            trigger_reason = "KEMIRINGAN MELEBIHI THRESHOLD"
        else:
            trigger_reason = None
        new_event = False

        if condition and not self._landslide_latched:
            self._landslide_latched = True
            self._landslide_started_monotonic = now_monotonic
            self._landslide_event = {
                "event_id": self._event_id("landslide"),
                "trip_id": trip_id,
                "event_type": "POTENSI_LONGSOR",
                "active": True,
                "timestamp": timestamp,
                "latitude": point[0] if point is not None else None,
                "longitude": point[1] if point is not None else None,
                "gps_status": "GPS_VALID" if point is not None else "NO_FIX",
                "vibration_g": round(float(vibration_g), 4),
                "vibration_peak_g": round(float(vibration_peak), 4),
                "vibration_threshold_g": vibration_threshold,
                "tilt_deg": round(tilt_deg, 2),
                "tilt_threshold_deg": tilt_threshold,
                "tilt_x_deg": round(float(tilt_x), 2),
                "tilt_y_deg": round(float(tilt_y), 2),
                "tilt_reference_valid": bool(tilt_valid),
                "sw420_detected": bool(sw420_active),
                "sw420_event_count": int(sw420_active),
                "machine_state": machine_state,
                "message": "POTENSI LONGSOR TERDETEKSI",
                "trigger_reason": trigger_reason,
                "severity": "POTENSI LONGSOR",
            }
            self._write_safety_event(self._landslide_event, "DETECTED", timestamp)
            new_event = True
        elif not condition and self._landslide_latched:
            self._landslide_latched = False
            self._landslide_event["active"] = False
            self._landslide_event["timestamp_end"] = timestamp
            duration_s = max(0.0, now_monotonic - self._landslide_started_monotonic)
            self._landslide_event["duration_s"] = round(duration_s, 1)
            self._write_safety_event(self._landslide_event, "CLEARED", timestamp,
                                     duration_s=duration_s)
            self._landslide_started_monotonic = None

        return condition, new_event

    def update(self, gps_fix, gps_lat, gps_lon, gps_status, vibration_rms, vibration_peak, sw420_event_count, machine_state, tilt_x, tilt_y, timestamp=None, now_monotonic=None, tilt_valid=True, trip_id=None):
        now_monotonic = self._clock() if now_monotonic is None else float(now_monotonic)
        timestamp = timestamp or datetime.now().isoformat(timespec="seconds")
        point = self._valid_gps_point(gps_fix, gps_lat, gps_lon)
        if point is not None:
            self._gps_last_valid = point
        idle_geofence_last_inside = self._update_idle_geofence(point)
        idle_geofence_inside = idle_geofence_last_inside if point is not None else False
        idle_geofence_bypass = (
            idle_geofence_last_inside and
            bool(self._idle_geofence.get("enabled", False)) and
            bool(self._idle_geofence.get("bypass_idle", False))
        )

        vibration_g = float(vibration_rms or 0.0)
        tilt_x = float(tilt_x or 0.0)
        tilt_y = float(tilt_y or 0.0)
        sw420_active = bool(int(sw420_event_count or 0))
        current_trip_id = trip_id if trip_id is not None else (
            self.trip.trip_id if self.trip.active else None
        )

        landslide_condition, new_landslide_event = self._update_landslide(
            now_monotonic, timestamp, point, vibration_g, vibration_peak,
            tilt_x, tilt_y,
            tilt_valid, sw420_active, machine_state, current_trip_id,
        )
        new_idle_event = self._update_idle(
            now_monotonic, timestamp, point, sw420_active,
            vibration_g, vibration_peak, machine_state, current_trip_id,
            idle_detection_enabled=not idle_geofence_bypass,
        )

        idle_event = self._idle_event or self._idle_last_event
        landslide_event = self._landslide_event
        buzzer_pattern = "three" if new_landslide_event else (
            "double" if new_idle_event and not landslide_condition and not self._landslide_latched else None
        )
        stationary_event = None
        if self._idle_event is not None:
            stationary_event = {
                **self._idle_event,
                "reason": self._idle_event["message"],
            }
        terrain_event = None
        if self._landslide_latched and landslide_event is not None:
            terrain_event = {
                **landslide_event,
                "severity": "POTENSI LONGSOR",
            }

        current_idle_duration_s = (
            max(0.0, now_monotonic - self._idle_started_monotonic)
            if self._idle_started_monotonic is not None else 0.0
        )
        total_idle_duration_s = self._total_idle_duration_s
        if self._idle_state == "IDLE_ACTIVE":
            total_idle_duration_s += current_idle_duration_s

        return {
            "idle_state": self._idle_state,
            "idle_duration_s": round(current_idle_duration_s, 1),
            "total_idle_duration_s": round(total_idle_duration_s, 1),
            "idle_session_count": self._idle_session_count,
            "idle_geofence": self._idle_geofence_snapshot(),
            "idle_geofence_inside": idle_geofence_inside,
            "idle_geofence_name": self._idle_geofence.get("name", ""),
            "idle_detection_enabled": not idle_geofence_bypass,
            "thresholds": {
                "idle_duration_s": float(self.config["IDLE_DURATION_THRESHOLD_S"]),
                "idle_distance_m": float(self.config["IDLE_DISTANCE_THRESHOLD_M"]),
                "heavy_vibration_g": float(self.config["HEAVY_VIBRATION_THRESHOLD"]),
                "tilt_deg": float(self.config["TILT_THRESHOLD_DEG"]),
            },
            "idle_event": idle_event,
            "potential_landslide": landslide_event,
            "stationary_vibration": stationary_event,
            "terrain_stability": terrain_event,
            "new_idle_event": new_idle_event,
            "new_landslide_event": new_landslide_event,
            "buzzer_pattern": buzzer_pattern,
            "gps_status": "GPS_VALID" if point is not None else "GPS_NO_FIX",
            "last_valid_point": self._gps_last_valid,
            "trip": self.trip.snapshot(),
        }

    def start_trip(self, lat=None, lon=None, timestamp=None, gps_status="GPS_VALID"):
        return self.trip.start_trip(lat, lon, timestamp=timestamp, gps_status=gps_status)

    def end_trip(self, lat=None, lon=None, timestamp=None, gps_status=None):
        return self.trip.end_trip(lat, lon, timestamp=timestamp, gps_status=gps_status)

    def record_trip_point(self, lat, lon, timestamp=None, gps_status="GPS_VALID"):
        return self.trip.update_position(lat, lon, timestamp, gps_status=gps_status)


if __name__ == "__main__":
    engine = SafetyEventEngine(base_dir=".")
    for second in range(6):
        result = engine.update(
            1, -6.2, 106.8, "GPS FIX AKTIF", 0.1, 0.1, 1, "ON", 0.0, 0.0,
            now_monotonic=second,
        )
    print(result["idle_event"])
