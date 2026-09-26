"""
dashboard.py
Server web dashboard AWAS -- v2, sekarang dengan panel TAMBAHAN untuk
status mesin/idle/GPS (dari mpu6050_sensor.py, vibration_sw420.py,
gps_neo6m.py), SENGAJA terpisah dari panel status blind spot yang besar.

Kenapa terpisah: status blind spot itu alarm keselamatan (prioritas
tertinggi), status idle/GPS itu informasi hemat BBM/lokasi (kelas
urgensi jauh berbeda). Digabung jadi satu bisa membuat operator
kehilangan sensitivitas ke alarm yang benar-benar penting.

Status sensor tambahan diisi oleh main.py tanpa menjadi syarat kritis
untuk jalur alarm blind spot.

Akses dari browser laptop: http://<ip-raspberry-pi>:5000
"""

import csv
import os
import threading
import time

import cv2
from flask import Flask, Response, jsonify, render_template

_DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=_DASHBOARD_DIR,
    static_folder=_DASHBOARD_DIR,
    static_url_path="/static",
)


class SharedState:
    """Jembatan data antara loop utama (main.py) dan server web ini."""

    def __init__(self):
        self.lock = threading.Lock()

        # -- Status blind spot (sudah ada sejak awal) --
        self.frame_jpeg = None
        self.status = "aman"
        self.jarak_m = 15.0
        self.durasi_s = 0.0
        self.skor = 0.0
        self.jumlah_orang = 0
        self.last_update = None
        self.events = []  # riwayat perubahan status blind spot, maks 15

        # -- Status mesin/idle/GPS (BARU) -- default "belum ada data"
        # sampai main.py benar-benar memanggil update_sensor_tambahan()
        self.status_mesin = None
        self.status_idle = None
        self.durasi_idle_s = 0
        self.getaran_g = 0.0
        self.tilt_x_deg = 0.0
        self.tilt_y_deg = 0.0
        self.tilt_status = "NORMAL"
        self.gps_fix = 0
        self.gps_lat = 0.0
        self.gps_lon = 0.0
        self.gps_status = "GPS BELUM DICEK"
        self.gps_uart_status = "BELUM DICEK"
        self.gps_nmea_received = False
        self.gps_nmea_sentence_count = 0
        self.gps_gga_received = False
        self.gps_rmc_received = False
        self.gps_satellites = None
        self.gps_last_sentence_time = None
        self.sensor_last_update = None
        self.operator_message = "Sistem siap — menunggu operator menekan start"
        self.start_requested = False
        self.startup_checks = []
        self.history = []

    def update_frame(self, frame_bgr):
        ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            with self.lock:
                self.frame_jpeg = buf.tobytes()

    def update_status(self, status, jarak_m, durasi_s, skor, jumlah_orang):
        """Status BLIND SPOT saja -- lihat update_sensor_tambahan() untuk
        status mesin/idle/GPS, sengaja dipisah jadi dua method berbeda."""
        with self.lock:
            status_berubah = status != self.status
            self.status = status
            self.jarak_m = jarak_m
            self.durasi_s = durasi_s
            self.skor = skor
            self.jumlah_orang = jumlah_orang
            self.last_update = time.strftime("%H:%M:%S")
            if status_berubah:
                self.events.insert(0, {"waktu": self.last_update, "status": status})
                self.events = self.events[:15]

    def update_sensor_tambahan(self, status_mesin, status_idle, durasi_idle_s,
                                getaran_g, gps_fix, gps_lat, gps_lon,
                                tilt_x_deg=0.0, tilt_y_deg=0.0, tilt_status="NORMAL",
                                gps_status="GPS BELUM DICEK", gps_uart_status="BELUM DICEK",
                                gps_nmea_received=False, gps_nmea_sentence_count=0,
                                gps_gga_received=False, gps_rmc_received=False,
                                gps_satellites=None, gps_last_sentence_time=None):
        """Status mesin/idle/getaran/kemiringan/GPS -- terpisah total dari
        update_status() di atas, tidak memicu/mengubah events blind spot."""
        with self.lock:
            self.status_mesin = status_mesin
            self.status_idle = status_idle
            self.durasi_idle_s = durasi_idle_s
            self.getaran_g = getaran_g
            self.tilt_x_deg = tilt_x_deg
            self.tilt_y_deg = tilt_y_deg
            self.tilt_status = tilt_status
            self.gps_fix = gps_fix
            self.gps_lat = gps_lat
            self.gps_lon = gps_lon
            self.gps_status = gps_status
            self.gps_uart_status = gps_uart_status
            self.gps_nmea_received = gps_nmea_received
            self.gps_nmea_sentence_count = gps_nmea_sentence_count
            self.gps_gga_received = gps_gga_received
            self.gps_rmc_received = gps_rmc_received
            self.gps_satellites = gps_satellites
            self.gps_last_sentence_time = gps_last_sentence_time
            self.sensor_last_update = time.strftime("%H:%M:%S")

    def set_operator_notice(self, message):
        with self.lock:
            self.operator_message = message

    def request_start(self):
        with self.lock:
            self.start_requested = True
            self.operator_message = "Permintaan mulai diterima — menunggu sistem"

    def consume_start_request(self):
        with self.lock:
            requested = self.start_requested
            self.start_requested = False
            return requested

    def update_startup_checks(self, checks):
        with self.lock:
            self.startup_checks = list(checks)

    def update_history(self, history_list):
        with self.lock:
            self.history = list(history_list)

    def snapshot(self):
        with self.lock:
            return {
                "status": self.status,
                "jarak_m": round(self.jarak_m, 1),
                "durasi_s": round(self.durasi_s, 1),
                "skor": round(self.skor, 1),
                "jumlah_orang": self.jumlah_orang,
                "last_update": self.last_update,
                "events": list(self.events),
                "status_mesin": self.status_mesin,
                "status_idle": self.status_idle,
                "durasi_idle_s": self.durasi_idle_s,
                "getaran_g": self.getaran_g,
                "tilt_x_deg": self.tilt_x_deg,
                "tilt_y_deg": self.tilt_y_deg,
                "tilt_status": self.tilt_status,
                "gps_fix": self.gps_fix,
                "gps_lat": self.gps_lat,
                "gps_lon": self.gps_lon,
                "gps_status": self.gps_status,
                "gps_uart_status": self.gps_uart_status,
                "gps_nmea_received": self.gps_nmea_received,
                "gps_nmea_sentence_count": self.gps_nmea_sentence_count,
                "gps_gga_received": self.gps_gga_received,
                "gps_rmc_received": self.gps_rmc_received,
                "gps_satellites": self.gps_satellites,
                "gps_last_sentence_time": self.gps_last_sentence_time,
                "sensor_last_update": self.sensor_last_update,
                "operator_message": self.operator_message,
                "start_requested": self.start_requested,
                "startup_checks": list(self.startup_checks),
                "history": list(self.history),
            }


