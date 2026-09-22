# WORKSPACE CONTEXT: AWAS Blind Spot Detector

Status dokumen: dibuat 2026-09-22. Ini adalah konteks teknis untuk AI lain, bukan dokumentasi operasional manusia.

## 0. Aturan pemeliharaan konteks

- Source of truth adalah source code aktif, `zone_config.json`, dan `requirements.txt`; jangan mengandalkan backup atau komentar lama jika berbeda.
- Setiap perubahan signifikan pada `main.py`, `vision.py`, `tracker.py`, `fuzzy_engine.py`, sensor, dashboard, model, wiring, atau konfigurasi zona harus memperbarui dokumen ini.
- Jangan menyalin isi `*.csv`, `*.log`, model YOLO, `venv/`, atau `__pycache__/`; hanya rujuk nama/path-nya.

## 1. Struktur file

### Root

- `main.py`: Runtime utama kamera -> YOLO -> tracker -> jarak -> fuzzy -> stabilizer -> GPIO alarm; membaca tiga sensor; logging; mengirim data ke dashboard.
- `vision.py`: CLAHE optional dan `PersonDetector` berbasis Ultralytics YOLO NCNN; hanya class person.
- `tracker.py`: `SimpleTracker`, pencocokan centroid multi-orang, ID track, durasi terlihat, dan timeout track hilang.
- `fuzzy_engine.py`: Fuzzy Mamdani untuk skor urgensi jarak/durasi dan `StatusStabilizer` anti-flicker.
- `calibrate_stream.py`: Kalibrasi interaktif kamera/YOLO; menyimpan sampel jarak dan bounding box ke `calibration_samples.csv`; tidak menulis `zone_config.json`.
- `calibrate_zone.py`: Skrip kalibrasi zona lama berbasis tiga titik; saat ini menulis format `y_waspada`/`y_bahaya`, tidak kompatibel dengan format `zone_config.json` yang dipakai `main.py`.
- `analyze_calibration.py`: Membaca `calibration_samples.csv`, menguji interpolasi linear, menghitung RMSE, dan mencetak prediksi antar titik.
- `camera_preview.py`: Preview kamera V4L2 640x480 MJPG dan penghitung FPS; bukan bagian pipeline utama.
- `test_distance_8point.py`: Test/manual runner kamera + YOLO + tracker + interpolasi dari CSV kalibrasi; bukan pipeline alarm utama.
- `test_pipeline.py`: Test/manual runner kamera + YOLO + tracker + interpolasi + fuzzy + stabilizer; tidak mengendalikan GPIO atau dashboard.
- `nano calibrate_stream.py`: File bernama tidak normal dan bukan source runtime; berisi salinan/fence Markdown dari skrip kalibrasi dan jangan diimpor.
- `requirements.txt`: Dependensi Python runtime dan tooling yang dideklarasikan.
- `zone_config.json`: Konfigurasi kalibrasi jarak aktif untuk `main.py`.
- `calibration_samples.csv`: Data sampel kalibrasi; tidak dirangkum di sini.
- `log_blindspot.csv`: Log runtime blind spot; tidak dirangkum di sini.
- `log_sensor_tambahan.csv`: Log runtime sensor tambahan; dibuat oleh `main.py`; tidak dirangkum di sini.
- `yolov8n.pt`, `yolo11n.pt`: Model PyTorch tersedia, tetapi bukan model yang dipakai jalur runtime aktif.
- `yolov8n_ncnn_model/metadata.yaml`: Metadata model NCNN.
- `yolov8n_ncnn_model/model.ncnn.param`: Parameter model NCNN aktif.
- `yolov8n_ncnn_model/model.ncnn.bin`: Bobot model NCNN aktif; file besar, tidak disalin ke dokumen.
- `yolov8n_ncnn_model/model_ncnn.py`: Smoke test langsung NCNN dengan input tensor acak; bukan jalur `PersonDetector` utama.

### `File pengembangan dari Claude AI/`

