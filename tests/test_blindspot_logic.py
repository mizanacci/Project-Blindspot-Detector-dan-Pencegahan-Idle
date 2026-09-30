import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'File pengembangan dari Claude AI'))

from fuzzy_engine import evaluate_urgency, StatusStabilizer
from tracker import SimpleTracker
from mpu6050_sensor import MPU6050Sensor
from gps_neo6m import GPSNeo6M
from safety_event_engine import is_point_inside_idle_geofence, load_runtime_config
import main


def test_distance_far_is_aman():
    score, label = evaluate_urgency(12.0, 1.0)
    assert label == "aman"
    assert score < 33


def test_distance_near_is_bahaya():
    score, label = evaluate_urgency(1.5, 1.0)
    assert label == "bahaya"
    assert score >= 66


def test_status_stabilizer_requires_multiple_confirmations():
    stabilizer = StatusStabilizer()
    assert stabilizer.update("bahaya") == "aman"
    assert stabilizer.update("bahaya") == "bahaya"
    assert stabilizer.update("aman") == "bahaya"
    assert stabilizer.update("aman") == "bahaya"
    assert stabilizer.update("aman") == "aman"


def test_tracker_keeps_same_person_id_across_close_boxes():
    tracker = SimpleTracker()
    first = tracker.update([
        {"x1": 10, "y1": 20, "x2": 30, "y2": 100},
        {"x1": 40, "y1": 25, "x2": 60, "y2": 120},
    ])
    second = tracker.update([
        {"x1": 12, "y1": 22, "x2": 32, "y2": 105},
    ])

    assert first[0]["id"] == 0
    assert len(first) == 2
    assert second[0]["id"] == 0
    assert second[0]["y2"] == 105


def test_mpu_calculates_pitch_and_roll_from_static_acceleration():
    sensor = MPU6050Sensor.__new__(MPU6050Sensor)

    tilt_x, tilt_y = sensor.calculate_tilt_deg(0.0, 0.0, 1.0)
    assert abs(tilt_x) < 1e-6
    assert abs(tilt_y) < 1e-6

    tilt_x, tilt_y = sensor.calculate_tilt_deg(0.0, 0.5, 0.8660254)
    assert abs(tilt_x - 30.0) < 1e-5
    assert abs(tilt_y) < 1e-6

    tilt_x, tilt_y = sensor.calculate_tilt_deg(0.5, 0.0, 0.8660254)
    assert abs(tilt_x) < 1e-6
    assert abs(tilt_y - 30.0) < 1e-5


def test_mpu_tilt_status_uses_threshold():
    sensor = MPU6050Sensor.__new__(MPU6050Sensor)

    assert sensor.get_tilt_status(5.0, 5.0, 12.0) == "NORMAL"
    assert sensor.get_tilt_status(15.0, 5.0, 12.0) == "MIRING"
    assert sensor.get_tilt_status(5.0, 18.0, 12.0) == "MIRING"


def test_mpu_vertical_mounting_becomes_zero_relative_tilt():
    sensor = MPU6050Sensor.__new__(MPU6050Sensor)
    sensor.reference_tilt_x_deg = 88.7
    sensor.reference_tilt_y_deg = 0.8

    relative_x, relative_y = sensor._relative_tilt(88.7, 0.8)

    assert abs(relative_x) < 1e-6
    assert abs(relative_y) < 1e-6
    assert sensor.get_tilt_status(relative_x, relative_y) == "NORMAL"


def test_mpu_calibration_averages_stable_samples():
    sensor = MPU6050Sensor.__new__(MPU6050Sensor)
    readings = iter([
        (0.0, 0.9997, 0.0227, 1.0),
        (0.0, 0.9997, 0.0227, 1.0),
        (0.0, 0.9997, 0.0227, 1.0),
    ])
    sensor._baca_magnitude_g = lambda: next(readings)

    reference = sensor.calibrate_reference(jumlah_sampel=3, interval_s=0)

    assert abs(reference["reference_tilt_x_deg"] - 88.7) < 0.2
    assert abs(reference["reference_tilt_y_deg"]) < 1e-6


def test_mpu_reference_persists_and_loads():
    with tempfile.TemporaryDirectory() as directory:
        calibration_file = os.path.join(directory, "mpu.json")
        first = MPU6050Sensor.__new__(MPU6050Sensor)
        first.calibration_file = calibration_file
        first.save_reference({
            "reference_tilt_x_deg": 88.7,
            "reference_tilt_y_deg": 0.8,
        })

        second = MPU6050Sensor.__new__(MPU6050Sensor)
        second.calibration_file = calibration_file
        second.load_reference()

        assert second.reference_available is True
        assert second.reference_tilt_x_deg == 88.7
        assert second.reference_tilt_y_deg == 0.8


def test_gps_valid_fix_at_zero_coordinates_is_accepted():
    msg = type("GGA", (), {"gps_qual": "1", "latitude": 0.0, "longitude": 0.0})()
    assert GPSNeo6M._ekstrak_fix(msg) == {"fix": 1, "lat": 0.0, "lon": 0.0}


