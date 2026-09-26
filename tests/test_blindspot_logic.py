import os
import sys
import tempfile

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