- `dashboard.py`: Flask server, `SharedState`, endpoint HTML/video/status, dan thread server dashboard.
- `dashboard.html`: UI dashboard AWAS: live camera, status blind spot, metrik, sensor mesin/idle/GPS, riwayat.
- `dashboard.css`: Styling dashboard HMI industrial dan layout responsif; saat ini belum diverifikasi visual pada LCD 800x480.
- `dashboard.js`: Polling `/status` setiap 500 ms dan render status, metrik, sensor, GPS, serta event.
- `mpu6050_sensor.py`: Pembacaan MPU6050 via I2C burst dan klasifikasi mesin mati/ON/idle.
- `vibration_sw420.py`: Pembacaan sensor getaran digital SW-420 via GPIO dan deteksi transisi.
- `gps_neo6m.py`: Pembacaan NMEA dari GPS NEO-6M via serial dan ekstraksi fix GGA/RMC.
- `throttle_pattern.py`: Implementasi `LoopThrottle`; dipakai `main.py` untuk target satu siklus per 1.0 detik.
- `README.md`: Catatan pengembangan sensor langsung di Pi, wiring, dependensi, dan keterbatasan hardware.

### Backup/arsip

- `main.py.backup_before_8point`, `main.py.backup_before_gpio_test`, `main.py.backup_before_vnc_preview`: backup historis; bukan source aktif.
- `fuzzy_engine.py.backup_before_rule_adjustment`: backup aturan fuzzy lama; bukan source aktif.
- `test_pipeline.py.backup_before_8point`: backup test lama; bukan source aktif.
- `zone_config.json.backup_before_8point`: backup konfigurasi lama; bukan konfigurasi aktif.

## 2. Pipeline aktif aktual di `main.py`

Urutan yang benar-benar dijalankan:

1. `main()` memanggil `start_dashboard_server()` sekali; server Flask berjalan pada thread daemon.
2. `zone_config.json` dibaca.
3. `PersonDetector`, `SimpleTracker`, `StatusStabilizer`, dan `LoopThrottle(interval_s=1.0)` dibuat.
4. MPU6050, SW-420 GPIO17, dan GPS `/dev/serial0` diinisialisasi masing-masing dalam `try/except`; jika gagal, objek menjadi `None` dan loop memakai fallback.
5. Kamera `/dev/video0` dibuka via V4L2, dipaksa MJPG 640x480 dan FPS request 10. Jika kamera gagal dibuka, `main()` return.
6. Buzzer GPIO22 dan LED GPIO23/24/25 dibuat.
7. CSV blind spot dan CSV sensor tambahan disiapkan.
8. Loop dimulai: `throttle.mulai_siklus()`.
9. Satu frame kamera dibaca. Jika gagal, tunggu sisa interval dan ulangi.
10. `FRAME_SKIP=1`, sehingga setiap frame yang berhasil dibaca diproses oleh `detector.detect_people(frame)`.
11. `PersonDetector` optional CLAHE, lalu YOLO NCNN mendeteksi class person dengan confidence minimum 0.5 dan `imgsz=640`.
12. `SimpleTracker.update()` mencocokkan semua deteksi, mempertahankan track sampai timeout, dan menghitung durasi track.
13. `urgensi_paling_parah()` mengestimasi jarak tiap track dari `y2`, mengevaluasi fuzzy tiap track, lalu memilih skor tertinggi. Jika tidak ada track: 15.0 m, 0.0 s, skor 0.0, `aman`.
14. `StatusStabilizer.update(status_mentah)` menghasilkan `status_stabil`.
15. Sensor dibaca: `mpu6050.baca_status()`, `sw420.baca_terdeteksi()`, dan `gps.baca_lokasi()`. Kegagalan sensor memakai fallback eksplisit.
16. `set_output(status_stabil, ...)` mematikan semua output lalu menyalakan output status yang sesuai; `bahaya` juga menyalakan buzzer.
17. Dashboard menerima frame lewat `state.update_frame(frame)`, data blind spot lewat `state.update_status(...)`, dan data sensor lewat `state.update_sensor_tambahan(...)`.
18. Hasil dicetak ke stdout dan ditulis ke `log_blindspot.csv` serta `log_sensor_tambahan.csv`.
19. Frame ditampilkan dengan `cv2.imshow`; tombol `q` menghentikan loop.
20. `throttle.tunggu_sisa_waktu()` menjaga target interval 1.0 detik jika pekerjaan siklus lebih cepat.
21. Pada `KeyboardInterrupt`, output GPIO dimatikan, sensor ditutup, kamera dilepas, dan fungsi selesai.