state = SharedState()


def read_recent_history(log_path, sensor_log_path=None, limit=8):
    items = []
    sensor_by_timestamp = {}
    if sensor_log_path and os.path.exists(sensor_log_path):
        try:
            with open(sensor_log_path, newline='') as handle:
                for row in csv.DictReader(handle):
                    sensor_by_timestamp[row.get("timestamp")] = row
        except Exception:
            sensor_by_timestamp = {}
    if not os.path.exists(log_path):
        return items
    try:
        with open(log_path, newline='') as handle:
            reader = csv.reader(handle)
            rows = list(reader)
        if len(rows) <= 1:
            return items
        for row in rows[-limit:]:
            if len(row) < 7:
                continue
            timestamp, jumlah_orang, jarak_m, durasi_s, skor, status_mentah, status_stabil = row[:7]
            items.append({
                "timestamp": timestamp,
                "jumlah_orang": jumlah_orang,
                "jarak_m": jarak_m,
                "durasi_s": durasi_s,
                "skor": skor,
                "status_mentah": status_mentah,
                "status_stabil": status_stabil,
                "status_mesin": sensor_by_timestamp.get(timestamp, {}).get("status_mesin"),
                "status_idle": sensor_by_timestamp.get(timestamp, {}).get("status_idle"),
                "durasi_idle_s": sensor_by_timestamp.get(timestamp, {}).get("durasi_idle_s"),
                "getaran_g": sensor_by_timestamp.get(timestamp, {}).get("getaran_g"),
                "sw420_terdeteksi": sensor_by_timestamp.get(timestamp, {}).get("sw420_terdeteksi"),
                "tilt_x_deg": sensor_by_timestamp.get(timestamp, {}).get("tilt_x_deg"),
                "tilt_y_deg": sensor_by_timestamp.get(timestamp, {}).get("tilt_y_deg"),
                "tilt_status": sensor_by_timestamp.get(timestamp, {}).get("tilt_status"),
                "gps_fix": sensor_by_timestamp.get(timestamp, {}).get("gps_fix"),
                "gps_lat": sensor_by_timestamp.get(timestamp, {}).get("gps_lat"),
                "gps_lon": sensor_by_timestamp.get(timestamp, {}).get("gps_lon"),
            })
    except Exception:
        return items
    return items


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/video_feed")
def video_feed():
    def generate():
        while True:
            with state.lock:
                frame = state.frame_jpeg
            if frame is not None:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
            time.sleep(0.05)
    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/status")
def status_endpoint():
    root_dir = os.path.dirname(_DASHBOARD_DIR)
    history = read_recent_history(
        os.path.join(root_dir, "log_blindspot.csv"),
        os.path.join(root_dir, "log_sensor_tambahan.csv"),
        limit=8,
    )
    state.update_history(history)
    return jsonify(state.snapshot())


@app.route("/start", methods=["POST"])
def request_start():
    state.request_start()
    return jsonify({"ok": True, "message": "Permintaan mulai diterima"})


def start_dashboard_server(host="0.0.0.0", port=5000):
    thread = threading.Thread(
        target=lambda: app.run(host=host, port=port, threaded=True, debug=False),
        daemon=True,
    )
    thread.start()
    return thread
