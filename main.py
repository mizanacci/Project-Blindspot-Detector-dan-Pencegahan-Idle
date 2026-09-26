"""
main.py
Loop utama: baca kamera -> deteksi orang (YOLO) -> lacak tiap orang
(tracker) -> estimasi jarak & durasi per orang -> fuzzy logic urgensi
tertinggi di antara semua orang -> stabilisasi status (anti false-alarm)
-> LED/buzzer -> log CSV.

SEBELUM DIJALANKAN:
1. pip install -r requirements.txt --break-system-packages
2. Pasang kamera di posisi & sudut FINAL, lalu jalankan calibrate_zone.py
   sampai zone_config.json terbentuk
3. Sesuaikan nomor pin GPIO di bawah dengan wiring kamu

v2: sekarang melacak SEMUA orang di frame (bukan cuma yang paling dekat)
lewat tracker.py, dan status alarm distabilkan lewat StatusStabilizer di
fuzzy_engine.py supaya tidak kedip-kedip akibat flicker deteksi sesaat.
"""

import time
import json
import csv
import os
import select
import sys
from datetime import datetime

import cv2
from gpiozero import Buzzer, LED

from vision import PersonDetector
from tracker import SimpleTracker
from fuzzy_engine import evaluate_urgency, StatusStabilizer

SENSOR_DIR = os.path.join(os.path.dirname(__file__), "File pengembangan dari Claude AI")
if SENSOR_DIR not in sys.path:
    sys.path.insert(0, SENSOR_DIR)

from mpu6050_sensor import MPU6050Sensor
from vibration_sw420 import SW420Sensor
from gps_neo6m import GPSNeo6M
from throttle_pattern import LoopThrottle
from dashboard import start_dashboard_server, state

BUZZER_PIN = 22
LED_HIJAU_PIN = 23     # status: aman
LED_KUNING_PIN = 24    # status: siaga
LED_MERAH_PIN = 25     # status: bahaya

LOG_FILE = "log_blindspot.csv"
SENSOR_LOG_FILE = "log_sensor_tambahan.csv"
ZONE_CONFIG_FILE = "zone_config.json"

# Lewati N-1 frame di antara tiap inference YOLO -- optimasi performa.
# 1 = proses tiap frame (paling akurat, paling berat). Naikkan ke 2-3
# kalau FPS di Pi 4 kamu masih terasa berat setelah pakai model NCNN.
FRAME_SKIP = 1
GPS_READ_TIMEOUT_S = 0.05
GPS_MAX_LINES = 5


def load_zone_config():
    with open(ZONE_CONFIG_FILE) as f:
        return json.load(f)

def estimate_distance(bbox_bottom_y, cfg):
    """
    Estimasi jarak menggunakan interpolasi linear
    berdasarkan seluruh titik kalibrasi.

    Semakin besar y2 -> orang semakin dekat.
    Di luar rentang kalibrasi, hasil di-clamp ke
    titik terjauh/terdekat yang tersedia.
    """

    points = cfg["calibration_points"]

    if not points:
        return 15.0

    # Pastikan titik terurut berdasarkan y2
    points = sorted(points, key=lambda p: p["y2"])

    # Di luar sisi jauh
    if bbox_bottom_y <= points[0]["y2"]:
        return points[0]["distance_m"]

    # Di luar sisi dekat
    if bbox_bottom_y >= points[-1]["y2"]:
        return points[-1]["distance_m"]

    # Cari dua titik yang mengapit bbox_bottom_y
    for i in range(len(points) - 1):

        p1 = points[i]
        p2 = points[i + 1]

        y1 = p1["y2"]
        y2 = p2["y2"]

        d1 = p1["distance_m"]
        d2 = p2["distance_m"]

        if y1 <= bbox_bottom_y <= y2:

            if y2 == y1:
                return d1

            # Interpolasi linear
            t = (bbox_bottom_y - y1) / (y2 - y1)

            jarak = d1 + t * (d2 - d1)

            return max(0.5, min(15.0, jarak))

    return points[-1]["distance_m"]

