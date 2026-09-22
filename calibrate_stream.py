"""
calibrate_stream.py

Program kalibrasi estimasi jarak berbasis posisi vertikal bounding box (y2).

Fungsi:
- Menampilkan live stream kamera DV20.
- Menjalankan YOLOv8n NCNN.
- Hanya mendeteksi class "person".
- Menampilkan bounding box.
- Menampilkan confidence.
- Menampilkan nilai y2.
- Memasukkan jarak aktual melalui keyboard.
- Menyimpan sampel kalibrasi ke CSV.
- Tidak mengubah zone_config.json.

Kontrol keyboard:
    0-9     : memasukkan angka jarak
    .       : desimal
    Backspace : hapus karakter
    Enter   : simpan sampel
    C       : hapus input jarak
    Q       : keluar

Contoh:
    Ketik 5.0 lalu Enter
    -> semua person yang sedang terdeteksi disimpan sebagai sampel
       dengan jarak aktual 5.0 meter.

CSV:
    calibration_samples.csv
"""

import cv2
import csv
import os
import time
from datetime import datetime

from vision import PersonDetector


# ============================================================
# KONFIGURASI
# ============================================================

CAMERA = "/dev/video0"

FRAME_WIDTH = 640
FRAME_HEIGHT = 480
FRAME_FPS = 30

MODEL_PATH = "yolov8n_ncnn_model"

CONFIDENCE = 0.5

CSV_FILE = "calibration_samples.csv"


# ============================================================
# CSV
# ============================================================

def setup_csv():
    """
    Membuat file CSV jika belum ada.
    """

    if not os.path.exists(CSV_FILE):

        with open(
            CSV_FILE,
            "w",
            newline=""
        ) as f:

            writer = csv.writer(f)

            writer.writerow([
                "timestamp",
                "jarak_aktual_m",
                "person_index",
                "x1",
                "y1",
                "x2",
                "y2",
                "confidence"
            ])


def save_samples(jarak_aktual, people):
    """
    Menyimpan semua person yang sedang terdeteksi
    pada frame saat tombol Enter ditekan.
    """

    if not people:
        return 0

    timestamp = datetime.now().isoformat(
        timespec="milliseconds"
    )

    with open(
        CSV_FILE,
        "a",
        newline=""
    ) as f:

        writer = csv.writer(f)

        for index, person in enumerate(people, start=1):

            writer.writerow([
                timestamp,
                jarak_aktual,
                index,
                round(person["x1"], 2),
                round(person["y1"], 2),
                round(person["x2"], 2),
                round(person["y2"], 2),
                round(person["conf"], 4)
            ])

    return len(people)


# ============================================================
# KAMERA
# ============================================================

def buka_kamera():

    print("Membuka kamera...")
    print(f"Device : {CAMERA}")
    print(f"Format : MJPG {FRAME_WIDTH}x{FRAME_HEIGHT} @ {FRAME_FPS} FPS")

    cap = cv2.VideoCapture(
        CAMERA,
        cv2.CAP_V4L2
    )

    if not cap.isOpened():

        print()
        print("ERROR: Kamera gagal dibuka.")
        print(f"Pastikan {CAMERA} tersedia.")

        return None

    # --------------------------------------------------------
    # Paksa MJPG
    # --------------------------------------------------------

    cap.set(
        cv2.CAP_PROP_FOURCC,
        cv2.VideoWriter_fourcc(*"MJPG")
    )

    cap.set(
        cv2.CAP_PROP_FRAME_WIDTH,
        FRAME_WIDTH
    )

    cap.set(
        cv2.CAP_PROP_FRAME_HEIGHT,
        FRAME_HEIGHT
    )

    cap.set(
        cv2.CAP_PROP_FPS,
        FRAME_FPS
    )

    # --------------------------------------------------------
    # Tampilkan konfigurasi aktual
    # --------------------------------------------------------

    width = int(
        cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    )

    height = int(
        cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    )

    fps = cap.get(
        cv2.CAP_PROP_FPS
    )

    print()
    print("Kamera berhasil dibuka.")
    print(
        f"Actual format: {width}x{height} @ {fps:.1f} FPS"
    )

    return cap


# ============================================================
# DRAW UI
# ============================================================