def test_gps_accepts_valid_rmc_and_rejects_invalid_gga_quality():
    valid_rmc = type("RMC", (), {
        "status": "A", "latitude": -6.2, "longitude": 106.8,
    })()
    invalid_gga = type("GGA", (), {
        "gps_qual": "invalid", "latitude": 1.0, "longitude": 2.0,
    })()

    assert GPSNeo6M._ekstrak_fix(valid_rmc) == {
        "fix": 1, "lat": -6.2, "lon": 106.8,
    }
    assert GPSNeo6M._ekstrak_fix(invalid_gga) is None


def _nmea_sentence(body):
    checksum = 0
    for character in body:
        checksum ^= ord(character)
    return f"${body}*{checksum:02X}\r\n".encode("ascii")


class _FakeSerial:
    def __init__(self, lines):
        self.lines = iter(lines)

    def readline(self):
        return next(self.lines, b"")

    def close(self):
        pass


def test_gps_distinguishes_uart_no_data_from_nmea_without_fix():
    gps = GPSNeo6M.__new__(GPSNeo6M)
    gps.ser = _FakeSerial([_nmea_sentence(
        "GPGGA,123519,4807.038,N,01131.000,E,0,02,1.0,545.4,M,46.9,M,,"
    )])
    gps.nmea_received = False
    gps.nmea_sentence_count = 0
    gps.gga_received = False
    gps.rmc_received = False
    gps.satellites = None
    gps.last_sentence_time = None
    gps.last_error = None

    result = gps.baca_lokasi(maks_baris=1)

    assert result["fix"] == 0
    assert result["status"] == "GPS UART OK - MENUNGGU FIX"
    assert result["nmea_received"] is True
    assert result["gga_received"] is True
    assert result["satellites"] == 2


def test_gps_reports_fix_and_satellites_from_valid_gga():
    gps = GPSNeo6M.__new__(GPSNeo6M)
    gps.ser = _FakeSerial([_nmea_sentence(
        "GPGGA,123519,4807.038,N,01131.000,E,1,09,1.0,545.4,M,46.9,M,,"
    )])
    gps.nmea_received = False
    gps.nmea_sentence_count = 0
    gps.gga_received = False
    gps.rmc_received = False
    gps.satellites = None
    gps.last_sentence_time = None
    gps.last_error = None

    result = gps.baca_lokasi(maks_baris=1)

    assert result["fix"] == 1
    assert result["status"] == "GPS FIX AKTIF"
    assert result["satellites"] == 9
    assert result["lat"] > 0
    assert result["lon"] > 0


def test_prototype_trip_starts_without_gps_and_survives_gps_loss_until_shutdown():
    import csv

    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(base_dir=directory)
        started = main.start_operation_trip(engine, "2026-09-29T08:00:00")
        trip_id = started["trip_id"]
        assert started["active"] is True
        assert started["gps_start_status"] == "NO_FIX"
        assert started["start_lat"] is None
        assert started["start_lon"] is None

        for second in (1, 2):
            state = main.update_trip_tracking(
                engine, {"fix": 0, "lat": 0.0, "lon": 0.0},
                timestamp=f"2026-09-29T08:00:0{second}",
            )
            assert state["trip_active"] is True
            assert state["trip_id"] == trip_id
            assert state["distance_km"] == 0.0

        point_a = main.update_trip_tracking(
            engine, {"fix": 1, "lat": -1.0, "lon": 116.0},
            timestamp="2026-09-29T08:00:03",
        )
        assert point_a["trip_id"] == trip_id
        assert point_a["trip"]["start_lat"] == -1.0
        assert point_a["trip"]["start_lon"] == 116.0
        distance_before_gap = point_a["distance_km"]

        for second in (4, 5):
            gap = main.update_trip_tracking(
                engine, {"fix": 0, "lat": 0.0, "lon": 0.0},
                timestamp=f"2026-09-29T08:00:0{second}",
            )
            assert gap["trip_active"] is True
            assert gap["trip_id"] == trip_id
            assert gap["distance_km"] == distance_before_gap

        point_b = main.update_trip_tracking(
            engine, {"fix": 1, "lat": -1.0, "lon": 116.0001},
            timestamp="2026-09-29T08:00:06",
        )
        assert point_b["trip_id"] == trip_id
        assert point_b["distance_km"] > distance_before_gap

        ended = main.stop_operation_trip(
            engine,
            {"fix": 0, "lat": 0.0, "lon": 0.0},
            timestamp="2026-09-29T08:00:07",
        )
        assert ended["active"] is False
        assert ended["end_lat"] == -1.0
        assert ended["end_lon"] == 116.0001
        assert ended["gps_end_status"] == "LAST_VALID_POINT"
        assert ended["total_distance_km"] == point_b["distance_km"]

        main.stop_operation_trip(
            engine, {"fix": 0, "lat": 0.0, "lon": 0.0},
            timestamp="2026-09-29T08:00:08",
        )
        with open(os.path.join(directory, "log_trip_details.csv"), newline="") as handle:
            summaries = [
                row for row in csv.DictReader(handle)
                if row["record_type"] == "TRIP_SUMMARY"
            ]
        assert len(summaries) == 1
        assert summaries[0]["trip_id"] == trip_id
        assert summaries[0]["end_latitude"] == "-1.0"
        assert summaries[0]["end_longitude"] == "116.0001"


