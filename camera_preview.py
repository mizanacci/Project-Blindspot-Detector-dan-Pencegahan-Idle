import cv2
import time

CAMERA = "/dev/video0"

cap = cv2.VideoCapture(CAMERA, cv2.CAP_V4L2)

if not cap.isOpened():
    print(f"Gagal membuka kamera: {CAMERA}")
    raise SystemExit(1)

cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 30)

print("Kamera berhasil dibuka.")
print("Tekan Q untuk keluar.")

prev_time = time.time()
frame_count = 0

while True:
    ret, frame = cap.read()

    if not ret:
        print("Gagal membaca frame.")
        continue

    frame_count += 1

    current_time = time.time()

    if current_time - prev_time >= 1.0:
        fps = frame_count / (current_time - prev_time)
        frame_count = 0
        prev_time = current_time
    else:
        fps = 0

    text = f"DV20 | {frame.shape[1]}x{frame.shape[0]} | FPS: {fps:.1f}"

    cv2.putText(
        frame,
        text,
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 0),
        2
    )

    cv2.imshow("DV20 Camera Preview", frame)

    key = cv2.waitKey(1) & 0xFF

    if key == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