Dashboard hanya membaca hasil yang sudah dihitung; dashboard tidak memengaruhi `set_output()`.

## 3. Konstanta penting persis dari source aktif

### Kamera/model/deteksi

- Kamera utama: `"/dev/video0"`, backend `cv2.CAP_V4L2`.
- Format utama `main.py`: MJPG, width `640`, height `480`, FPS request `10`.
- `FRAME_SKIP = 1`.
- Model default: `"yolov8n_ncnn_model"`.
- `PERSON_CLASS_ID = 0`.
- YOLO confidence: `0.5`.
- YOLO `imgsz=640`.
- CLAHE: `clipLimit=2.5`, `tileGridSize=(8, 8)`.
- Jarak interpolasi internal di-clamp `0.5` sampai `15.0` meter.
- Jika `calibration_points` kosong, fallback jarak `15.0` meter.

### GPIO dan output alarm

Penomoran GPIO adalah BCM:

- `BUZZER_PIN = 22`: buzzer; aktif hanya saat status `bahaya`.
- `LED_HIJAU_PIN = 23`: status `aman`.
- `LED_KUNING_PIN = 24`: status `siaga`.
- `LED_MERAH_PIN = 25`: status selain `aman`/`siaga`, terutama `bahaya`.
- `SW420Sensor(pin=17)`: input digital SW-420; tidak boleh memakai GPIO alarm.
- `set_output()`: selalu `off()` semua LED dan buzzer lebih dulu, lalu menyalakan output status.

### Fuzzy logic dan stabilizer

- Universe jarak: `np.arange(0, 15.01, 0.1)`.
- Membership jarak `dekat`: `trapmf([0, 0, 2, 4])`.
- Membership jarak `sedang`: `trimf([2, 5, 8])`.
- Membership jarak `jauh`: `trapmf([5, 8, 15, 15])`.
- Universe durasi: `np.arange(0, 30.01, 0.5)`.
- Membership durasi `sebentar`: `trapmf([0, 0, 3, 8])`.
- Membership durasi `lama`: `trapmf([5, 10, 30, 30])`.
- Universe urgensi: `np.arange(0, 100.01, 1)`.
- Membership urgensi `aman`: `trapmf([0, 0, 20, 40])`.
- Membership urgensi `siaga`: `trimf([25, 50, 75])`.
- Membership urgensi `bahaya`: `trapmf([60, 80, 100, 100])`.
- Input fuzzy di-clamp ke jarak `0.0..15.0` dan durasi `0.0..30.0`.
- Label hasil: skor `< 33` = `aman`; skor `>= 33` dan `< 66` = `siaga`; skor `>= 66` = `bahaya`.
- `StatusStabilizer(ambang_naik=2, ambang_turun=3)`; status naik perlu 2 update berturut-turut, status turun perlu 3.
- Urutan tingkat: `['aman', 'siaga', 'bahaya']`.

### Throttle

- `LoopThrottle(interval_s=1.0)`.
- `tunggu_sisa_waktu()` tidur hanya jika sisa interval positif; jika pekerjaan lebih lama dari 1.0 detik, tidak menambah delay.

### MPU6050

- I2C bus default: `bus_num=1`.
- I2C address: `MPU_ADDR = 0x68`.
- Power register: `PWR_MGMT_1 = 0x6B`; accelerometer register: `ACCEL_XOUT_H = 0x3B`.
- Burst default: `durasi_burst_s=0.2`.
- Konversi accelerometer: pembagi `16384.0`.
- `AMBANG_MESIN_MATI = 0.030` g.
- `AMBANG_GERAK = 0.180` g.
- `DURASI_PERINGATAN_S = 3 * 60` detik, yaitu nilai runtime `180` detik.
- Output status mesin: `ON`, `MATI`, `TIDAK_PASTI`.
- Output idle: `AMAN`, `IDLE`, `IDLE_LAMA`.

### SW-420

- Default pin: `17`.
- Jendela baca default: `jendela_s=0.3` detik.
- Polling transisi: `time.sleep(0.005)`.
- Nilai magnitude g tidak berasal dari SW-420; magnitude `getaran_g` berasal dari MPU6050.

### GPS NEO-6M