def test_two_prototype_cycles_keep_separate_ids_and_one_summary_each():
    import csv

    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(base_dir=directory)
        cycle_trip_ids = []
        for cycle, first_lon, last_lon in ((1, 116.0, 116.0001), (2, 117.0, 117.0001)):
            started = main.start_operation_trip(
                engine, f"2026-09-29T0{cycle}:00:00",
            )
            cycle_trip_ids.append(started["trip_id"])
            main.update_trip_tracking(
                engine,
                {"fix": 1, "lat": -1.0, "lon": first_lon},
                timestamp=f"2026-09-29T0{cycle}:00:01",
            )
            main.update_trip_tracking(
                engine,
                {"fix": 1, "lat": -1.0, "lon": last_lon},
                timestamp=f"2026-09-29T0{cycle}:00:02",
            )
            ended = main.stop_operation_trip(
                engine,
                {"fix": 1, "lat": -1.0, "lon": last_lon},
                timestamp=f"2026-09-29T0{cycle}:00:03",
            )
            assert ended["active"] is False
            assert ended["gps_end_status"] == "GPS_VALID"
            assert ended["end_lon"] == last_lon

        assert cycle_trip_ids[0] != cycle_trip_ids[1]
        with open(os.path.join(directory, "log_trip_details.csv"), newline="") as handle:
            summaries = [
                row for row in csv.DictReader(handle)
                if row["record_type"] == "TRIP_SUMMARY"
            ]
        assert len(summaries) == 2
        assert {row["trip_id"] for row in summaries} == set(cycle_trip_ids)


def test_trip_tracker_persists_start_movement_end_and_summary():
    import csv

    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(base_dir=directory)
        trip = engine.trip
        started = trip.start_trip(
            0.0, 0.0, timestamp="2026-09-29T08:00:00", gps_status="GPS_VALID",
        )
        assert started["active"] is True
        assert started["start_time"] == "2026-09-29T08:00:00"
        assert started["start_lat"] == 0.0
        assert started["start_lon"] == 0.0
        assert started["total_distance_km"] == 0.0
        assert started["track_points"] == 1

        assert trip.update_position(0.0, 0.0001, "2026-09-29T08:00:10") is True
        assert trip.update_position(0.0001, 0.0001, "2026-09-29T08:00:20") is True
        expected_km = (
            trip._haversine_km((0.0, 0.0), (0.0, 0.0001)) +
            trip._haversine_km((0.0, 0.0001), (0.0001, 0.0001))
        )
        assert trip.total_distance_km == pytest.approx(expected_km)

        ended = trip.end_trip(
            0.0001, 0.0002, timestamp="2026-09-29T08:02:00", gps_status="GPS_VALID",
        )
        expected_with_end = expected_km + trip._haversine_km(
            (0.0001, 0.0001), (0.0001, 0.0002)
        )
        assert ended["active"] is False
        assert ended["end_time"] == "2026-09-29T08:02:00"
        assert ended["end_lat"] == 0.0001
        assert ended["end_lon"] == 0.0002
        assert ended["duration_s"] == 120.0
        assert ended["duration_min"] == 2.0
        assert ended["total_distance_km"] == pytest.approx(expected_with_end, abs=1e-6)
        assert ended["track_points"] == 4
        summary = trip.summary_text()
        assert "TRIP SUMMARY" in summary
        assert "Total Distance:" in summary
        assert "GPS Status : GPS_VALID -> GPS_VALID" in summary

        with open(os.path.join(directory, "log_trip_details.csv"), newline="") as handle:
            rows = list(csv.DictReader(handle))
        points = [row for row in rows if row["record_type"] == "TRACK_POINT"]
        summaries = [row for row in rows if row["record_type"] == "TRIP_SUMMARY"]
        assert len(points) == 4
        assert points[0]["distance_from_previous_m"] == "0.0"
        assert len(summaries) == 1
        assert summaries[0]["gps_start_status"] == "GPS_VALID"
        assert summaries[0]["gps_end_status"] == "GPS_VALID"


def test_trip_tracker_ignores_gps_jitter_but_accumulates_from_last_accepted_point():
    with tempfile.TemporaryDirectory() as directory:
        trip = main.SafetyEventEngine(base_dir=directory).trip
        trip.start_trip(0.0, 0.0, timestamp="2026-09-29T08:00:00")

        assert trip.update_position(0.0, 0.000005, "2026-09-29T08:00:05") is False
        assert trip.total_distance_km == 0.0
        assert trip.snapshot()["track_points"] == 1

        assert trip.update_position(0.0, 0.000025, "2026-09-29T08:00:10") is True
        expected_m = trip._haversine_m((0.0, 0.0), (0.0, 0.000025))
        assert trip.total_distance_km == pytest.approx(expected_m / 1000.0)
        assert trip.snapshot()["track_points"] == 2


