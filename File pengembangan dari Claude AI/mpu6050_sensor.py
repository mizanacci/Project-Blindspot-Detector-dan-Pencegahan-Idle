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

AMBANG_MESIN_MATI = 0.030   # di bawah ini = tidak ada getaran berarti
AMBANG_GERAK = 0.180        # di atas ini = jelas bergerak/beroperasi, bukan idle
DURASI_PERINGATAN_S = 3 * 60  # 3 menit idle -> IDLE_LAMA

MPU_ADDR = 0x68
PWR_MGMT_1 = 0x6B
ACCEL_XOUT_H = 0x3B

STATUS_MESIN_VALID = {"ON", "MATI", "TIDAK_PASTI"}
STATUS_IDLE_VALID = {"AMAN", "IDLE", "IDLE_LAMA"}


class MPU6050Sensor:
    def __init__(self, bus_num=1, smbus_module=None, durasi_burst_s=0.2):
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
        return math.sqrt(ax * ax + ay * ay + az * az)

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
            rata_burst = sum(sampel) / len(sampel)
            getaran_ac = max(abs(s - rata_burst) for s in sampel)
        except Exception:
            return {
                "status_mesin": "TIDAK_PASTI", "status_idle": "AMAN",
                "durasi_idle_s": 0, "getaran_g": 0.0,
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

        return {
            "status_mesin": status_mesin,
            "status_idle": status_idle,
            "durasi_idle_s": durasi_idle_s,
            "getaran_g": round(getaran_ac, 4),
        }

    def close(self):
        self.bus.close()
