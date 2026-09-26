"""Interactive persistent calibration for the MPU6050 mounting position."""

import os
import sys

SENSOR_DIR = os.path.join(os.path.dirname(__file__), "File pengembangan dari Claude AI")
if SENSOR_DIR not in sys.path:
    sys.path.insert(0, SENSOR_DIR)

from mpu6050_sensor import MPU6050Sensor


def main():
    sensor = MPU6050Sensor()
    try:
        print("Letakkan alat pada posisi NORMAL dan diam.")
        input("Tekan Enter untuk mengambil sampel kalibrasi... ")
        reference = sensor.calibrate_reference()
        print(
            "Reference hasil kalibrasi: "
            f"X={reference['reference_tilt_x_deg']:.2f} derajat, "
            f"Y={reference['reference_tilt_y_deg']:.2f} derajat"
        )
        konfirmasi = input("Simpan reference ini? [y/N] ").strip().lower()
        if konfirmasi not in {"y", "ya"}:
            print("Kalibrasi dibatalkan.")
            return
        sensor.save_reference(reference)
        print(f"Kalibrasi tersimpan di {sensor.calibration_file}")
    finally:
        sensor.close()


if __name__ == "__main__":
    main()
