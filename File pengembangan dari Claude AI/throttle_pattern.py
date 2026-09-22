"""
throttle_pattern.py
Pola referensi untuk membatasi loop utama supaya jalan MAKSIMAL sekali
per detik (atau interval lain yang kamu pilih) -- bukan secepat mungkin.

INI FILE REFERENSI/DEMONSTRASI, bukan untuk di-import main.py secara
langsung -- salin pola `LoopThrottle` ini ke dalam struktur main.py yang
sudah ada (lihat prompt Copilot terpisah untuk integrasinya), karena
main.py sendiri sebaiknya tidak diubah tanpa proses bertahap yang jelas.

KENAPA INI MENGURANGI BEBAN, BUKAN CUMA MEMPERLAMBAT TAMPILAN:
- Capture kamera diminta pada FPS lebih rendah (bukan 30 FPS) -- driver
  kamera/USB tidak dipaksa kerja menyediakan frame yang toh dibuang.
- Inference YOLO, baca MPU6050 (burst 0.2s), baca SW-420 (jendela
  0.3s), dan baca GPS cuma dijalankan SEKALI per siklus terkontrol --
  bukan berlomba secepat mungkin lalu menunggu, yang di CPU artinya
  tetap 100% dipakai sia-sia.
- `time.sleep()` di akhir siklus benar-benar melepas CPU ke idle,
  membiarkan suhu turun -- ini yang paling langsung menjawab masalah
  overheat, karena CPU yang sungguhan idle (bukan busy-loop) itu yang
  menyala rendah/throttle turun secara termal.
"""

import time


class LoopThrottle:
    """
    Pakai di awal & akhir tiap satu siklus loop utama:

        throttle = LoopThrottle(interval_s=1.0)
        while True:
            throttle.mulai_siklus()
            # ... kerjaan satu siklus: baca kamera, YOLO, sensor, dst ...
            throttle.tunggu_sisa_waktu()

    Kalau satu siklus kerjaan makan waktu LEBIH dari interval_s (misal
    YOLO kebetulan lambat), tunggu_sisa_waktu() tidak menunggu sama
    sekali (tidak mungkin sleep negatif) -- siklus berikutnya langsung
    mulai. Ini mencegah keterlambatan menumpuk, tapi juga berarti kalau
    KONSISTEN lebih lambat dari target, sistem efektif jalan di
    kecepatan aslinya (lebih lambat dari 1Hz) -- itu sinyal jujur kalau
    interval_s terlalu ambisius untuk hardware kamu, bukan dipaksa.
    """

    def __init__(self, interval_s=1.0):
        self.interval_s = interval_s
        self._mulai = None

    def mulai_siklus(self):
        self._mulai = time.time()

    def tunggu_sisa_waktu(self):
        elapsed = time.time() - self._mulai
        sisa = self.interval_s - elapsed
        if sisa > 0:
            time.sleep(sisa)
        return elapsed  # dikembalikan untuk keperluan logging/diagnostik


if __name__ == "__main__":
    print("Demo LoopThrottle -- 5 siklus, target 1.0 detik per siklus,")
    print("tiap siklus disimulasikan makan waktu acak 0.1-0.4 detik kerja nyata:\n")

    import random

    throttle = LoopThrottle(interval_s=1.0)
    for i in range(5):
        throttle.mulai_siklus()
        waktu_kerja = random.uniform(0.1, 0.4)
        time.sleep(waktu_kerja)  # simulasi kerja nyata (baca sensor, YOLO, dst)
        t0 = time.time()
        elapsed = throttle.tunggu_sisa_waktu()
        total_siklus = time.time() - t0 + elapsed
        print(f"Siklus {i+1}: kerja nyata={waktu_kerja:.3f}s | "
              f"total siklus (kerja+tunggu)~={elapsed + (time.time()-t0):.3f}s")

    print("\nKalau semua baris di atas menunjukkan total siklus mendekati 1.0s")
    print("meski waktu kerja nyatanya bervariasi, throttle bekerja dengan benar.")
