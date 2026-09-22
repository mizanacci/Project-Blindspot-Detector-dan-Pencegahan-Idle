# Konteks Sistem Prototype Blind Spot Detector Raspberry Pi 4

Dokumen ini adalah konteks teknis untuk Claude AI, ChatGPT, atau AI developer lain. Gunakan dokumen ini sebagai sumber kebenaran sebelum mengusulkan perubahan. Sistem harus dikembangkan bertahap, diuji pada hardware nyata, dan tidak boleh mengganggu alarm keselamatan blind spot yang sudah berjalan.

## 1. Tujuan Sistem

Prototype ini dipasang pada alat berat untuk:

1. Mendeteksi manusia pada area blind spot menggunakan kamera.
2. Mengestimasi jarak manusia dari alat berat berdasarkan posisi bawah bounding box (`y2`).
3. Melacak beberapa orang dan durasi keberadaannya.
4. Mengubah jarak dan durasi menjadi tingkat urgensi: `aman`, `siaga`, atau `bahaya`.
5. Memberikan alarm lokal melalui LED dan buzzer.
6. Mencatat hasil deteksi ke CSV.
7. Pengembangan berikutnya: menampilkan status pada LCD di kabin dan menambahkan pemantauan kondisi mesin melalui ESP32, MPU6050, GPS, dan sensor getaran.

Prioritas keselamatan: alarm blind spot tidak boleh berhenti hanya karena modul LCD, ESP32, GPS, atau sensor idle bermasalah.

## 2. Struktur Workspace Saat Ini

File utama:

- `main.py`: runtime utama sistem blind spot.
- `vision.py`: deteksi person dengan YOLO dan NCNN.
- `tracker.py`: tracking sederhana berbasis centroid.
- `fuzzy_engine.py`: fuzzy logic urgensi dan stabilisasi status.
- `zone_config.json`: konfigurasi kalibrasi jarak aktif.
- `calibrate_stream.py`: pengambilan sampel kalibrasi melalui live camera.
- `analyze_calibration.py`: analisis interpolasi dan RMSE kalibrasi.
- `calibrate_zone.py`: skrip kalibrasi versi lama, belum kompatibel dengan format `zone_config.json` aktif.
- `camera_preview.py`: preview kamera dan FPS.
- `test_pipeline.py`: uji manual kamera -> YOLO -> tracker -> jarak -> fuzzy.
- `test_distance_8point.py`: uji estimasi jarak berdasarkan sampel kalibrasi.
- `calibration_samples.csv`: delapan sampel kalibrasi aktual.
- `log_blindspot.csv`: log hasil runtime blind spot.
- `requirements.txt`: dependensi Python.
- `yolov8n_ncnn_model/`: model YOLOv8n NCNN yang dipakai runtime.
- `yolov8n.pt` dan `yolo11n.pt`: file model PyTorch yang tersedia tetapi tidak digunakan jalur runtime aktif.

File backup:

- `main.py.backup_before_8point`
- `main.py.backup_before_gpio_test`
- `main.py.backup_before_vnc_preview`
- `test_pipeline.py.backup_before_8point`
- `fuzzy_engine.py.backup_before_rule_adjustment`
- `zone_config.json.backup_before_8point`

File tambahan dari Claude AI:

- `Tiga file pengembangan dari Claude AI/README.md`
- `Tiga file pengembangan dari Claude AI/idle_monitor.ino`
- `Tiga file pengembangan dari Claude AI/idle_receiver.py`

File `nano calibrate_stream.py` adalah salinan yang diawali fence Markdown `````python````` dan bukan file Python valid. Jangan gunakan sebagai source runtime.

## 3. Runtime Blind Spot Raspberry Pi

Alur aktif:

```text
Kamera /dev/video0
  -> OpenCV 640x480 MJPG @ 30 FPS
  -> CLAHE untuk pencahayaan
  -> YOLOv8n NCNN, class person saja, confidence 0.5
  -> SimpleTracker berbasis centroid
  -> interpolasi y2 menggunakan 8 titik kalibrasi
  -> fuzzy urgency berdasarkan jarak dan durasi
  -> pilih risiko tertinggi dari semua track
  -> StatusStabilizer
  -> LED hijau/kuning/merah dan buzzer
  -> log_blindspot.csv
```