def test_trip_tracker_closes_without_fix_and_multiple_trips_do_not_mix():
    with tempfile.TemporaryDirectory() as directory:
        trip = main.SafetyEventEngine(base_dir=directory).trip
        first = trip.start_trip(-1.0, 116.0, timestamp="2026-09-29T08:00:00")
        trip.update_position(-1.0, 116.0001, "2026-09-29T08:00:10")
        first_distance = trip.total_distance_km
        first_id = first["trip_id"]

        ended = trip.end_trip(timestamp="2026-09-29T08:00:20", gps_status="NO_FIX")
        assert ended["active"] is False
        assert ended["end_lat"] == -1.0
        assert ended["end_lon"] == 116.0001
        assert ended["gps_end_status"] == "LAST_VALID_POINT"
        assert ended["total_distance_km"] == pytest.approx(first_distance, abs=1e-6)

        second = trip.start_trip(-1.0, 116.0, timestamp="2026-09-29T09:00:00")
        assert second["trip_id"] != first_id
        assert second["total_distance_km"] == 0.0
        trip.update_position(-1.0, 116.00005, "2026-09-29T09:00:10")
        second_distance = trip.total_distance_km
        trip.end_trip(timestamp="2026-09-29T09:00:20", gps_status="NO_FIX")
        assert trip.total_distance_km == pytest.approx(second_distance, abs=1e-6)
        assert first_distance != second_distance


def test_idle_and_landslide_events_are_linked_to_active_trip_id():
    import csv

    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(base_dir=directory)
        trip = engine.start_trip(-6.2, 106.8, timestamp="2026-09-29T08:00:00")
        trip_id = trip["trip_id"]

        for second in range(11):
            _update_safety_engine(engine, second, vibration=0.1)
        result = _update_safety_engine(engine, 11, vibration=0.31, tilt_x=20)
        assert result["idle_event"]["trip_id"] == trip_id
        assert result["potential_landslide"]["trip_id"] == trip_id

        with open(os.path.join(directory, "log_safety_events.csv"), newline="") as handle:
            rows = list(csv.DictReader(handle))
        linked = [row for row in rows if row["event_type"] in ("IDLE", "POTENSI_LONGSOR")]
        assert linked
        assert all(row["trip_id"] == trip_id for row in linked)


def test_safety_event_log_schema_adds_trip_id_without_losing_historical_rows():
    import csv

    old_fields = [
        "timestamp", "event_id", "event_type", "event_action", "timestamp_start",
        "timestamp_end", "duration_s", "latitude", "longitude", "end_latitude",
        "end_longitude", "gps_status", "vibration_g", "vibration_threshold_g",
        "tilt_deg", "tilt_threshold_deg", "tilt_x_deg", "tilt_y_deg",
        "tilt_reference_valid", "sw420_detected", "machine_state", "message",
        "future_column",
    ]
    with tempfile.TemporaryDirectory() as directory:
        with open(os.path.join(directory, "log_trip.csv"), "w") as handle:
            handle.write("timestamp,trip_id,event_type,latitude,longitude,distance_km,elapsed_s,status\n")
        path = os.path.join(directory, "log_safety_events.csv")
        with open(path, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=old_fields)
            writer.writeheader()
            writer.writerow({"event_id": "existing-1", "event_type": "IDLE", "future_column": "preserved"})

        main.SafetyEventEngine(base_dir=directory)

        assert os.path.exists(os.path.join(directory, "log_trip_details.csv"))
        with open(path, newline="") as handle:
            reader = csv.DictReader(handle)
            row = next(reader)
            fields = reader.fieldnames
        assert "trip_id" in fields
        assert "future_column" in fields
        assert row["event_id"] == "existing-1"
        assert row["trip_id"] == ""
        assert row["future_column"] == "preserved"


def test_startup_check_flags_critical_hardware_items():
    checks = main.run_startup_check(
        {"calibration_points": [{"y2": 10, "distance_m": 5.0}]},
        type("Camera", (), {"isOpened": lambda self: False})(),
        None,
        None,
        None,
    )
    critical = {item["label"]: item.get("critical", False) for item in checks}
    assert critical["Kalibrasi zona"] is True
    assert critical["Kamera /dev/video0"] is True
    assert any(item["label"] == "MPU6050 I2C" and item.get("critical") is False for item in checks)


def _update_safety_engine(engine, now, *, fix=1, lat=-6.2, lon=106.8,
                          vibration=0.1, sw420=True, tilt_x=0.0, tilt_y=0.0,
                          machine_state=None, tilt_valid=True):
    return engine.update(
        gps_fix=fix,
        gps_lat=lat,
        gps_lon=lon,
        gps_status="GPS FIX AKTIF" if fix else "GPS UART NO DATA",
        vibration_rms=vibration,
        vibration_peak=vibration,
        sw420_event_count=int(sw420),
        machine_state=machine_state or ("ON" if sw420 else "MATI"),
        tilt_x=tilt_x,
        tilt_y=tilt_y,
        timestamp=f"2026-09-29T00:00:{int(now):02d}",
        now_monotonic=now,
        tilt_valid=tilt_valid,
    )


TEST_IDLE_GEOFENCE = {
    "enabled": True,
    "name": "Test Bongkar Muat",
    "bypass_idle": True,
    "points": [
        {"lat": -6.2001, "lon": 106.7999},
        {"lat": -6.2001, "lon": 106.8001},
        {"lat": -6.1999, "lon": 106.8001},
        {"lat": -6.1999, "lon": 106.7999},
    ],
}


