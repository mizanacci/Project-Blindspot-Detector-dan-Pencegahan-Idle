import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'File pengembangan dari Claude AI'))

from fuzzy_engine import evaluate_urgency, StatusStabilizer
from tracker import SimpleTracker
from mpu6050_sensor import MPU6050Sensor
from gps_neo6m import GPSNeo6M
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


def test_gps_valid_fix_at_zero_coordinates_is_accepted():
    msg = type("GGA", (), {"gps_qual": "1", "latitude": 0.0, "longitude": 0.0})()
    assert GPSNeo6M._ekstrak_fix(msg) == {"fix": 1, "lat": 0.0, "lon": 0.0}


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
    assert any(item["label"] == "MPU6050" and item.get("critical") is False for item in checks)
