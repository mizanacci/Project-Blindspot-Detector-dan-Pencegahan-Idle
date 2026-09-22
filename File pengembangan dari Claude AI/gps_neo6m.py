"""
gps_neo6m.py
Baca modul GPS NEO-6M lewat UART Raspberry Pi -- memakai port yang
SEBELUMNYA direncanakan untuk komunikasi ke ESP32. Karena arsitektur
ESP32 dibatalkan, UART itu sekarang bebas dipakai GPS.

WIRING:
    NEO-6M VCC -> Pi 5V (kebanyakan breakout NEO-6M butuh 5V walau
                  level sinyal TX/RX-nya 3.3V -- cek datasheet modul
                  kamu, jangan asal sambung ke 3.3V kalau modulnya
                  butuh 5V untuk regulator onboard-nya)
    NEO-6M GND -> Pi GND
    NEO-6M TX  -> Pi RXD, GPIO15, pin fisik 10
    NEO-6M RX  -> Pi TXD, GPIO14, pin fisik 8 (opsional -- GPS pada
                  umumnya tidak perlu menerima perintah dari Pi untuk
                  operasi dasar, cukup sambung TX GPS -> RX Pi saja
                  kalau mau lebih sederhana)

SEBELUM DIPAKAI, port serial Pi harus dikonfigurasi (SAMA seperti
persiapan yang sebelumnya didokumentasikan untuk ESP32 -- prosesnya
identik, tinggal dipakai ulang):
    sudo raspi-config -> Interface Options -> Serial Port
    "login shell over serial" -> No
    "serial port hardware"    -> Yes
    (lalu reboot)

Dependensi: pip install pynmea2 pyserial --break-system-packages

Modul NEO-6M defaultnya kirim banyak jenis sentence NMEA per detik
(GGA, RMC, GSV, dst). Kita cuma ambil GGA/RMC untuk fix posisi --
sentence lain diabaikan begitu saja, bukan error.
"""

import serial
import pynmea2


class GPSNeo6M:
    def __init__(self, port="/dev/serial0", baud=9600, timeout=1.0, serial_factory=None):
        """
        serial_factory: parameter tambahan HANYA untuk pengujian tanpa
        hardware asli (disuntik port serial virtual). Di pemakaian
        normal, biarkan default -- akan otomatis pakai pyserial.
        """
        if serial_factory is None:
            serial_factory = serial.Serial
        self.ser = serial_factory(port, baud, timeout=timeout)

    def baca_lokasi(self, maks_baris=15):
        """
        Baca beberapa baris NMEA sampai ketemu sentence GGA/RMC yang
        punya fix valid, atau sampai maks_baris habis. NEO-6M kirim
        banyak jenis sentence per detik jadi wajar perlu baca beberapa
        baris untuk menemukan satu yang relevan.

        Return: {'fix': 0 atau 1, 'lat': float, 'lon': float}
        fix=0 (lat/lon=0.0) kalau tidak ada fix valid ditemukan --
        INI BUKAN KOORDINAT SUNGGUHAN, cuma nilai kosong/placeholder.
        """
        for _ in range(maks_baris):
            try:
                mentah = self.ser.readline()
                baris = mentah.decode("ascii", errors="ignore").strip()
            except Exception:
                continue

            if not baris.startswith("$"):
                continue

            try:
                pesan = pynmea2.parse(baris)
            except pynmea2.ParseError:
                continue  # checksum salah/format rusak -- lewati, jangan crash

            hasil = self._ekstrak_fix(pesan)
            if hasil is not None:
                return hasil

        return {"fix": 0, "lat": 0.0, "lon": 0.0}

    @staticmethod
    def _ekstrak_fix(pesan):
        tipe = type(pesan).__name__
        if tipe == "GGA":
            if pesan.gps_qual and int(pesan.gps_qual) > 0 and pesan.latitude and pesan.longitude:
                return {"fix": 1, "lat": float(pesan.latitude), "lon": float(pesan.longitude)}
        elif tipe == "RMC":
            if pesan.status == "A" and pesan.latitude and pesan.longitude:
                return {"fix": 1, "lat": float(pesan.latitude), "lon": float(pesan.longitude)}
        return None

    def close(self):
        self.ser.close()