def _geofence_engine(directory):
    return main.SafetyEventEngine(
        base_dir=directory,
        config={"IDLE_GEOFENCE": TEST_IDLE_GEOFENCE},
    )


def test_idle_geofence_point_in_polygon_handles_inside_outside_boundary_and_nofix():
    points = TEST_IDLE_GEOFENCE["points"]
    assert is_point_inside_idle_geofence(-6.2, 106.8, points)
    assert not is_point_inside_idle_geofence(-6.2, 106.801, points)
    assert is_point_inside_idle_geofence(-6.2001, 106.8, points)
    assert not is_point_inside_idle_geofence(None, 106.8, points)


def test_active_geofence_configuration_contains_new_balakpapan_center():
    config = load_runtime_config()
    geofence = config["IDLE_GEOFENCE"]
    center = (-1.2763828609586374, 116.86299109402113)
    assert geofence["name"] == "Area Bongkar Muat Balikpapan"
    assert len(geofence["points"]) == 5
    assert is_point_inside_idle_geofence(center[0], center[1], geofence["points"])
    assert not is_point_inside_idle_geofence(-1.28, 116.87, geofence["points"])


def test_idle_is_disabled_inside_geofence_without_creating_event():
    with tempfile.TemporaryDirectory() as directory:
        engine = _geofence_engine(directory)
        for second in range(12):
            result = _update_safety_engine(engine, second, lat=-6.2, lon=106.8)
        assert result["idle_geofence_inside"] is True
        assert result["idle_geofence_name"] == "Test Bongkar Muat"
        assert result["idle_detection_enabled"] is False
        assert result["idle_state"] == "NORMAL"
        assert result["new_idle_event"] is False
        assert result["idle_event"] is None


def test_entering_geofence_closes_active_idle_session():
    with tempfile.TemporaryDirectory() as directory:
        engine = _geofence_engine(directory)
        for second in range(11):
            result = _update_safety_engine(engine, second, lon=106.801)
        assert result["idle_state"] == "IDLE_ACTIVE"
        result = _update_safety_engine(engine, 12, lon=106.8)
        assert result["idle_geofence_inside"] is True
        assert result["idle_state"] == "NORMAL"
        assert result["idle_event"]["active"] is False
        assert result["idle_event"]["timestamp_end"] == "2026-09-29T00:00:12"


def test_idle_restarts_from_zero_after_exiting_geofence():
    with tempfile.TemporaryDirectory() as directory:
        engine = _geofence_engine(directory)
        result = _update_safety_engine(engine, 0, lat=-6.2, lon=106.8)
        assert result["idle_state"] == "NORMAL"
        result = _update_safety_engine(engine, 1, lon=106.801)
        assert result["idle_geofence_inside"] is False
        assert result["idle_state"] == "IDLE_CANDIDATE"
        result = _update_safety_engine(engine, 10, lon=106.801)
        assert result["new_idle_event"] is False
        result = _update_safety_engine(engine, 11, lon=106.801)
        assert result["new_idle_event"] is True
        assert result["idle_state"] == "IDLE_ACTIVE"


def test_geofence_nofix_does_not_claim_inside_or_force_exit():
    with tempfile.TemporaryDirectory() as directory:
        engine = _geofence_engine(directory)
        result = _update_safety_engine(engine, 0, fix=0, lat=None, lon=None)
        assert result["idle_geofence_inside"] is False
        assert result["idle_geofence"]["position_valid"] is False
        assert result["idle_detection_enabled"] is True
        result = _update_safety_engine(engine, 1, lon=106.8)
        assert result["idle_geofence_inside"] is True
        result = _update_safety_engine(engine, 2, fix=0, lat=None, lon=None)
        assert result["idle_geofence_inside"] is False
        assert result["idle_geofence"]["last_valid_inside"] is True
        assert result["idle_geofence"]["position_valid"] is False
        assert result["idle_state"] == "NORMAL"


def test_crossing_geofence_does_not_create_idle_event():
    with tempfile.TemporaryDirectory() as directory:
        engine = _geofence_engine(directory)
        result = _update_safety_engine(engine, 0, lon=106.801)
        assert result["idle_state"] == "IDLE_CANDIDATE"
        result = _update_safety_engine(engine, 1, lon=106.8)
        assert result["idle_geofence_inside"] is True
        assert result["idle_state"] == "NORMAL"
        assert result["new_idle_event"] is False


def test_idle_candidate_survives_gps_no_fix_before_threshold():
    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(base_dir=directory)

        result = _update_safety_engine(engine, 0, sw420=False)
        assert result["idle_state"] == "NORMAL"
        result = _update_safety_engine(engine, 1, fix=0)
        assert result["idle_state"] == "IDLE_CANDIDATE"
        started = engine._idle_started_monotonic

        result = _update_safety_engine(engine, 2)
        assert result["idle_state"] == "IDLE_CANDIDATE"
        assert engine._idle_started_monotonic == started
        result = _update_safety_engine(engine, 3)
        assert result["new_idle_event"] is False
        result = _update_safety_engine(engine, 9)
        assert result["new_idle_event"] is False
        result = _update_safety_engine(engine, 11)
        assert result["new_idle_event"] is True
        assert result["idle_state"] == "IDLE_ACTIVE"
        assert result["buzzer_pattern"] == "double"
        assert result["idle_event"]["timestamp_start"] == "2026-09-29T00:00:01"