def setup_log():
    try:
        with open(LOG_FILE, 'r') as f:
            kosong = (f.read(1) == '')
    except FileNotFoundError:
        kosong = True
    if kosong:
        with open(LOG_FILE, 'w', newline='') as f:
            csv.writer(f).writerow([
                'timestamp', 'jumlah_orang', 'jarak_terdekat_m',
                'durasi_terlama_s', 'skor_urgensi', 'status_mentah',
                'status_stabil'
            ])

    try:
        with open(SENSOR_LOG_FILE, 'r') as f:
            kosong = (f.read(1) == '')
    except FileNotFoundError:
        kosong = True
    if kosong:
        with open(SENSOR_LOG_FILE, 'w', newline='') as f:
            csv.writer(f).writerow([
                'timestamp', 'status_mesin', 'status_idle', 'durasi_idle_s',
                'getaran_g', 'sw420_terdeteksi', 'gps_fix', 'gps_lat', 'gps_lon',
                'tilt_x_deg', 'tilt_y_deg', 'tilt_status'
            ])


def log_reading(row):
    with open(LOG_FILE, 'a', newline='') as f:
        csv.writer(f).writerow(row)


def log_sensor_reading(row):
    with open(SENSOR_LOG_FILE, 'a', newline='') as f:
        csv.writer(f).writerow(row)


def set_output(status, buzzer, led_hijau, led_kuning, led_merah):
    led_hijau.off(); led_kuning.off(); led_merah.off(); buzzer.off()
    if status == 'aman':
        led_hijau.on()
    elif status == 'siaga':
        led_kuning.on()
    else:
        led_merah.on()
        buzzer.on()


def urgensi_paling_parah(tracks_aktif, cfg):
    """
    Hitung urgensi untuk SETIAP orang yang dilacak, lalu kembalikan yang
    paling parah -- karena satu orang yang benar-benar dekat/lama itu
    tetap harus memicu alarm, tidak boleh "dirata-rata" jadi kelihatan
    aman gara-gara orang lain di frame sedang jauh.
    """
    if not tracks_aktif:
        return 15.0, 0.0, 0.0, 'aman'

    terparah = None
    for tr in tracks_aktif:
        jarak_m = estimate_distance(tr['y2'], cfg)
        skor, label = evaluate_urgency(jarak_m, tr['durasi_s'])
        if terparah is None or skor > terparah[0]:
            terparah = (skor, jarak_m, tr['durasi_s'], label)

    return terparah[1], terparah[2], terparah[0], terparah[3]


def wait_for_operator_start():
    """Mencegah sistem langsung aktif tanpa persetujuan operator."""
    print("\nPanduan mulai sistem:")
    print("1. Pastikan area sekitar alat berat aman.")
    print("2. Pastikan kamera, sensor, dan GPS sudah siap.")
    print("3. Tekan Enter untuk mulai deteksi blind spot.")
    print("   (Mode non-interaktif: sistem akan mulai otomatis.)")

    try:
        if sys.stdin.isatty():
            while True:
                if state.consume_start_request():
                    break
                ready, _, _ = select.select([sys.stdin], [], [], 0.25)
                if ready:
                    input()
                    break
    except (EOFError, KeyboardInterrupt):
        print("Start dibatalkan oleh operator.")
        raise

    print("Operator menekan start. Sistem dimulai.\n")


def run_startup_check(cfg, cap, mpu6050, sw420, gps):
    """Hasil cek awal untuk operator; ini bukan pengganti alarm blind spot."""
    checks = []
    checks.append({
        "label": "Kalibrasi zona",
        "ok": bool(cfg and isinstance(cfg.get("calibration_points"), list) and len(cfg["calibration_points"]) >= 2),
        "critical": True,
    })
    checks.append({
        "label": "Kamera /dev/video0",
        "ok": bool(cap is not None and cap.isOpened()),
        "critical": True,
    })
    checks.append({
        "label": "MPU6050 I2C",
        "ok": mpu6050 is not None,
        "critical": False,
    })
    checks.append({
        "label": "MPU6050 reference",
        "ok": bool(mpu6050 is not None and mpu6050.reference_available),
        "critical": False,
    })
    checks.append({
        "label": "SW-420",
        "ok": sw420 is not None,
        "critical": False,
    })
    checks.append({
        "label": "GPS UART",
        "ok": gps is not None,
        "critical": False,
    })
    checks.append({
        "label": "Alarm pengaman siap",
        "ok": True,
        "critical": True,
    })
    return checks


