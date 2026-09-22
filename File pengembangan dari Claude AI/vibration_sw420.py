"""
vibration_sw420.py
Baca sensor getaran digital SW-420 lewat GPIO Raspberry Pi.

BEDA dari MPU6050: SW-420 cuma kasih sinyal digital HIGH/LOW berdasarkan
ambang yang diatur lewat potensiometer FISIK di modulnya sendiri --
tidak ada nilai magnitude seperti MPU6050. Dipakai sebagai sinyal
pelengkap yang sederhana dan murah, BUKAN pengganti MPU6050 untuk
klasifikasi idle yang lebih detail (lihat mpu6050_sensor.py).

WIRING:
    SW-420 VCC -> Pi 3.3V atau 5V (cek papan modul kamu -- kebanyakan
                  modul SW-420 punya comparator onboard yang toleran
                  3.3-5V, tapi pastikan dulu sebelum sambung ke 5V)
    SW-420 GND -> Pi GND
    SW-420 DO  -> Pi GPIO17 (bisa diganti pin lain -- GPIO17 dipilih
                  karena tidak dipakai fungsi lain di sistem blind spot
                  yang sudah ada: buzzer=22, LED hijau=23, kuning=24,
                  merah=25)

Sebelum dipasang di alat berat sungguhan: putar potensiometer di modul
SW-420 sambil pantau outputnya supaya sensitivitasnya pas -- terlalu
sensitif akan selalu HIGH, terlalu tidak sensitif tidak akan pernah
mendeteksi apapun.
"""

import time


class SW420Sensor:
    def __init__(self, pin=17, device_factory=None):
        """
        device_factory: parameter tambahan HANYA untuk pengujian tanpa
        hardware asli. Di pemakaian normal, biarkan default.
        """
        if device_factory is None:
            from gpiozero import DigitalInputDevice
            device_factory = DigitalInputDevice
        self.sensor = device_factory(pin)

    def baca_terdeteksi(self, jendela_s=0.3):
        """
        Return True kalau ada minimal satu transisi sinyal (getaran
        terdeteksi) dalam jendela_s detik terakhir, False kalau tidak.
        Jendela pendek (0.3s default) cukup untuk konfirmasi cepat
        tanpa menghabiskan banyak waktu di siklus 1Hz utama -- total
        waktu baca SW-420 + MPU6050 (burst 0.2s) masih jauh di bawah
        1 detik, menyisakan ruang untuk kamera+YOLO di siklus yang sama.
        """
        mulai = time.time()
        state_awal = self.sensor.value
        while time.time() - mulai < jendela_s:
            if self.sensor.value != state_awal:
                return True
            time.sleep(0.005)
        return False

    def close(self):
        self.sensor.close()
