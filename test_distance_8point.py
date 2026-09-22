import time
import cv2
import csv
import numpy as np

from vision import PersonDetector
from tracker import SimpleTracker


CSV_FILE = "calibration_samples.csv"


def load_calibration():
    data = []

    with open(CSV_FILE, newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            data.append({
                "y2": float(row["y2"]),
                "jarak": float(row["jarak_aktual_m"])
            })

    data.sort(key=lambda x: x["y2"])

    return data


def estimate_distance(y, data):
    ys = np.array([d["y2"] for d in data])
    ds = np.array([d["jarak"] for d in data])

    # Di luar rentang kalibrasi -> clamp
    if y <= ys[0]:
        return ds[0]

    if y >= ys[-1]:
        return ds[-1]

    # Cari dua titik yang mengapit y
    for i in range(len(ys) - 1):

        y1 = ys[i]
        y2 = ys[i + 1]

        d1 = ds[i]
        d2 = ds[i + 1]

        if y1 <= y <= y2:

            t = (y - y1) / (y2 - y1)

            return d1 + t * (d2 - d1)

    return ds[-1]


def main():

    print("=" * 70)
    print(" TEST ESTIMASI JARAK - INTERPOLASI 8 TITIK")
    print("=" * 70)

    calibration = load_calibration()

    print("\nTitik kalibrasi:")
    for d in calibration:
        print(
            f"  y2={d['y2']:7.2f} px"
            f" -> {d['jarak']:5.2f} m"
        )

    print("\nMemuat YOLO NCNN...")
    detector = PersonDetector()

    print("Membuat tracker...")
    tracker = SimpleTracker()

    print("Membuka kamera...")

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

    print("\n" + "=" * 70)
    print(" PENGUJIAN DIMULAI")
    print("=" * 70)
    print("Tekan Ctrl+C untuk menghentikan.")
    print()

    frame_count = 0
    last_print = 0

    try:

        while True:

            ret, frame = cap.read()

            if not ret:
                print("Gagal membaca frame.")
                time.sleep(0.2)
                continue

            frame_count += 1

            # Deteksi orang
            people = detector.detect_people(frame)

            # Tracking
            tracks = tracker.update(people)

            now = time.time()

            # Print setiap 0.5 detik
            if now - last_print >= 0.5:

                print("-" * 70)

                if not tracks:

                    print("Tidak ada orang terdeteksi.")

                else:

                    print(f"Jumlah orang: {len(tracks)}")

                    for tr in tracks:

                        jarak = estimate_distance(
                            tr["y2"],
                            calibration
                        )

                        print(
                            f"ID={tr['id']:2d}"
                            f" | y2={tr['y2']:7.2f} px"
                            f" | jarak={jarak:5.2f} m"
                            f" | durasi={tr['durasi_s']:5.1f} s"
                        )

                last_print = now

    except KeyboardInterrupt:

        print("\n\nPengujian dihentikan.")

    finally:

        cap.release()

        print("Kamera dilepas.")
        print("Test selesai.")


if __name__ == "__main__":
    main()