def startup_ready_for_start(checks):
    """Startup diperbolehkan hanya bila semua item kritis sudah OK."""
    for item in checks:
        if item.get("critical") and not item.get("ok", False):
            return False
    return True


def can_use_gui():
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def safe_imshow(window_name, frame):
    if not can_use_gui() or frame is None:
        return -1
    cv2.imshow(window_name, frame)
    return cv2.waitKey(1) & 0xFF


def main():
    start_dashboard_server()
    state.set_operator_notice("Sistem siap — menunggu operator menekan start")

    cfg = load_zone_config()

    print("Kalibrasi jarak:")
    for point in cfg["calibration_points"]:
        print(
            f"  y2={point['y2']:.2f} px"
            f" -> {point['distance_m']:.2f} m"
        )

    detector = PersonDetector()
    tracker = SimpleTracker()
    stabilizer = StatusStabilizer()
    throttle = LoopThrottle(interval_s=1.0)

    try:
        mpu6050 = MPU6050Sensor()
    except Exception as exc:
        mpu6050 = None
        print(f"MPU6050 tidak tersedia: {exc}")
    try:
        sw420 = SW420Sensor(pin=17)
    except Exception as exc:
        sw420 = None
        print(f"SW-420 tidak tersedia: {exc}")
    try:
        gps = GPSNeo6M(
            port="/dev/serial0",
            baud=9600,
            timeout=GPS_READ_TIMEOUT_S,
        )
    except Exception as exc:
        gps = None
        print(f"GPS NEO-6M tidak tersedia: {exc}")

    cap = cv2.VideoCapture("/dev/video0", cv2.CAP_V4L2)

    cap.set(cv2.CAP_PROP_FOURCC,
            cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 10)
    if not cap.isOpened():
        print("Kamera tidak terdeteksi. Cek koneksi webcam.")
        return

    buzzer = Buzzer(BUZZER_PIN)
    led_hijau = LED(LED_HIJAU_PIN)
    led_kuning = LED(LED_KUNING_PIN)
    led_merah = LED(LED_MERAH_PIN)

    setup_log()
    startup_checks = run_startup_check(cfg, cap, mpu6050, sw420, gps)
    state.update_startup_checks(startup_checks)
    print("Checklist startup:")
    for item in startup_checks:
        status = 'OK' if item['ok'] else 'PERIKSA'
        prioritas = 'KRITIS' if item.get('critical') else 'OPSIONAL'
        print(f"  - {item['label']}: {status} [{prioritas}]")

    if not startup_ready_for_start(startup_checks):
        state.set_operator_notice("START DIBLOKIR: item kritis belum siap")
        print("\nSTART DIBLOKIR. Perbaiki item kritis berikut sebelum menjalankan sistem:")
        for item in startup_checks:
            if item.get('critical') and not item.get('ok', False):
                print(f"  - {item['label']}")
        return

    wait_for_operator_start()
    state.set_operator_notice("Sistem aktif — deteksi blind spot berjalan")
    print("Sistem deteksi blind spot berjalan. Ctrl+C untuk berhenti.\n")

    frame_ke = 0
    orang_terdeteksi = []  # cache hasil deteksi terakhir, dipakai ulang saat frame di-skip

    try:
        while True:
            throttle.mulai_siklus()
            ret, frame = cap.read()
            if not ret:
                print("Gagal membaca frame kamera, coba lagi...")
                throttle.tunggu_sisa_waktu()
                continue

            frame_ke += 1
            state.update_frame(frame)
            if frame_ke % FRAME_SKIP == 0:
                orang_terdeteksi = detector.detect_people(frame)

            tracks_aktif = tracker.update(orang_terdeteksi)
            jarak_m, durasi_s, skor, status_mentah = urgensi_paling_parah(tracks_aktif, cfg)
            status_stabil = stabilizer.update(status_mentah)

            sensor_mpu = (mpu6050.baca_status() if mpu6050 is not None else {
                'status_mesin': 'TIDAK_PASTI', 'status_idle': 'AMAN',
                'durasi_idle_s': 0, 'getaran_g': 0.0,
                'tilt_x_deg': 0.0, 'tilt_y_deg': 0.0,
                'tilt_status': 'I2C TIDAK TERSEDIA',
            })
            sw420_terdeteksi = sw420.baca_terdeteksi() if sw420 is not None else False
            gps_lokasi = (gps.baca_lokasi(maks_baris=GPS_MAX_LINES) if gps is not None else {
                'fix': 0, 'lat': 0.0, 'lon': 0.0,
                'status': 'GPS UART ERROR', 'uart_status': 'ERROR',
                'nmea_received': False, 'nmea_sentence_count': 0,
                'gga_received': False, 'rmc_received': False,
                'satellites': None, 'last_sentence_time': None,
            })

            set_output(status_stabil, buzzer, led_hijau, led_kuning, led_merah)
            state.update_status(
                status_stabil, jarak_m, durasi_s, skor, len(tracks_aktif)
            )
            state.update_sensor_tambahan(
                sensor_mpu['status_mesin'], sensor_mpu['status_idle'],
                sensor_mpu['durasi_idle_s'], sensor_mpu['getaran_g'],
                gps_lokasi['fix'], gps_lokasi['lat'], gps_lokasi['lon'],
                sensor_mpu['tilt_x_deg'], sensor_mpu['tilt_y_deg'],
                sensor_mpu['tilt_status'], gps_lokasi['status'],
                gps_lokasi['uart_status'], gps_lokasi['nmea_received'],
                gps_lokasi['nmea_sentence_count'], gps_lokasi['gga_received'],
                gps_lokasi['rmc_received'], gps_lokasi['satellites'],
                gps_lokasi['last_sentence_time']
            )

            timestamp = datetime.now().isoformat(timespec='seconds')
            print(f"[{timestamp}] orang={len(tracks_aktif)}  jarak_terdekat={jarak_m:5.1f}m  "
                  f"durasi_terlama={durasi_s:5.1f}s  skor={skor:5.1f}  "
                  f"mentah={status_mentah:7s} -> STABIL={status_stabil.upper()}")
            print(f"  sensor: mesin={sensor_mpu['status_mesin']}  "
                f"idle={sensor_mpu['status_idle']}  "
                f"getaran={sensor_mpu['getaran_g']:.4f}g  "
                f"tilt_x={sensor_mpu['tilt_x_deg']:.1f}deg  "
                f"tilt_y={sensor_mpu['tilt_y_deg']:.1f}deg  "
                f"tilt_status={sensor_mpu['tilt_status']}  "
                f"SW420={sw420_terdeteksi}  "
                f"GPS={gps_lokasi['status']}  "
                f"sat={gps_lokasi['satellites'] or '-'}  "
                f"({gps_lokasi['lat']:.6f}, {gps_lokasi['lon']:.6f})")

            log_reading([
                timestamp, len(tracks_aktif), round(jarak_m, 1),
                round(durasi_s, 1), round(skor, 1), status_mentah, status_stabil
            ])
            log_sensor_reading([
                timestamp, sensor_mpu['status_mesin'], sensor_mpu['status_idle'],
                sensor_mpu['durasi_idle_s'], sensor_mpu['getaran_g'],
                int(sw420_terdeteksi), gps_lokasi['fix'], gps_lokasi['lat'],
                gps_lokasi['lon'], sensor_mpu['tilt_x_deg'], sensor_mpu['tilt_y_deg'],
                sensor_mpu['tilt_status']
            ])
            key = safe_imshow("Blind Spot Detector - Camera", frame)
            if key == ord('q'):
                break

            throttle.tunggu_sisa_waktu()

    except KeyboardInterrupt:
        print("\nDihentikan oleh pengguna.")
    finally:
        if can_use_gui():
            cv2.destroyAllWindows()
        buzzer.off(); led_hijau.off(); led_kuning.off(); led_merah.off()
        if mpu6050 is not None:
            mpu6050.close()
        if sw420 is not None:
            sw420.close()
        if gps is not None:
            gps.close()
        cap.release()
        print("Semua output dimatikan. Log tersimpan di", LOG_FILE)


if __name__ == '__main__':
    main()
