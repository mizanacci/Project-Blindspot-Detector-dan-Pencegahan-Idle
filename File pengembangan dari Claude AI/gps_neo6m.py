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

import time

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
        self.nmea_received = False
        self.nmea_sentence_count = 0
        self.gga_received = False
        self.rmc_received = False
        self.satellites = None
        self.last_sentence_time = None
        self.last_error = None

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
        fix = None
        for _ in range(maks_baris):
            try:
                mentah = self.ser.readline()
                baris = mentah.decode("ascii", errors="ignore").strip()
            except Exception as exc:
                self.last_error = str(exc)
                continue

            if not baris.startswith("$"):
                continue

            self.nmea_received = True
            self.nmea_sentence_count += 1
            self.last_sentence_time = time.strftime("%H:%M:%S")

            try:
                pesan = pynmea2.parse(baris)
            except pynmea2.ParseError:
                continue  # checksum salah/format rusak -- lewati, jangan crash

            tipe = type(pesan).__name__
            if tipe == "GGA":
                self.gga_received = True
                self.satellites = self._parse_satellites(pesan)
            elif tipe == "RMC":
                self.rmc_received = True

            hasil = self._ekstrak_fix(pesan)
            if hasil is not None:
                fix = hasil
                break

        if fix is not None:
            status = "GPS FIX AKTIF"
        elif self.nmea_received:
            status = "GPS UART OK - MENUNGGU FIX"
        elif self.last_error:
            status = "GPS UART ERROR"
        else:
            status = "GPS UART NO DATA"

        return {
            "fix": 1 if fix is not None else 0,
            "lat": fix["lat"] if fix is not None else 0.0,
            "lon": fix["lon"] if fix is not None else 0.0,
            "status": status,
            "uart_status": "ERROR" if self.last_error else (
                "OK" if self.nmea_received else "NO DATA"
            ),
            "nmea_received": self.nmea_received,
            "nmea_sentence_count": self.nmea_sentence_count,
            "gga_received": self.gga_received,
            "rmc_received": self.rmc_received,
            "satellites": self.satellites,
            "last_sentence_time": self.last_sentence_time,
        }

    @staticmethod
    def _parse_satellites(pesan):
        value = getattr(pesan, "num_sats", None)
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _ekstrak_fix(pesan):
        tipe = type(pesan).__name__
        gps_qual = getattr(pesan, "gps_qual", None)
        latitude = getattr(pesan, "latitude", None)
        longitude = getattr(pesan, "longitude", None)
        status = getattr(pesan, "status", None)

        if tipe == "GGA":
            try:
                valid_fix = gps_qual is not None and int(gps_qual) > 0
            except (TypeError, ValueError):
                valid_fix = False
            if valid_fix and latitude is not None and longitude is not None:
                return {"fix": 1, "lat": float(latitude), "lon": float(longitude)}
        elif tipe == "RMC":
            if status == "A" and latitude is not None and longitude is not None:
                return {"fix": 1, "lat": float(latitude), "lon": float(longitude)}
        return None

    def close(self):
        self.ser.close()