def test_active_idle_survives_gps_no_fix_and_fix_recovery():
    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(base_dir=directory)
        for second in range(11):
            result = _update_safety_engine(engine, second)
        assert result["idle_state"] == "IDLE_ACTIVE"
        started = engine._idle_started_monotonic

        result = _update_safety_engine(engine, 15, fix=0)
        assert result["idle_state"] == "IDLE_ACTIVE"
        assert result["idle_event"]["active"] is True
        assert result["idle_duration_s"] == 15.0
        assert engine._idle_started_monotonic == started
        assert result["new_idle_event"] is False
        assert result["buzzer_pattern"] is None

        result = _update_safety_engine(engine, 20, lat=-6.199995)
        assert result["idle_state"] == "IDLE_ACTIVE"
        assert result["idle_duration_s"] == 20.0
        assert result["new_idle_event"] is False
        assert result["idle_event"]["gps_status"] == "GPS_VALID"


def test_idle_uses_machine_state_even_without_sw420_signal():
    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(base_dir=directory)
        for second in range(11):
            result = _update_safety_engine(
                engine, second, sw420=False, machine_state="ON",
            )
        assert result["new_idle_event"] is True
        assert result["buzzer_pattern"] == "double"
        assert result["idle_event"]["machine_state"] == "ON"
        assert result["idle_event"]["sw420_detected"] is False


def test_idle_candidate_resets_on_movement_and_vibration_stop():
    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(base_dir=directory)
        _update_safety_engine(engine, 0)
        _update_safety_engine(engine, 4)
        result = _update_safety_engine(engine, 5, lat=-6.19996)
        assert result["idle_state"] == "NORMAL"
        assert result["new_idle_event"] is False

        _update_safety_engine(engine, 6)
        result = _update_safety_engine(engine, 7, sw420=False)
        assert result["idle_state"] == "NORMAL"
        assert result["new_idle_event"] is False


def test_idle_logs_start_updates_and_end_once_with_final_duration():
    import csv

    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(
            base_dir=directory,
            config={"IDLE_LOG_UPDATE_INTERVAL_S": 2.0},
        )
        for second in range(11):
            result = _update_safety_engine(engine, second)
        assert result["buzzer_pattern"] == "double"

        result = _update_safety_engine(engine, 12)
        assert result["buzzer_pattern"] is None
        result = _update_safety_engine(engine, 14)
        assert result["buzzer_pattern"] is None
        result = _update_safety_engine(engine, 15, sw420=False)
        assert result["idle_state"] == "NORMAL"
        assert result["idle_event"]["active"] is False
        assert result["idle_event"]["duration_s"] == 15.0

        with open(os.path.join(directory, "log_safety_events.csv"), newline="") as handle:
            rows = list(csv.DictReader(handle))
        idle_rows = [row for row in rows if row["event_type"] == "IDLE"]
        assert [row["event_action"] for row in idle_rows] == ["START", "UPDATE", "UPDATE", "END"]
        assert idle_rows[-1]["duration_s"] == "15.0"
        assert idle_rows[-1]["timestamp_end"] == "2026-09-29T00:00:15"
        assert idle_rows[-1]["gps_status"] == "GPS_VALID"


def test_active_idle_closes_on_machine_off_after_gps_no_fix():
    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(base_dir=directory)
        for second in range(11):
            result = _update_safety_engine(engine, second)
        assert result["idle_state"] == "IDLE_ACTIVE"

        result = _update_safety_engine(engine, 15, fix=0)
        assert result["idle_state"] == "IDLE_ACTIVE"
        result = _update_safety_engine(engine, 20, fix=0, sw420=False, machine_state="MATI")
        assert result["idle_state"] == "NORMAL"
        assert result["idle_event"]["active"] is False
        assert result["idle_event"]["end_latitude"] == -6.2
        assert result["idle_event"]["end_longitude"] == 106.8
        assert result["idle_event"]["gps_status"] == "LAST_VALID_POINT"
        assert result["idle_event"]["duration_s"] == 20.0


def test_active_idle_ends_when_gps_returns_outside_reference_radius():
    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(base_dir=directory)
        for second in range(11):
            _update_safety_engine(engine, second)

        result = _update_safety_engine(engine, 15, fix=0)
        assert result["idle_state"] == "IDLE_ACTIVE"
        result = _update_safety_engine(engine, 16, lat=-6.1998)
        assert result["idle_state"] == "NORMAL"
        assert result["idle_event"]["active"] is False
        assert result["idle_event"]["timestamp_end"] == "2026-09-29T00:00:16"
        assert result["idle_event"]["duration_s"] == 16.0
        assert result["idle_event"]["gps_status"] == "GPS_VALID"


def test_idle_can_start_without_gps_and_uses_first_fix_as_reference():
    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(base_dir=directory)
        result = _update_safety_engine(engine, 0, fix=0)
        assert result["idle_state"] == "IDLE_CANDIDATE"
        assert result["idle_event"] is None
        for second in range(1, 10):
            result = _update_safety_engine(engine, second, fix=0)
        assert result["new_idle_event"] is False
        result = _update_safety_engine(engine, 10, lat=-6.2, lon=106.8)
        assert result["new_idle_event"] is True
        assert result["idle_event"]["latitude"] == -6.2
        assert result["idle_event"]["longitude"] == 106.8