### 3.1 `vision.py`

- Model default: `yolov8n_ncnn_model`.
- Backend: Ultralytics YOLO dengan model NCNN.
- Hanya class COCO `person` dengan ID `0` yang diambil.
- Frame diproses dengan CLAHE sebelum inference.
- Output setiap deteksi:

```python
{
    "x1": float,
    "y1": float,
    "x2": float,
    "y2": float,
    "conf": float
}
```

### 3.2 `tracker.py`

`SimpleTracker` mencocokkan centroid deteksi baru dengan track lama.

- `max_jarak_piksel=80`.
- Track dihapus setelah lebih dari 2 detik tidak terlihat.
- Durasi dihitung dari waktu track pertama dibuat.
- Track dapat bertukar ID saat dua orang bersilangan.
- Untuk use case ini, prioritasnya adalah jarak dan durasi risiko, bukan identitas orang yang sempurna.

Output track:

```python
{
    "id": int,
    "y2": float,
    "durasi_s": float
}
```

### 3.3 Kalibrasi Jarak

`zone_config.json` aktif memakai format:

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

Hubungan yang dipakai: semakin besar `y2`, manusia semakin dekat.

`main.py` mengurutkan titik berdasarkan `y2`, melakukan interpolasi linear, dan melakukan clamp di luar rentang kalibrasi. Jarak dibatasi pada 0.5 sampai 15 meter untuk hasil interpolasi internal.

Validasi saat ini:

- Delapan titik kalibrasi tersedia dari 9 m sampai 2 m.
- `analyze_calibration.py` menghasilkan RMSE 0.000 m pada titik kalibrasi.
- Nilai RMSE nol hanya membuktikan interpolasi melewati sampel yang sama; belum membuktikan akurasi terhadap sampel baru.
- `calibrate_zone.py` masih menulis format lama:

```json
{
  "y_waspada": 300,
  "y_bahaya": 400,
  "jarak_waspada_m": 5.0,
  "jarak_bahaya_m": 2.0
}
```

Jangan menjalankan `calibrate_zone.py` untuk mengganti konfigurasi aktif sebelum skrip tersebut direvisi ke format delapan titik.

### 3.4 Fuzzy Logic

`fuzzy_engine.py` memiliki input:

- `jarak`: 0 sampai 15 m.
- `durasi`: 0 sampai 30 detik.

Output urgensi 0 sampai 100 dan label:

- `aman`: skor kurang dari 33.
- `siaga`: skor 33 sampai kurang dari 66.
- `bahaya`: skor 66 atau lebih.

Aturan utama:

- Jarak jauh -> aman.
- Jarak sedang -> siaga, baik durasi sebentar maupun lama.
- Jarak dekat -> bahaya, baik durasi sebentar maupun lama.

Perubahan status distabilkan oleh `StatusStabilizer`:

- Naik ke status lebih berbahaya perlu 2 iterasi berturut-turut.
- Turun ke status lebih aman perlu 3 iterasi berturut-turut.
- Ambang ini berbasis jumlah loop, bukan waktu detik yang eksak.

### 3.5 GPIO Pi 4 Saat Ini

Kode `main.py` memakai penomoran BCM:

| Fungsi | GPIO BCM | Pin fisik umum |
|---|---:|---:|
| Buzzer blind spot | 22 | 15 |
| LED hijau blind spot | 23 | 16 |
| LED kuning blind spot | 24 | 18 |
| LED merah blind spot | 25 | 22 |

GPIO ini adalah output alarm keselamatan blind spot. Jangan dipakai ulang untuk LCD, ESP32, atau idle alarm tanpa keputusan wiring yang eksplisit.

`main.py` sudah memiliki pembersihan output pada `finally` untuk jalur normal/KeyboardInterrupt, tetapi setiap integrasi baru harus mempertahankan fail-safe: saat program berhenti atau error, output harus dimatikan dan kamera/serial harus ditutup.

## 4. Dependensi dan Hardware Saat Ini

`requirements.txt`:

```text
ultralytics
opencv-python
gpiozero
numpy
scikit-fuzzy
```

