"""
mpu6050_sensor.py
Baca MPU6050 (GY-521) LANGSUNG dari Raspberry Pi 4 lewat I2C -- bukan
lewat ESP32. Arsitektur ESP32 dibatalkan (rekomendasi dosen pembimbing:
satu Raspberry Pi saja demi purwarupa yang lebih compact), jadi logika
klasifikasi yang sebelumnya didesain untuk firmware ESP32 sekarang
dipindah jadi Python biasa yang jalan di Pi.

Prinsip klasifikasi SAMA seperti sebelumnya (Engine Idle Signature):
getaran mesin idle punya pola amplitudo di rentang tertentu, beda dari
getaran latar (nyaris nol) dan beda dari getaran saat benar-benar
bergerak/beroperasi (jauh lebih besar).

WIRING (I2C -- bus hardware Pi, bisa berbagi bus dengan sensor I2C lain):
    MPU6050 VCC -> Pi 3.3V (pin fisik 1 atau 17)
    MPU6050 GND -> Pi GND  (pin fisik 6/9/14/20/25/dst.)
    MPU6050 SDA -> Pi GPIO2 / SDA (pin fisik 3)
    MPU6050 SCL -> Pi GPIO3 / SCL (pin fisik 5)

PANGGIL baca_status() SEKALI PER SIKLUS (misal sekali per detik sesuai
throttle utama di main.py, lihat throttle_pattern.py) -- fungsi ini
sendiri sudah mengambil burst sampel singkat (default 0.2 detik) di
dalamnya, jadi memanggilnya lebih sering dari itu cuma menambah beban
CPU tanpa manfaat tambahan.

CATATAN DESAIN (ditemukan lewat pengujian, bukan cuma teori): mengambil
SATU titik sesaat sekali per detik ternyata bisa "meleset" menangkap
getaran mesin yang frekuensinya jauh lebih tinggi (puluhan Hz) --
kebetulan sampling pas di titik nol gelombang getaran walau getaran
sebenarnya ada. Makanya tiap panggilan mengambil beberapa sampel cepat
dulu (burst) dan pakai deviasi PUNCAK dalam burst itu, bukan satu titik.
"""

import time
import math
import json
import os

AMBANG_MESIN_MATI = 0.030   # di bawah ini = tidak ada getaran berarti
AMBANG_GERAK = 0.180        # di atas ini = jelas bergerak/beroperasi, bukan idle
DURASI_PERINGATAN_S = 3 * 60  # 3 menit idle -> IDLE_LAMA
BATAS_KEMIRINGAN_RELATIF_DERAJAT = 12.0
FILE_KALIBRASI_DEFAULT = os.path.join(
    os.path.dirname(__file__), "mpu6050_calibration.json"
)

MPU_ADDR = 0x68
PWR_MGMT_1 = 0x6B
ACCEL_XOUT_H = 0x3B

STATUS_MESIN_VALID = {"ON", "MATI", "TIDAK_PASTI"}
STATUS_IDLE_VALID = {"AMAN", "IDLE", "IDLE_LAMA"}


def _clip(value, minimum, maximum):
    return max(minimum, min(maximum, value))