- Port default yang dipakai `main.py`: `"/dev/serial0"`.
- Baud rate: `9600`.
- Timeout serial default: `1.0` detik.
- Maksimum baris NMEA per baca: `maks_baris=15`.
- Sentence yang diterima untuk fix: GGA dengan `gps_qual > 0`, atau RMC dengan `status == "A"`.
- Tanpa fix: `fix=0`, `lat=0.0`, `lon=0.0`.

## 4. `zone_config.json` aktif

Format aktif adalah object dengan array `calibration_points`; tiap titik memiliki `y2` dan `distance_m`:

```json
{
  "calibration_points": [
    {"y2": 256.61, "distance_m": 9.0},
    {"y2": 266.0, "distance_m": 8.0},
    {"y2": 278.16, "distance_m": 7.0},
    {"y2": 288.0, "distance_m": 6.0},
    {"y2": 309.71, "distance_m": 5.0},
    {"y2": 332.23, "distance_m": 4.0},
    {"y2": 364.98, "distance_m": 3.0},
    {"y2": 458.62, "distance_m": 2.0}
  ]
}
```

`main.py` mengurutkan titik berdasarkan `y2`, melakukan interpolasi linear, dan memakai titik ujung di luar rentang. Semakin besar `y2`, semakin dekat jarak.

## 5. Status fitur

Status berikut harus dibaca sebagai status pada workspace ini, bukan klaim sertifikasi keselamatan.

| Fitur | Status integrasi | Status pengujian |
|---|---|---|
| YOLO NCNN person detection | Terintegrasi di `main.py` melalui `vision.py` | Pipeline/source sudah tersedia; hardware kamera nyata belum dapat diverifikasi pada sesi terakhir karena `/dev/video0` tidak tersedia di environment uji |
| CLAHE preprocessing | Terintegrasi | Teruji lewat source/import; hardware camera belum diverifikasi pada sesi terakhir |
| Multi-person `SimpleTracker` | Terintegrasi | Logic tersedia; test manual membutuhkan kamera |
| Interpolasi 8 titik | Terintegrasi dan memakai `zone_config.json` aktif | `test_distance_8point.py`/`analyze_calibration.py` tersedia; nilai RMSE pada titik kalibrasi historis disebut 0.000 m, tetapi akurasi titik baru belum dibuktikan |
| Fuzzy urgency | Terintegrasi | Logic/source dan demo tersedia; validasi hardware alarm end-to-end belum dilakukan pada sesi terakhir |
| `StatusStabilizer` | Terintegrasi | Logic tersedia; parameter 2/3 belum divalidasi sebagai waktu detik karena berbasis jumlah update |
| LED/buzzer GPIO 22/23/24/25 | Terintegrasi; alur `set_output()` tidak diganti dashboard | User menyatakan pipeline utama sudah berjalan, tetapi sesi uji terakhir tidak memiliki GPIO hardware yang valid dan gpiozero memakai fallback |
| Throttle 1 Hz | Terintegrasi di `main.py` dengan `LoopThrottle(1.0)` | Source/import lulus; pengukuran hardware nyata belum dilakukan |
| MPU6050 | Terintegrasi dengan fallback jika init gagal | Baru ditulis/diintegrasikan; belum diuji sensor fisik. Sesi terakhir gagal karena `/dev/i2c-1` tidak tersedia |
| SW-420 | Terintegrasi dengan fallback jika init gagal | Baru ditulis/diintegrasikan; belum diuji sensor fisik. Sesi terakhir gagal membuka input GPIO |
| GPS NEO-6M | Terintegrasi dengan fallback jika init gagal | Baru ditulis/diintegrasikan; belum diuji GPS fisik. Sesi terakhir gagal karena `/dev/serial0` tidak tersedia |
| Flask dashboard | Terintegrasi; `main.py` mengirim frame/status/sensor | Endpoint `/`, CSS, JS, `/status`, dan `SharedState` diuji HTTP/local; tampilan LCD 800x480 dan data deteksi nyata belum diverifikasi |
| Live `/video_feed` | Terintegrasi di dashboard | Endpoint bergantung pada frame kamera dari `main.py`; belum teruji dengan kamera hardware pada sesi terakhir |
| Logging blind spot | Terintegrasi ke `log_blindspot.csv` | Source tersedia; isi log tidak didokumentasikan di sini |
| Logging sensor | Terintegrasi ke `log_sensor_tambahan.csv` | Source tersedia; sensor fisik belum tersedia saat uji |
| Kalibrasi 8 titik lewat `calibrate_stream.py` | Pengumpulan sampel terpisah; bukan runtime utama | Membutuhkan kamera/figur/jarak nyata; belum diverifikasi ulang di sesi terakhir |
| `calibrate_zone.py` tiga titik | Ada sebagai skrip lama, tetapi tidak kompatibel dengan format aktif | Jangan gunakan untuk menimpa `zone_config.json` sebelum direvisi |
| LCD HDMI / Chromium kiosk | Belum diintegrasikan ke source | Rute yang direncanakan adalah browser Chromium ke server yang sama; belum diuji pada LCD 800x480 |
| GitHub/Claude Project integration | Tidak terkait runtime; belum diatur oleh source workspace | Proses eksternal di luar repository |

