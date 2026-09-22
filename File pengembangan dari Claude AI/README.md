# Modul Sensor Langsung-di-Pi (tanpa ESP32) + Optimasi Beban

Arsitektur berubah: **semua kembali ke satu Raspberry Pi 4**, tidak ada
ESP32 lagi (atas rekomendasi dosen pembimbing, demi purwarupa yang lebih
compact). Empat file baru di sini gantinya jalan LANGSUNG di Pi.

## File apa yang jadi TIDAK RELEVAN sekarang

`sensor_protocol.py`, `test_sensor_protocol.py`, dan `protocol_esp32.h`
dari pengembangan sebelumnya **tidak dipakai lagi** — itu protokol
komunikasi UART khusus untuk ESP32 kirim data ke Pi, sementara sekarang
tidak ada ESP32 yang mengirim apapun. Boleh dihapus dari workspace, atau
dibiarkan saja sebagai arsip riwayat pengembangan — tidak akan
mengganggu apapun kalau dibiarkan, cuma tidak dipakai `main.py`.

## Empat file baru

| File | Fungsi | Sudah diverifikasi |
|---|---|---|
| `mpu6050_sensor.py` | Baca getaran + klasifikasi status mesin/idle langsung lewat I2C | Ya — 5 skenario (mati/idle/bergerak/gagal-baca/idle-lama) pakai I2C tiruan |
| `vibration_sw420.py` | Baca sensor getaran digital sederhana | Ya — deteksi ada/tidak transisi sinyal pakai GPIO tiruan |
| `gps_neo6m.py` | Baca lokasi GPS lewat UART, parsing NMEA | Ya — end-to-end lewat port serial virtual sungguhan, termasuk lewati sentence rusak/irelevan |
| `throttle_pattern.py` | Pola pembatas laju loop 1Hz (lihat bagian optimasi di bawah) | Ya — durasi siklus teruji presisi mendekati target |

Yang **belum** bisa diverifikasi dari sandbox ini: pembacaan sensor
FISIK sungguhan (MPU6050/SW-420/GPS asli), dan karakter getaran mesin
alat berat kamu yang sebenarnya (ambang di `mpu6050_sensor.py` adalah
titik awal dari riset literatur, sama seperti sebelumnya — bukan hasil
ukur langsung ke alat berat kamu).

## Wiring lengkap tiga sensor

**MPU6050 (I2C)** — bus yang sama dipakai I2C lain kalau ada:
| MPU6050 | Pi (GPIO) | Pi (pin fisik) |
|---|---|---|
| VCC | 3.3V | 1 atau 17 |
| GND | GND | 6/9/14/20/25 |
| SDA | GPIO2 | 3 |
| SCL | GPIO3 | 5 |

**SW-420 (digital)**:
| SW-420 | Pi (GPIO) | Pi (pin fisik) |
|---|---|---|
| VCC | 3.3V/5V (cek modul) | — |
| GND | GND | — |
| DO | GPIO17 | 11 |

**GPS NEO-6M (UART)** — pakai port yang sama yang sebelumnya
direncanakan untuk ESP32:
| NEO-6M | Pi (GPIO) | Pi (pin fisik) |
|---|---|---|
| VCC | 5V (cek modul) | — |
| GND | GND | — |
| TX | RXD / GPIO15 | 10 |
| RX | TXD / GPIO14 | 8 (opsional) |

Sebelum GPS bisa dipakai, port serial Pi wajib dikonfigurasi (proses
identik dengan yang dulu disiapkan untuk ESP32, tinggal dipakai ulang):
```bash
sudo raspi-config
# Interface Options -> Serial Port
# "login shell over serial" -> No
# "serial port hardware"    -> Yes
# lalu reboot
```

**GPIO yang SUDAH DIPAKAI, jangan dipakai ulang**: 22 (buzzer), 23
(LED hijau), 24 (LED kuning), 25 (LED merah) — alarm blind spot, tetap
prioritas keselamatan tertinggi, tidak boleh diganggu.

## ⚠️ Perhatian untuk LCD 3.5" (GPIO/SPI) yang akan datang

Kamu bilang "untuk sementara di laptop dulu" untuk tampilan, jadi ini
BUKAN untuk dikerjakan sekarang — tapi penting diketahui SEBELUM beli
LCD-nya. Banyak produk "LCD 3.5 inch GPIO/SPI untuk Raspberry Pi" itu
bentuknya HAT yang menutupi SELURUH 40-pin header, dan tipe yang umum
justru memakai **GPIO24 dan GPIO25** — persis dua pin yang sekarang
dipakai LED kuning dan LED merah kamu. Kalau LCD yang kamu beli tipe ini,
akan bentrok fisik langsung.

Sebelum beli: cari LCD yang secara eksplisit disebutkan tidak menempati
pin selain jalur SPI standar (SPI0: GPIO 8/9/10/11), atau yang punya
pass-through header (ada 2 baris pin di sisi bawah papan LCD, jadi pin
lain tetap bisa disambung lewat situ). Kalau ragu, tanyakan dulu
sebelum beli, atau siapkan rencana pindah LED/buzzer ke pin lain.

## Cara menambahkan ke workspace SSH kamu

Dari laptop (bukan dari Pi), salin ke folder workspace yang sudah ada:
```bash
scp mpu6050_sensor.py vibration_sw420.py gps_neo6m.py throttle_pattern.py \
    <user>@<ip-pi>:~/blindspot_detector/
```

Lalu di Pi (lewat SSH), tambahkan dependensi baru:
```bash
cd ~/blindspot_detector
source venv/bin/activate   # kalau pakai venv seperti yang sudah didokumentasikan
pip install pyserial pynmea2 smbus2
```
(`gpiozero` seharusnya sudah terpasang dari sebelumnya untuk LED/buzzer.)

Uji tiap file SENDIRI-SENDIRI dulu sebelum digabung ke `main.py` —
misal `python3 -c "from mpu6050_sensor import MPU6050Sensor; s=MPU6050Sensor(); print(s.baca_status())"`
— supaya kalau ada masalah wiring, jelas sensor mana yang bermasalah,
bukan tercampur dengan masalah di tempat lain.

## Soal optimasi beban Pi (poin utama permintaan kamu)

`throttle_pattern.py` isinya pola `LoopThrottle` yang MEMAKSA satu
siklus penuh (baca kamera + YOLO + tracker + fuzzy + baca 3 sensor baru
+ update tampilan) berjalan MAKSIMAL sekali per detik — bukan secepat
mungkin lalu nunggu. ini yang paling langsung menjawab "jangan terlalu
banyak data tiap detik" dan "jangan overheat", karena CPU yang benar-benar
`sleep()` (bukan sibuk berulang menunggu) itu yang suhunya turun.

Ini file REFERENSI, bukan untuk langsung dipakai — cara memasukkannya ke
`main.py` yang sudah ada ada di prompt Copilot di bawah, sengaja
dipisah supaya perubahan ke file yang sudah jalan tetap lewat proses
bertahap.