Hardware/runtime yang diasumsikan:

- Raspberry Pi 4.
- Kamera USB atau kamera V4L2 pada `/dev/video0`.
- GPIO LED dan buzzer seperti tabel di atas.
- Display OpenCV, sehingga runtime saat ini membutuhkan sesi GUI/display yang mendukung `cv2.imshow`.
- Model YOLOv8n NCNN lengkap:
  - `model.ncnn.param`
  - `model.ncnn.bin`
  - `metadata.yaml`

Belum ada dependensi LCD, GPS, MPU6050 Python, atau serial Python pada requirements aktif.

## 5. Tiga File Pengembangan dari Claude AI

### 5.1 `idle_monitor.ino`

Firmware ESP32 membaca MPU6050 melalui I2C dan mengirim satu baris serial tiap sekitar satu detik:

```text
STATUS,durasi_idle_detik,getaran_g
```

Contoh:

```text
IDLE,45,0.087
```

Status yang didukung:

- `MESIN_MATI`
- `BERGERAK`
- `IDLE`
- `IDLE_LAMA`

Wiring yang diasumsikan:

| MPU6050 | ESP32 |
|---|---|
| VCC | 3.3V |
| GND | GND |
| SDA | GPIO21 |
| SCL | GPIO22 |

UART:

| ESP32 | Raspberry Pi 4 |
|---|---|
| TX2 GPIO17 | RXD GPIO15, pin fisik 10 |
| RX2 GPIO16 | TXD GPIO14, pin fisik 8 |
| GND | GND bersama |

Output idle lokal pada ESP32:

- LED hijau GPIO25.
- LED kuning GPIO26.
- LED merah GPIO27.
- Buzzer GPIO14.

Konfigurasi awal:

- `AMBANG_MESIN_MATI = 0.030 g`.
- `AMBANG_GERAK = 0.180 g`.
- Peringatan `IDLE_LAMA` setelah 3 menit.
- Rata-rata bergerak 20 sampel.
- I2C MPU6050 address `0x68`.
- UART ESP32 `Serial2` 9600 baud, RX 16 dan TX 17.

### 5.2 `idle_receiver.py`

Skrip Raspberry Pi membaca `/dev/serial0` pada 9600 baud, mem-parse format CSV teks, mencetak data, dan menulis `log_idle.csv`.

Parser mengembalikan:

```python
{
    "status": "IDLE",
    "durasi_idle_s": 45,
    "getaran_g": 0.087
}
```

Status invalid atau baris rusak dilewati tanpa crash.

Skrip ini masih program standalone. Belum terintegrasi dengan loop `main.py`, belum mengirim data ke LCD, dan belum menggabungkan alarm idle dengan alarm blind spot.

## 6. Ketidaksesuaian yang Wajib Diperhatikan

Jangan langsung memakai tiga file Claude sebagai implementasi final. Kondisinya:

