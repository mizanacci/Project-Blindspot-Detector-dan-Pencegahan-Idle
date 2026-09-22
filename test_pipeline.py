import time
import cv2
import json

from vision import PersonDetector
from tracker import SimpleTracker
from fuzzy_engine import evaluate_urgency, StatusStabilizer


ZONE_CONFIG_FILE = "zone_config.json"


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


def main():

    print("=" * 70)
    print(" TEST PIPELINE: YOLO -> TRACKING -> JARAK -> FUZZY")
    print("=" * 70)

    cfg = load_zone_config()

    print("\nKalibrasi jarak:")

    for point in cfg["calibration_points"]:
        print(
            f"  y2={point['y2']:.2f} px"
            f" -> {point['distance_m']:.2f} m"
        )

    print("\n1. Memuat YOLO NCNN...")
    detector = PersonDetector()

    print("2. Membuat tracker...")
    tracker = SimpleTracker()

    print("3. Membuat fuzzy stabilizer...")
    stabilizer = StatusStabilizer()

    print("4. Membuka kamera...")

    cap = cv2.VideoCapture(
        "/dev/video0",
        cv2.CAP_V4L2
    )

    if not cap.isOpened():
        print("GAGAL: kamera tidak dapat dibuka.")
        return

    cap.set(
        cv2.CAP_PROP_FOURCC,
        cv2.VideoWriter_fourcc(*"MJPG")
    )
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)

    print("Kamera berhasil dibuka.")
    print("\nTekan Ctrl+C untuk menghentikan pengujian.")
    print("=" * 70)

    frame_count = 0
    last_print = 0

    try:

        while True:

            ret, frame = cap.read()

            if not ret:
                print("Gagal membaca frame.")
                continue

            frame_count += 1

            # YOLO
            orang = detector.detect_people(frame)

            # Tracking
            tracks = tracker.update(orang)

            # Fuzzy
            hasil_track = []

            for tr in tracks:

                jarak_m = estimate_distance(
                    tr["y2"],
                    cfg
                )

                skor, status = evaluate_urgency(
                    jarak_m,
                    tr["durasi_s"]
                )

                hasil_track.append({
                    "id": tr["id"],
                    "y2": tr["y2"],
                    "durasi": tr["durasi_s"],
                    "jarak": jarak_m,
                    "skor": skor,
                    "status": status
                })

            # Cari orang dengan risiko tertinggi
            if hasil_track:

                terparah = max(
                    hasil_track,
                    key=lambda x: x["skor"]
                )

                status_mentah = terparah["status"]

                status_stabil = stabilizer.update(
                    status_mentah
                )

            else:

                status_mentah = "aman"
                status_stabil = stabilizer.update(
                    "aman"
                )

            # Print setiap ~0.5 detik
            now = time.time()

            if now - last_print >= 0.5:

                print(
                    f"\nFrame={frame_count}"
                    f" | orang={len(hasil_track)}"
                    f" | RAW={status_mentah.upper()}"
                    f" | STABIL={status_stabil.upper()}"
                )

                for p in hasil_track:

                    print(
                        f"  ID={p['id']}"
                        f" | y2={p['y2']:.0f}px"
                        f" | jarak={p['jarak']:.2f}m"
                        f" | durasi={p['durasi']:.1f}s"
                        f" | skor={p['skor']:.1f}"
                        f" | fuzzy={p['status'].upper()}"
                    )

                last_print = now

    except KeyboardInterrupt:

        print("\n\nPengujian dihentikan.")

    finally:

        cap.release()

        print("\nKamera dilepas.")
        print("Test pipeline selesai.")


if __name__ == "__main__":
    main()