def test_idle_no_fix_never_logs_zero_coordinates():
    import csv

    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(base_dir=directory)
        for second in range(11):
            result = _update_safety_engine(engine, second, fix=0)
        assert result["idle_event"]["latitude"] is None
        assert result["idle_event"]["longitude"] is None
        assert result["idle_event"]["gps_status"] == "NO_FIX"

        with open(os.path.join(directory, "log_safety_events.csv"), newline="") as handle:
            row = next(csv.DictReader(handle))
        assert row["latitude"] == ""
        assert row["longitude"] == ""
        assert row["gps_status"] == "NO_FIX"


def test_total_idle_duration_accumulates_completed_and_active_sessions():
    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(base_dir=directory)
        for second in range(11):
            result = _update_safety_engine(engine, second)
        assert result["idle_session_count"] == 1
        assert result["total_idle_duration_s"] == 10.0

        result = _update_safety_engine(engine, 12, sw420=False)
        assert result["idle_state"] == "NORMAL"
        assert result["total_idle_duration_s"] == 12.0

        for second in range(13, 25):
            result = _update_safety_engine(engine, second)
        assert result["idle_session_count"] == 2
        assert result["idle_duration_s"] == 11.0
        assert result["total_idle_duration_s"] == 23.0


def test_specialized_logs_share_master_event_ids_and_lifecycle_actions():
    import csv

    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(
            base_dir=directory,
            config={"IDLE_LOG_UPDATE_INTERVAL_S": 3.0},
        )
        for second in range(11):
            _update_safety_engine(engine, second, vibration=0.1)
        _update_safety_engine(engine, 12, vibration=0.31, tilt_x=20)
        _update_safety_engine(engine, 14, vibration=0.1, tilt_x=0)
        _update_safety_engine(engine, 15, vibration=0.1, tilt_x=0, sw420=False)

        def read_rows(filename):
            with open(os.path.join(directory, filename), newline="") as handle:
                return list(csv.DictReader(handle))

        master = read_rows("log_safety_events.csv")
        idle = read_rows("log_stationary_vibration.csv")
        terrain = read_rows("log_terrain_stability.csv")
        master_idle = [row for row in master if row["event_type"] == "IDLE"]
        master_terrain = [row for row in master if row["event_type"] == "POTENSI_LONGSOR"]

        assert [row["event_action"] for row in idle] == ["START", "UPDATE", "END"]
        assert {row["event_id"] for row in idle} == {row["event_id"] for row in master_idle}
        assert [row["event_action"] for row in terrain] == ["DETECTED", "CLEARED"]
        assert {row["event_id"] for row in terrain} == {row["event_id"] for row in master_terrain}
        assert terrain[0]["trigger_reason"] == "GETARAN DAN KEMIRINGAN MELEBIHI THRESHOLD"


def test_potential_landslide_uses_either_threshold_and_latches_until_normal():
    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(base_dir=directory)

        assert not _update_safety_engine(engine, 0, vibration=0.1, tilt_x=5)["new_landslide_event"]
        result = _update_safety_engine(engine, 1, vibration=0.31, tilt_x=5)
        assert result["new_landslide_event"] is True
        assert result["potential_landslide"]["trigger_reason"] == "GETARAN MELEBIHI THRESHOLD"
        _update_safety_engine(engine, 2, vibration=0.1, tilt_x=5)

        result = _update_safety_engine(engine, 3, vibration=0.1, tilt_x=20)
        assert result["new_landslide_event"] is True
        assert result["potential_landslide"]["trigger_reason"] == "KEMIRINGAN MELEBIHI THRESHOLD"
        _update_safety_engine(engine, 4, vibration=0.1, tilt_x=5)
        result = _update_safety_engine(engine, 5, vibration=0.31, tilt_x=20)
        assert result["new_landslide_event"] is True
        assert result["buzzer_pattern"] == "three"
        event = result["potential_landslide"]
        assert event["event_type"] == "POTENSI_LONGSOR"
        assert event["latitude"] == -6.2
        assert event["longitude"] == 106.8
        assert event["vibration_threshold_g"] == 0.30
        assert event["tilt_threshold_deg"] == 15.0
        assert event["trigger_reason"] == "GETARAN DAN KEMIRINGAN MELEBIHI THRESHOLD"

        result = _update_safety_engine(engine, 4, vibration=0.31, tilt_x=20)
        assert result["new_landslide_event"] is False
        assert result["buzzer_pattern"] is None
        _update_safety_engine(engine, 5, vibration=0.1, tilt_x=5)
        result = _update_safety_engine(engine, 6, vibration=0.31, tilt_x=20)
        assert result["new_landslide_event"] is True
        assert result["buzzer_pattern"] == "three"