1. **GPS belum diimplementasikan.** User menginginkan GPS untuk lokasi, tetapi `idle_monitor.ino` hanya memakai MPU6050. Tidak ada modul GPS, wiring GPS, format koordinat, atau parser NMEA.
2. **Deteksi mesin ON/OFF belum benar-benar tervalidasi.** Firmware menganggap getaran sangat rendah sebagai `MESIN_MATI` dan getaran menengah sebagai `IDLE`. Ambang tersebut hanya titik awal dan belum diukur pada mesin alat berat target.
3. **Algoritma getaran belum membuktikan pola mesin.** Firmware memakai deviasi magnitude akselerasi dari rata-rata bergerak. Hal ini dapat salah klasifikasi karena posisi pemasangan, getaran bodi, sensor longgar, gerakan operator, atau perubahan orientasi gravitasi.
4. **LCD belum ada.** Tidak ada jenis LCD, ukuran, interface, alamat I2C, library, layout, refresh rate, atau keputusan apakah LCD dikendalikan Pi atau ESP32.
5. **Receiver belum terintegrasi.** `idle_receiver.py` hanya logger dan monitor serial standalone. `main.py` belum membaca UART.
6. **Konflik format konfigurasi kalibrasi lama.** `calibrate_zone.py` masih dapat menulis format yang akan membuat `main.py` gagal karena `main.py` membutuhkan `calibration_points`.
7. **Konflik alarm belum didefinisikan.** Blind spot memakai LED/buzzer pada Pi; idle memakai LED/buzzer pada ESP32. Belum ada keputusan prioritas bila alarm blind spot dan idle muncul bersamaan.
8. **Kondisi komunikasi putus belum didefinisikan.** Jika UART ESP32 terputus, sistem belum memiliki timeout, status `SENSOR_OFFLINE`, atau aturan fail-safe.
9. **Deteksi mesin hidup hanya dari getaran berisiko.** GPS tidak dapat menentukan mesin ON/OFF sendirian. Untuk kepastian lebih tinggi diperlukan sumber lain seperti sinyal ACC/ignition 12/24 V melalui isolasi yang sesuai, alternator/D+/engine-run signal, CAN/J1939 jika tersedia, atau sensor arus/tegangan yang dirancang untuk kendaraan.
10. **Tegangan kendaraan belum dibahas.** Jangan menyambungkan GPIO/ESP32 langsung ke sistem listrik alat berat 12/24 V. Wajib gunakan regulator, fuse, proteksi surge, ground yang benar, dan interface/isolator yang sesuai.
11. **Receiver membutuhkan pyserial.** `pyserial` belum ada di `requirements.txt` aktif.
12. **UART Pi harus dikonfigurasi.** Serial console/login shell harus dimatikan dan hardware UART diaktifkan, tetapi langkah ini belum diverifikasi pada device target.
13. **Skrip firmware memakai `sqrt`/`fabs`.** Pada banyak toolchain Arduino fungsi ini tersedia, tetapi firmware tetap perlu dikompilasi pada board dan versi core ESP32 yang sebenarnya digunakan.
14. **Data status idle tidak memiliki sequence number atau timestamp sumber.** Sulit mendeteksi paket lama/replay jika komunikasi tersendat.

## 7. Rancangan Pengembangan yang Diinginkan

### Fase A: LCD pada kabin

LCD harus menampilkan setidaknya:

- Status blind spot: `AMAN`, `SIAGA`, atau `BAHAYA`.
- Jarak manusia terdekat.
- Jumlah orang terdeteksi.
- Durasi track berisiko.
- Status mesin: `MESIN MATI`, `BERGERAK`, `IDLE`, `IDLE LAMA`, atau `SENSOR OFFLINE`.
- Durasi idle.
- Status GPS bila GPS dipasang: fix valid/tidak valid dan koordinat atau area kerja yang diperlukan.

Keputusan desain yang harus dibuat sebelum coding:

- Jenis LCD: I2C 16x2, I2C 20x4, OLED, HDMI, atau layar lain.
- Perangkat pengendali LCD: Raspberry Pi lebih disarankan agar data blind spot dan idle berada dalam satu tampilan; ESP32 hanya mengirim data sensor.
- Alamat I2C LCD dan bus yang digunakan.
- Prioritas tampilan saat alarm blind spot dan idle bersamaan.
- Apakah LCD harus tetap hidup jika detector YOLO gagal.
- Refresh rate agar layar tidak flicker dan tidak membebani loop inference.

### Fase B: ESP32 untuk sensor

ESP32 idealnya menangani:

- MPU6050 dan pemrosesan getaran.
- GPS jika memang dibutuhkan untuk lokasi.
- Sinyal engine-run/ignition atau sensor tambahan untuk membedakan ON/OFF.
- Status idle, durasi idle, kualitas sensor, dan heartbeat komunikasi.
- Pengiriman paket terstruktur ke Pi melalui UART.

Raspberry Pi menangani:

- Kamera, YOLO, tracking, estimasi jarak, fuzzy blind spot.
- Penggabungan status sensor dengan status blind spot.
- LCD operator.
- Logging terpadu.
- Kebijakan prioritas alarm.

Format komunikasi yang direkomendasikan untuk revisi, bukan format final yang sudah diterapkan:

```text
V1,status_mesin,status_idle,durasi_idle_s,getaran_g,lat,lon,gps_fix,seq,timestamp_ms
```