class MPU6050Sensor:
    def __init__(self, bus_num=1, smbus_module=None, durasi_burst_s=0.2,
                 calibration_file=FILE_KALIBRASI_DEFAULT):
        """
        smbus_module: parameter tambahan HANYA untuk pengujian tanpa
        hardware asli (disuntik dengan bus tiruan). Di pemakaian normal,
        biarkan default -- akan otomatis pakai smbus2.

        durasi_burst_s: tiap panggilan baca_status() mengambil beberapa
        sampel cepat selama durasi ini (bukan satu titik sesaat) --
        lihat catatan desain di docstring modul ini.
        """
        if smbus_module is None:
            import smbus2 as smbus_module
        self.bus = smbus_module.SMBus(bus_num)
        self._init_sensor()
        self._idle_mulai = None
        self.durasi_burst_s = durasi_burst_s
        self.calibration_file = calibration_file
        self.reference_tilt_x_deg = None
        self.reference_tilt_y_deg = None
        self.load_reference()

    def _init_sensor(self):
        self.bus.write_byte_data(MPU_ADDR, PWR_MGMT_1, 0)
        time.sleep(0.1)

    def _read_word(self, reg):
        high = self.bus.read_byte_data(MPU_ADDR, reg)
        low = self.bus.read_byte_data(MPU_ADDR, reg + 1)
        val = (high << 8) + low
        if val >= 0x8000:
            val = -((65535 - val) + 1)
        return val

    def _baca_magnitude_g(self):
        ax = self._read_word(ACCEL_XOUT_H) / 16384.0
        ay = self._read_word(ACCEL_XOUT_H + 2) / 16384.0
        az = self._read_word(ACCEL_XOUT_H + 4) / 16384.0
        return ax, ay, az, math.sqrt(ax * ax + ay * ay + az * az)

    @staticmethod
    def calculate_tilt_deg(ax, ay, az):
        ax = float(ax)
        ay = float(ay)
        az = float(az)
        tilt_x_deg = math.degrees(math.atan2(ay, math.sqrt(ax * ax + az * az)))
        tilt_y_deg = math.degrees(math.atan2(ax, math.sqrt(ay * ay + az * az)))
        return tilt_x_deg, tilt_y_deg

    @staticmethod
    def normalize_angle_delta(angle_deg):
        """Return the shortest signed angle difference in [-180, 180)."""
        return (float(angle_deg) + 180.0) % 360.0 - 180.0

    @staticmethod
    def get_tilt_status(tilt_x_deg, tilt_y_deg,
                        threshold_deg=BATAS_KEMIRINGAN_RELATIF_DERAJAT):
        if abs(float(tilt_x_deg)) > threshold_deg or abs(float(tilt_y_deg)) > threshold_deg:
            return "MIRING"
        return "NORMAL"

    @property
    def reference_available(self):
        return (self.reference_tilt_x_deg is not None and
                self.reference_tilt_y_deg is not None)

    def load_reference(self):
        try:
            with open(self.calibration_file) as handle:
                data = json.load(handle)
            self.reference_tilt_x_deg = float(data["reference_tilt_x_deg"])
            self.reference_tilt_y_deg = float(data["reference_tilt_y_deg"])
        except (FileNotFoundError, KeyError, TypeError, ValueError, OSError):
            self.reference_tilt_x_deg = None
            self.reference_tilt_y_deg = None

    def save_reference(self, reference):
        self.reference_tilt_x_deg = float(reference["reference_tilt_x_deg"])
        self.reference_tilt_y_deg = float(reference["reference_tilt_y_deg"])
        with open(self.calibration_file, "w") as handle:
            json.dump({
                "reference_tilt_x_deg": self.reference_tilt_x_deg,
                "reference_tilt_y_deg": self.reference_tilt_y_deg,
            }, handle, indent=2)
            handle.write("\n")

    def calibrate_reference(self, jumlah_sampel=30, interval_s=0.05,
                            batas_stabilitas_derajat=3.0):
        """Average a stationary normal position and return a persistent reference."""
        samples = []
        for _ in range(jumlah_sampel):
            ax, ay, az, _ = self._baca_magnitude_g()
            samples.append(self.calculate_tilt_deg(ax, ay, az))
            time.sleep(interval_s)

        if not samples:
            raise ValueError("Tidak ada sampel MPU6050")

        tilt_x_values = [sample[0] for sample in samples]
        tilt_y_values = [sample[1] for sample in samples]
        if (max(tilt_x_values) - min(tilt_x_values) > batas_stabilitas_derajat or
                max(tilt_y_values) - min(tilt_y_values) > batas_stabilitas_derajat):
            raise ValueError("Posisi MPU tidak stabil selama kalibrasi")

        reference = {
            "reference_tilt_x_deg": sum(tilt_x_values) / len(tilt_x_values),
            "reference_tilt_y_deg": sum(tilt_y_values) / len(tilt_y_values),
        }
        return reference

    def _relative_tilt(self, raw_tilt_x_deg, raw_tilt_y_deg):
        if not self.reference_available:
            return raw_tilt_x_deg, raw_tilt_y_deg
        return (
            self.normalize_angle_delta(raw_tilt_x_deg - self.reference_tilt_x_deg),
            self.normalize_angle_delta(raw_tilt_y_deg - self.reference_tilt_y_deg),
        )

    def baca_status(self):
        """
        Return dict: {status_mesin, status_idle, durasi_idle_s, getaran_g}

        status_mesin: ON / MATI / TIDAK_PASTI
            TIDAK_PASTI dipakai HANYA saat pembacaan sensor gagal
            (misal I2C error) -- eksplisit "sensor tidak bisa dibaca
            saat ini", bukan disamarkan jadi status yang kelihatan pasti.
        status_idle: AMAN / IDLE / IDLE_LAMA
            AMAN kalau mesin mati ATAU sedang bergerak/beroperasi.
        """
        try:
            sampel = []
            mulai = time.time()
            while time.time() - mulai < self.durasi_burst_s:
                sampel.append(self._baca_magnitude_g())
            if len(sampel) < 3:
                sampel.append(self._baca_magnitude_g())
                sampel.append(self._baca_magnitude_g())

            ax_values = [item[0] for item in sampel]
            ay_values = [item[1] for item in sampel]
            az_values = [item[2] for item in sampel]
            mag_values = [item[3] for item in sampel]
            rata_burst = sum(mag_values) / len(mag_values)
            getaran_ac = max(abs(s - rata_burst) for s in mag_values)
            ax_avg = sum(ax_values) / len(ax_values)
            ay_avg = sum(ay_values) / len(ay_values)
            az_avg = sum(az_values) / len(az_values)
            raw_tilt_x_deg, raw_tilt_y_deg = self.calculate_tilt_deg(
                ax_avg, ay_avg, az_avg
            )
        except Exception:
            return {
                "status_mesin": "TIDAK_PASTI", "status_idle": "AMAN",
                "durasi_idle_s": 0, "getaran_g": 0.0,
                "tilt_x_deg": 0.0, "tilt_y_deg": 0.0,
                "tilt_status": "TIDAK_DAPAT_DIBACA",
            }

        now = time.time()

        if getaran_ac <= AMBANG_MESIN_MATI:
            status_mesin, status_idle = "MATI", "AMAN"
            self._idle_mulai = None
        elif getaran_ac >= AMBANG_GERAK:
            status_mesin, status_idle = "ON", "AMAN"  # bergerak/beroperasi, bukan idle
            self._idle_mulai = None
        else:
            status_mesin = "ON"
            if self._idle_mulai is None:
                self._idle_mulai = now
            durasi = now - self._idle_mulai
            status_idle = "IDLE_LAMA" if durasi >= DURASI_PERINGATAN_S else "IDLE"

        durasi_idle_s = int(now - self._idle_mulai) if self._idle_mulai else 0
        tilt_x_deg, tilt_y_deg = self._relative_tilt(
            raw_tilt_x_deg, raw_tilt_y_deg
        )
        tilt_status = (self.get_tilt_status(tilt_x_deg, tilt_y_deg)
                       if self.reference_available else
                       "REFERENCE_BELUM_DIKALIBRASI")

        return {
            "status_mesin": status_mesin,
            "status_idle": status_idle,
            "durasi_idle_s": durasi_idle_s,
            "getaran_g": round(getaran_ac, 4),
            "tilt_x_deg": round(_clip(float(tilt_x_deg), -90.0, 90.0), 1),
            "tilt_y_deg": round(_clip(float(tilt_y_deg), -90.0, 90.0), 1),
            "tilt_status": tilt_status,
        }

    def close(self):
        self.bus.close()
