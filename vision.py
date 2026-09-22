"""
vision.py
Deteksi orang menggunakan YOLO + NCNN.

Model NCNN digunakan agar inference dapat berjalan di Raspberry Pi 4
tanpa menggunakan PyTorch untuk proses inference.
"""

import cv2
from ultralytics import YOLO

PERSON_CLASS_ID = 0


def perbaiki_pencahayaan(frame):
    """
    Meningkatkan pencahayaan/kontras gambar menggunakan CLAHE.
    """
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)

    l, a, b = cv2.split(lab)

    clahe = cv2.createCLAHE(
        clipLimit=2.5,
        tileGridSize=(8, 8)
    )

    l = clahe.apply(l)

    lab = cv2.merge((l, a, b))

    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


class PersonDetector:

    def __init__(
        self,
        model_path="yolov8n_ncnn_model",
        confidence=0.5,
        perbaiki_cahaya=True
    ):
        print(f"Memuat model: {model_path}")

        self.model = YOLO(model_path)

        self.confidence = confidence
        self.perbaiki_cahaya = perbaiki_cahaya

        print("Model berhasil dimuat.")

    def detect_people(self, frame):

        if self.perbaiki_cahaya:
            frame = perbaiki_pencahayaan(frame)

        results = self.model.predict(
            source=frame,
            imgsz=640,
            classes=[PERSON_CLASS_ID],
            conf=self.confidence,
            verbose=False
        )

        people = []

        for box in results[0].boxes:

            x1, y1, x2, y2 = box.xyxy[0].tolist()

            conf = float(box.conf[0])

            people.append({
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "conf": conf
            })

        return people

    def draw_debug(self, frame, people):

        for p in people:

            pt1 = (
                int(p["x1"]),
                int(p["y1"])
            )

            pt2 = (
                int(p["x2"]),
                int(p["y2"])
            )

            cv2.rectangle(
                frame,
                pt1,
                pt2,
                (0, 255, 0),
                2
            )

            label = f"Person {p['conf']:.2f}"

            cv2.putText(
                frame,
                label,
                (pt1[0], pt1[1] - 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                1
            )

        return frame