## 6. Dependensi `requirements.txt` saat ini

```text
ultralytics
opencv-python
gpiozero
flask
numpy
scikit-fuzzy
pynmea2
pyserial
smbus2
```

Runtime juga membutuhkan file model NCNN lengkap dan hardware/device yang sesuai; dependensi Python saja tidak menyediakan kamera, GPIO, I2C, atau UART.

## 7. Ketidaksesuaian dan keputusan terbuka

1. `calibrate_zone.py` masih menghasilkan format konfigurasi lama (`y_waspada`, `y_bahaya`, `jarak_waspada_m`, `jarak_bahaya_m`), sedangkan `main.py` hanya memahami `calibration_points`. Tentukan apakah skrip lama direvisi, diberi status arsip, atau tidak dipakai.
2. Komentar/docstring `dashboard.py` masih menyebut dashboard “BELUM diintegrasikan ke main.py”, padahal integrasi sudah ada. Komentar tersebut perlu diperbarui pada perubahan dashboard berikutnya.
3. Sesi terakhir berjalan sampai inisialisasi server/model tetapi berhenti karena `/dev/video0` tidak tersedia; karena itu belum ada konfirmasi end-to-end aktual untuk kamera, YOLO, tracker, dashboard bergerak, GPIO, MPU6050, SW-420, atau GPS.
4. `gpiozero` pada sesi terakhir tidak menemukan `lgpio`, `RPi`, atau `pigpio` dan memakai `NativeFactory`; backend GPIO final pada Raspberry Pi asli belum dikonfirmasi.
5. Layout dashboard dibuat untuk layar sekitar 900 px tinggi; LCD HDMI 800x480 mungkin membutuhkan tampilan ringkas khusus. Jangan mengganti tampilan laptop sebelum inspeksi fisik LCD.
6. `main.py` tetap memakai `cv2.imshow`, sehingga runtime membutuhkan GUI/display aktif. Strategi final untuk Chromium kiosk/VNC dan preview OpenCV perlu diputuskan agar tidak berebut display.
7. `start_dashboard_server()` memakai Flask development server dan port default `5000`; kebutuhan deployment service/restart policy belum diputuskan.
8. Konfigurasi GPS serial (`/dev/serial0`) dan I2C harus diverifikasi melalui konfigurasi Raspberry Pi sebelum pengujian hardware.
9. Ambang MPU6050 (`0.030`, `0.180` g) masih titik awal; harus dikalibrasi terhadap pola getaran alat berat nyata.
10. Status `SW420` dicatat ke CSV tetapi tidak dikirim ke `update_sensor_tambahan()` karena API dashboard saat ini hanya menerima `status_mesin`, `status_idle`, `durasi_idle_s`, `getaran_g`, `gps_fix`, `lat`, `lon`. Tentukan apakah sinyal SW-420 perlu ditampilkan di dashboard.
11. Tidak ada mekanisme autentikasi atau pembatasan akses pada Flask dashboard; aman hanya untuk jaringan eksperimen yang dipercaya sampai keputusan deployment dibuat.
12. `venv/`, `__pycache__/`, dan `*.pyc` harus tetap dikecualikan dari repository Git; konfigurasi `.gitignore` belum diverifikasi dalam workspace ini.