def test_potential_landslide_logs_null_coordinates_without_gps_fix():
    import csv

    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(base_dir=directory)
        result = _update_safety_engine(
            engine, 0, fix=0, lat=-6.2, lon=106.8, vibration=0.31, tilt_y=-19,
        )
        event = result["potential_landslide"]
        assert result["new_landslide_event"] is True
        assert event["latitude"] is None
        assert event["longitude"] is None
        assert event["gps_status"] == "NO_FIX"

        with open(os.path.join(directory, "log_safety_events.csv"), newline="") as handle:
            row = next(csv.DictReader(handle))
        assert row["latitude"] == ""
        assert row["longitude"] == ""
        assert row["gps_status"] == "NO_FIX"
        assert row["tilt_y_deg"] == "-19.0"


def test_potential_landslide_respects_tilt_reference_but_allows_vibration_only():
    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(base_dir=directory)
        result = engine.update(
            gps_fix=1,
            gps_lat=-6.2,
            gps_lon=106.8,
            gps_status="GPS FIX AKTIF",
            vibration_rms=0.31,
            vibration_peak=0.31,
            sw420_event_count=1,
            machine_state="ON",
            tilt_x=30.0,
            tilt_y=0.0,
            tilt_valid=False,
            now_monotonic=0.0,
        )
        assert result["new_landslide_event"] is True
        assert result["potential_landslide"]["trigger_reason"] == "GETARAN MELEBIHI THRESHOLD"

        result = engine.update(
            gps_fix=1,
            gps_lat=-6.2,
            gps_lon=106.8,
            gps_status="GPS FIX AKTIF",
            vibration_rms=0.31,
            vibration_peak=0.31,
            sw420_event_count=1,
            machine_state="ON",
            tilt_x=30.0,
            tilt_y=0.0,
            tilt_valid=True,
            now_monotonic=1.0,
        )
        assert result["new_landslide_event"] is False

        result = engine.update(
            gps_fix=1,
            gps_lat=-6.2,
            gps_lon=106.8,
            gps_status="GPS FIX AKTIF",
            vibration_rms=0.0,
            vibration_peak=0.0,
            sw420_event_count=0,
            machine_state="ON",
            tilt_x=0.0,
            tilt_y=0.0,
            tilt_valid=False,
            now_monotonic=2.0,
        )
        assert result["potential_landslide"]["active"] is False


def test_tuned_threshold_boundaries():
    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(base_dir=directory)
        result = _update_safety_engine(engine, 0, vibration=0.30, tilt_x=0.0)
        assert result["new_landslide_event"] is False
        result = _update_safety_engine(engine, 1, vibration=0.31, tilt_x=0.0)
        assert result["new_landslide_event"] is True
        assert result["potential_landslide"]["trigger_reason"] == "GETARAN MELEBIHI THRESHOLD"

    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(base_dir=directory)
        result = _update_safety_engine(engine, 0, vibration=0.1, tilt_x=13.0)
        assert result["new_landslide_event"] is False
        result = _update_safety_engine(engine, 1, vibration=0.1, tilt_x=15.0)
        assert result["new_landslide_event"] is False
        result = _update_safety_engine(engine, 2, vibration=0.1, tilt_x=15.1)
        assert result["new_landslide_event"] is True
        assert result["potential_landslide"]["trigger_reason"] == "KEMIRINGAN MELEBIHI THRESHOLD"


def test_idle_activation_boundary_is_ten_seconds():
    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(base_dir=directory)
        for second in range(8):
            result = _update_safety_engine(engine, second)
        assert result["idle_state"] == "IDLE_CANDIDATE"
        assert result["new_idle_event"] is False
        result = _update_safety_engine(engine, 10)
        assert result["idle_state"] == "IDLE_ACTIVE"
        assert result["new_idle_event"] is True


def test_landslide_buzzer_pattern_has_priority_over_idle_pattern():
    with tempfile.TemporaryDirectory() as directory:
        engine = main.SafetyEventEngine(base_dir=directory)
        for second in range(10):
            result = _update_safety_engine(engine, second, vibration=0.1)
            assert result["buzzer_pattern"] is None

        result = _update_safety_engine(engine, 10, vibration=0.31, tilt_x=20)
        assert result["new_idle_event"] is True
        assert result["new_landslide_event"] is True
        assert result["buzzer_pattern"] == "three"


def test_priority_buzzer_plays_requested_pulses_and_suppresses_under_blindspot_alarm():
    import time

    class FakeBuzzer:
        def __init__(self):
            self.on_count = 0
            self.off_count = 0
            self.closed = False

        def on(self):
            self.on_count += 1

        def off(self):
            self.off_count += 1

        def close(self):
            self.closed = True

    for pattern, expected_pulses in (("double", 2), ("three", 3)):
        device = FakeBuzzer()
        controller = main.PriorityBuzzer(device, on_time_s=0.001, off_time_s=0.001)
        try:
            assert controller.request_pattern(pattern) is True
            deadline = time.monotonic() + 1.0
            while device.off_count < expected_pulses + 1 and time.monotonic() < deadline:
                time.sleep(0.001)
            assert device.on_count == expected_pulses
            assert device.off_count >= expected_pulses + 1

            controller.set_blindspot_active(True)
            assert controller.request_pattern("three") is False
            deadline = time.monotonic() + 1.0
            while device.on_count == expected_pulses and time.monotonic() < deadline:
                time.sleep(0.001)
            assert device.on_count > expected_pulses
        finally:
            controller.close()
        assert device.closed is True