def draw_person(frame, person, index):

    x1 = int(person["x1"])
    y1 = int(person["y1"])

    x2 = int(person["x2"])
    y2 = int(person["y2"])

    conf = person["conf"]

    # --------------------------------------------------------
    # Bounding box
    # --------------------------------------------------------

    cv2.rectangle(
        frame,
        (x1, y1),
        (x2, y2),
        (0, 255, 0),
        2
    )

    # --------------------------------------------------------
    # Titik y2
    # --------------------------------------------------------

    cv2.circle(
        frame,
        (int((x1 + x2) / 2), y2),
        5,
        (0, 0, 255),
        -1
    )

    # --------------------------------------------------------
    # Label
    # --------------------------------------------------------

    label = (
        f"Person {index} | "
        f"conf={conf:.2f} | "
        f"y2={y2}px"
    )

    label_y = max(
        20,
        y1 - 10
    )

    cv2.putText(
        frame,
        label,
        (x1, label_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (0, 255, 0),
        1,
        cv2.LINE_AA
    )

    # --------------------------------------------------------
    # Garis horizontal pada y2
    # --------------------------------------------------------

    cv2.line(
        frame,
        (0, y2),
        (frame.shape[1] - 1, y2),
        (0, 0, 255),
        1
    )

    cv2.putText(
        frame,
        f"y2 = {y2}",
        (10, max(20, y2 - 5)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (0, 0, 255),
        1,
        cv2.LINE_AA
    )


# ============================================================
# DRAW STATUS
# ============================================================

def draw_interface(
    frame,
    distance_input,
    people_count,
    message,
    fps
):

    height, width = frame.shape[:2]

    # --------------------------------------------------------
    # Panel atas
    # --------------------------------------------------------

    cv2.rectangle(
        frame,
        (0, 0),
        (width, 75),
        (0, 0, 0),
        -1
    )

    # --------------------------------------------------------
    # Jarak input
    # --------------------------------------------------------

    cv2.putText(
        frame,
        f"Jarak aktual: {distance_input} m",
        (10, 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2,
        cv2.LINE_AA
    )

    # --------------------------------------------------------
    # Jumlah person
    # --------------------------------------------------------

    cv2.putText(
        frame,
        f"Person: {people_count}",
        (10, 52),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        1,
        cv2.LINE_AA
    )

    # --------------------------------------------------------
    # FPS
    # --------------------------------------------------------

    fps_text = f"FPS: {fps:.1f}"

    cv2.putText(
        frame,
        fps_text,
        (width - 110, 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        1,
        cv2.LINE_AA
    )

    # --------------------------------------------------------
    # Instruksi
    # --------------------------------------------------------

    instruction = (
        "Ketik jarak -> ENTER simpan | "
        "C=clear | Q=quit"
    )

    cv2.putText(
        frame,
        instruction,
        (width - 390, 52),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.38,
        (255, 255, 255),
        1,
        cv2.LINE_AA
    )

    # --------------------------------------------------------
    # Message
    # --------------------------------------------------------

    if message:

        cv2.rectangle(
            frame,
            (0, height - 45),
            (width, height),
            (0, 0, 0),
            -1
        )

        cv2.putText(
            frame,
            message,
            (10, height - 15),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 255),
            2,
            cv2.LINE_AA
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 60)
    print(" KALIBRASI YOLO + LIVE STREAM")
    print("=" * 60)
    print()

    # --------------------------------------------------------
    # CSV
    # --------------------------------------------------------

    setup_csv()

    print(f"CSV output: {CSV_FILE}")

    # --------------------------------------------------------
    # YOLO
    # --------------------------------------------------------

    print()
    print("Memuat YOLO NCNN...")

    detector = PersonDetector(
        model_path=MODEL_PATH,
        confidence=CONFIDENCE,
        perbaiki_cahaya=True
    )

    # --------------------------------------------------------
    # Kamera
    # --------------------------------------------------------

    cap = buka_kamera()

    if cap is None:
        return

    # --------------------------------------------------------
    # Window
    # --------------------------------------------------------

    window_name = "Kalibrasi YOLO - DV20"

    cv2.namedWindow(
        window_name,
        cv2.WINDOW_NORMAL
    )

    cv2.resizeWindow(
        window_name,
        960,
        720
    )

    # --------------------------------------------------------
    # Input jarak
    # --------------------------------------------------------

    distance_input = ""

    # --------------------------------------------------------
    # Status
    # --------------------------------------------------------

    message = (
        "Masukkan jarak aktual, contoh: 5.0"
    )

    message_until = time.time() + 5

    # --------------------------------------------------------
    # FPS
    # --------------------------------------------------------

    fps = 0.0
    fps_counter = 0
    fps_start = time.time()

    # --------------------------------------------------------
    # Frame
    # --------------------------------------------------------

    frame_number = 0

    print()
    print("Kontrol:")
    print("  angka 0-9 : input jarak")
    print("  .         : desimal")
    print("  Backspace : hapus input")
    print("  Enter     : simpan sampel")
    print("  C         : clear input")
    print("  Q         : keluar")
    print()

    try:

        while True:

            # =================================================
            # CAPTURE
            # =================================================

            ret, frame = cap.read()

            if not ret:

                print(
                    "Gagal membaca frame kamera."
                )

                time.sleep(0.1)

                continue

            frame_number += 1

            # =================================================
            # FPS
            # =================================================

            fps_counter += 1

            elapsed = (
                time.time() - fps_start
            )

            if elapsed >= 1.0:

                fps = (
                    fps_counter / elapsed
                )

                fps_counter = 0
                fps_start = time.time()

            # =================================================
            # YOLO
            # =================================================

            people = detector.detect_people(
                frame
            )

            # =================================================
            # DRAW DETECTIONS
            # =================================================

            display = frame.copy()

            for index, person in enumerate(
                people,
                start=1
            ):

                draw_person(
                    display,
                    person,
                    index
                )

            # =================================================
            # MESSAGE TIMEOUT
            # =================================================

            current_message = ""

            if time.time() < message_until:

                current_message = message

            # =================================================
            # DRAW INTERFACE
            # =================================================

            draw_interface(
                display,
                distance_input,
                len(people),
                current_message,
                fps
            )

            # =================================================
            # DISPLAY
            # =================================================

            cv2.imshow(
                window_name,
                display
            )

            # =================================================
            # KEYBOARD
            # =================================================

            key = cv2.waitKey(1) & 0xFF

            # -------------------------------------------------
            # Q = QUIT
            # -------------------------------------------------

            if key in (
                ord("q"),
                ord("Q")
            ):

                break

            # -------------------------------------------------
            # C = CLEAR INPUT
            # -------------------------------------------------

            elif key in (
                ord("c"),
                ord("C")
            ):

                distance_input = ""

                message = (
                    "Input jarak dihapus."
                )

                message_until = (
                    time.time() + 2
                )

            # -------------------------------------------------
            # BACKSPACE
            # -------------------------------------------------

            elif key == 8:

                distance_input = (
                    distance_input[:-1]
                )

            # -------------------------------------------------
            # ENTER
            # -------------------------------------------------

            elif key in (
                10,
                13
            ):

                if not distance_input:

                    message = (
                        "Masukkan jarak terlebih dahulu."
                    )

                    message_until = (
                        time.time() + 3
                    )

                    continue

                try:

                    jarak = float(
                        distance_input
                    )

                except ValueError:

                    message = (
                        "Input jarak tidak valid."
                    )

                    message_until = (
                        time.time() + 3
                    )

                    continue

                if jarak <= 0:

                    message = (
                        "Jarak harus lebih besar dari 0."
                    )

                    message_until = (
                        time.time() + 3
                    )

                    continue

                if not people:

                    message = (
                        "Tidak ada person terdeteksi. "
                        "Sampel tidak disimpan."
                    )

                    message_until = (
                        time.time() + 3
                    )

                    continue

                # ---------------------------------------------
                # SAVE
                # ---------------------------------------------

                jumlah_disimpan = save_samples(
                    jarak,
                    people
                )

                message = (
                    f"TERSIMPAN: {jumlah_disimpan} "
                    f"person @ {jarak:.2f} m"
                )

                message_until = (
                    time.time() + 4
                )

                print(
                    f"[CALIBRATION] "
                    f"jarak={jarak:.2f} m | "
                    f"person={jumlah_disimpan}"
                )

                for index, person in enumerate(
                    people,
                    start=1
                ):

                    print(
                        f"  Person {index}: "
                        f"y2={person['y2']:.1f}px | "
                        f"conf={person['conf']:.3f}"
                    )

                # ---------------------------------------------
                # CLEAR INPUT
                # ---------------------------------------------

                distance_input = ""

            # -------------------------------------------------
            # ANGKA
            # -------------------------------------------------

            elif (
                ord("0") <= key <= ord("9")
            ):

                distance_input += chr(key)

            # -------------------------------------------------
            # DESIMAL
            # -------------------------------------------------

            elif key == ord("."):

                if "." not in distance_input:

                    if not distance_input:

                        distance_input = "0."

                    else:

                        distance_input += "."

    except KeyboardInterrupt:

        print()
        print(
            "Program dihentikan oleh pengguna."
        )

    finally:

        cap.release()

        cv2.destroyAllWindows()

        print()
        print("=" * 60)
        print("KALIBRASI SELESAI")
        print("=" * 60)
        print()
        print(
            f"Data tersimpan di: {CSV_FILE}"
        )
        print()


if __name__ == "__main__":
    main()
