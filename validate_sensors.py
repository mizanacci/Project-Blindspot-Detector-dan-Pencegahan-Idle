#!/usr/bin/env python3
"""Script validasi sensor lapangan terpisah.

Tujuan: mengukur dan mencatat data MPU6050, GPS, dan SW-420 tanpa
mengaktifkan alarm blind spot atau memblokir loop utama.

Ini adalah alat diagnostik, bukan pengganti safety loop utama.
"""

import csv
import importlib.util
import os
import sys
import time
from datetime import datetime

MODULE_DIR = os.path.join(os.path.dirname(__file__), "File pengembangan dari Claude AI")
if MODULE_DIR not in sys.path:
    sys.path.insert(0, MODULE_DIR)


def load_module(module_name, file_name):
    module_path = os.path.join(MODULE_DIR, file_name)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Tidak dapat memuat {file_name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mpu6050_sensor = load_module("mpu6050_sensor", "mpu6050_sensor.py")
gps_neo6m = load_module("gps_neo6m", "gps_neo6m.py")
vibration_sw420 = load_module("vibration_sw420", "vibration_sw420.py")

MPU6050Sensor = mpu6050_sensor.MPU6050Sensor
GPSNeo6M = gps_neo6m.GPSNeo6M
SW420Sensor = vibration_sw420.SW420Sensor

LOG_FILE = "sensor_field_validation.csv"


def append_row(row):
    exists = os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="") as handle:
        writer = csv.writer(handle)
        if not exists:
            writer.writerow([
                "timestamp",
                "status_mesin",
                "status_idle",
                "durasi_idle_s",
                "getaran_g",
                "tilt_x_deg",
                "tilt_y_deg",
                "tilt_status",
                "sw420_terdeteksi",
                "gps_fix",
                "gps_lat",
                "gps_lon",
                "gps_status",
            ])
        writer.writerow(row)


def main():
    print("Mulai validasi sensor lapangan. Tekan Ctrl+C untuk berhenti.")
    try:
        mpu = MPU6050Sensor()
    except Exception as exc:
        print(f"MPU6050 tidak tersedia: {exc}")
        mpu = None

    try:
        gps = GPSNeo6M(port="/dev/serial0", baud=9600, timeout=0.2)
    except Exception as exc:
        print(f"GPS tidak tersedia: {exc}")
        gps = None

    try:
        sw420 = SW420Sensor(pin=17)
    except Exception as exc:
        print(f"SW-420 tidak tersedia: {exc}")
        sw420 = None

    try:
        while True:
            timestamp = datetime.now().isoformat(timespec="seconds")
            if mpu is not None:
                sensor = mpu.baca_status()
                status_mesin = sensor.get("status_mesin", "TIDAK_PASTI")
                status_idle = sensor.get("status_idle", "AMAN")
                durasi_idle_s = sensor.get("durasi_idle_s", 0)
                getaran_g = sensor.get("getaran_g", 0.0)
                tilt_x_deg = sensor.get("tilt_x_deg", 0.0)
                tilt_y_deg = sensor.get("tilt_y_deg", 0.0)
                tilt_status = sensor.get("tilt_status", "UNKNOWN")
            else:
                status_mesin = "TIDAK_PASTI"
                status_idle = "AMAN"
                durasi_idle_s = 0
                getaran_g = 0.0
                tilt_x_deg = 0.0
                tilt_y_deg = 0.0
                tilt_status = "UNAVAILABLE"

            if sw420 is not None:
                sw420_terdeteksi = bool(sw420.baca_terdeteksi(0.3))
            else:
                sw420_terdeteksi = False

            if gps is not None:
                pkt = gps.baca_lokasi(maks_baris=3)
                gps_fix = int(pkt.get("fix", 0) or 0)
                gps_lat = pkt.get("lat", 0.0)
                gps_lon = pkt.get("lon", 0.0)
                gps_status = pkt.get("status", "GPS NO DATA")
            else:
                gps_fix = 0
                gps_lat = 0.0
                gps_lon = 0.0
                gps_status = "GPS UNAVAILABLE"

            row = [
                timestamp,
                status_mesin,
                status_idle,
                durasi_idle_s,
                round(float(getaran_g), 4),
                round(float(tilt_x_deg), 2),
                round(float(tilt_y_deg), 2),
                tilt_status,
                int(sw420_terdeteksi),
                gps_fix,
                round(float(gps_lat), 6),
                round(float(gps_lon), 6),
                gps_status,
            ]
            append_row(row)
            print(f"[{timestamp}] Mesin={status_mesin} Idle={status_idle} Getaran={getaran_g:.4f}g "
                  f"TiltX={tilt_x_deg:.1f} TiltY={tilt_y_deg:.1f} SW420={sw420_terdeteksi} "
                  f"GPS={gps_status} ({gps_fix}, {gps_lat:.6f}, {gps_lon:.6f})")
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nValidasi sensor dihentikan oleh pengguna.")
    finally:
        if mpu is not None:
            mpu.close()
        if gps is not None:
            gps.close()
        if sw420 is not None:
            sw420.close()
        print(f"Data disimpan ke {LOG_FILE}")


if __name__ == "__main__":
    main()