Contoh:

```text
V1,ON,IDLE,45,0.087,-6.2001,106.8167,1,1234,456789
```

Format harus memiliki checksum/CRC atau minimal sequence number dan aturan timeout bila dipakai untuk sistem lapangan. JSON boleh dipakai jika beban dan bandwidth memadai, tetapi format harus konsisten dan mudah divalidasi.

### Fase C: Kebijakan idle dan alarm

Definisi bisnis yang perlu dikunci:

- `MESIN_MATI`: mesin benar-benar tidak aktif.
- `BERGERAK` atau `OPERASI`: alat bergerak/beroperasi.
- `IDLE`: mesin menyala tetapi tidak melakukan aktivitas yang ditentukan.
- `IDLE_LAMA`: mesin idle melebihi batas, misalnya 3 menit.

Peringatan idle hanya boleh aktif bila:

1. Status engine benar-benar `ON` atau terkonfirmasi hidup.
2. Tidak ada aktivitas/gerakan selama ambang waktu yang disepakati.
3. Sensor sehat dan data masih fresh.
4. Kondisi bukan sekadar kehilangan GPS atau kehilangan paket UART.

Alarm blind spot harus mempunyai prioritas keselamatan lebih tinggi daripada penghematan bahan bakar. Bila keduanya aktif bersamaan, tampilan dan buzzer harus memiliki pola yang dapat dibedakan atau blind spot harus mengambil prioritas eksplisit.

## 8. Strategi Integrasi yang Disarankan

1. Jangan mengubah jalur blind spot saat pertama menambahkan ESP32.
2. Uji `idle_monitor.ino` secara mandiri pada ESP32 dan simpan log mentah getaran dalam kondisi mesin mati, idle, bergerak, dan aktivitas lain.
3. Tambahkan `pyserial` dan uji `idle_receiver.py` secara mandiri dengan timeout, reconnect, paket rusak, dan ESP32 terputus.
4. Pilih dan dokumentasikan LCD sebelum membuat driver.
5. Buat modul Python terpisah, misalnya `idle_receiver.py` sebagai class/library, bukan membaca serial langsung di banyak tempat.
6. Tambahkan model data sensor yang tervalidasi, misalnya `IdleStatus`/dictionary terstruktur.
7. Integrasikan pembacaan serial secara non-blocking ke loop utama atau thread/worker yang jelas, tanpa menghambat inference kamera.
8. Tambahkan timeout freshness. Data ESP32 yang lebih lama dari batas tertentu harus menjadi `SENSOR_OFFLINE`.
9. Pisahkan output alarm blind spot dan idle secara logis walaupun akhirnya perangkat keras berbagi buzzer/LCD.
10. Tambahkan satu CSV terpadu atau dua log yang memiliki timestamp konsisten.
11. Tambahkan pengujian unit untuk parser serial, timeout, prioritas alarm, dan status LCD sebelum uji lapangan.
12. Baru setelah data nyata terkumpul, kalibrasi ambang getaran dan durasi idle.

## 9. Batasan dan Aturan untuk AI Developer Berikutnya

- Jangan mengganti format `zone_config.json` aktif tanpa migrasi dan validasi.
- Jangan memakai `calibrate_zone.py` sebelum direvisi ke format `calibration_points`.
- Jangan menghapus `StatusStabilizer` tanpa alasan keselamatan yang jelas.
- Jangan menggabungkan alarm idle dan blind spot tanpa mendefinisikan prioritas.
- Jangan menganggap GPS sebagai sensor engine ON/OFF.
- Jangan mengklaim deteksi idle sudah akurat sebelum ada log alat berat nyata.
- Jangan menyambungkan ESP32 atau Pi langsung ke 12/24 V kendaraan.
- Jangan membuat pembacaan serial blocking di loop inference kamera.
- Jangan membuat LCD sebagai single point of failure untuk alarm keselamatan.
- Pertahankan cleanup GPIO, kamera, LCD, dan serial saat shutdown.
- Semua perubahan harus kecil, dapat diuji, dan disertai perintah validasi.

## 10. Prompt Revisi untuk Claude AI atau ChatGPT

Gunakan prompt berikut untuk meminta revisi tiga file pengembangan:

> Pahami dulu workspace Raspberry Pi 4 saya dari dokumen konteks ini. Saya memiliki sistem blind spot yang sudah aktif dengan `main.py`, `vision.py`, `tracker.py`, `fuzzy_engine.py`, kamera `/dev/video0`, YOLOv8n NCNN, kalibrasi `zone_config.json` berbasis delapan titik `calibration_points`, serta GPIO blind spot BCM 22/23/24/25. Jangan merusak jalur keselamatan tersebut.
>
> Saya ingin mengembangkan sistem secara bertahap:
>
> 1. Tambahkan LCD untuk operator di kabin.
> 2. Gunakan ESP32 untuk membaca MPU6050, sensor getaran, GPS, dan sinyal yang lebih valid untuk mengetahui mesin ON/OFF bila tersedia.
> 3. Deteksi kondisi `MESIN_MATI`, `BERGERAK`, `IDLE`, `IDLE_LAMA`, dan `SENSOR_OFFLINE`.
> 4. Berikan peringatan idle agar operator mematikan mesin ketika mesin ON tetapi tidak ada aktivitas selama ambang waktu tertentu.
> 5. Tampilkan status blind spot dan idle pada LCD, tetapi alarm blind spot tetap memiliki prioritas keselamatan tertinggi.
>
> Tiga file awal saya adalah `idle_monitor.ino`, `idle_receiver.py`, dan README terkait. Audit dahulu ketiganya. Jangan langsung menggunakannya bila tidak sesuai. Identifikasi semua ketidaksesuaian dengan sistem saat ini, terutama fakta bahwa kode awal belum memiliki GPS, belum memiliki LCD, belum tervalidasi pada alat berat, dan belum terintegrasi ke `main.py`.
>
> Kemudian berikan revisi dalam fase aman:
>
> - Fase 1: protokol data ESP32 ke Pi yang memiliki versi, sequence number, timestamp, status sensor, status engine, status idle, getaran, GPS fix, koordinat, dan checksum/validasi.
> - Fase 2: receiver serial non-blocking dengan timeout, reconnect, `SENSOR_OFFLINE`, parser paket rusak, dan logging.
> - Fase 3: integrasi ke pipeline `main.py` tanpa menghambat YOLO dan tanpa mengambil alih GPIO blind spot.
> - Fase 4: driver LCD sesuai jenis LCD yang saya konfirmasi.
> - Fase 5: kalibrasi ambang getaran dan validasi lapangan.
>
> Sebelum menulis kode, tanyakan atau nyatakan asumsi untuk: jenis LCD, tipe board ESP32, tipe GPS, sumber sinyal engine ON/OFF, sensor getaran yang tersedia, tegangan kelistrikan alat berat, wiring final, pola prioritas buzzer, dan batas waktu idle. Jangan menganggap GPS dapat mendeteksi engine ON/OFF. Sertakan daftar file yang diubah, wiring, dependensi, prosedur pengujian, dan cara rollback.

## 11. Status Validasi Saat Ini

Validasi yang sudah dilakukan:

- Sintaks semua file Python runtime utama berhasil.
- Analisis delapan sampel kalibrasi berhasil.
- RMSE pada titik kalibrasi: 0.000 m.
- Demo fuzzy logic berhasil.
- Model NCNN memiliki file parameter dan bobot lengkap.

Validasi yang belum dilakukan:

- Inference langsung dengan kamera pada sesi ini.
- GPIO pada hardware nyata.
- UART fisik ESP32-Pi.
- Kompilasi firmware ESP32 pada board target.
- MPU6050 pada alat berat nyata.
- GPS pada area kerja nyata.
- LCD pada kabin.
- Keakuratan klasifikasi mesin mati, idle, bergerak, dan operasi.

Kesimpulan: sistem blind spot Raspberry Pi adalah baseline yang sudah berjalan. Modul ESP32 dari Claude adalah proof-of-concept terpisah untuk idle berbasis getaran, bukan integrasi final. Integrasi berikutnya harus dimulai dari audit hardware dan definisi protokol, lalu dilakukan bertahap dengan fail-safe.
