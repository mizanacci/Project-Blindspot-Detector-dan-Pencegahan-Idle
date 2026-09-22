"""
calibrate_zone.py
Skrip interaktif untuk kalibrasi zona jarak. Karena kamera dipasang di
posisi & sudut TETAP pada alat berat, hubungan antara "di baris piksel
mana bagian bawah kotak orang terdeteksi" dengan "seberapa jauh jaraknya
sungguhan" itu konsisten -- cukup dikalibrasi sekali di awal.

CARA PAKAI:
1. Pasang kamera di posisi & sudut FINAL -- persis seperti akan dipakai
   saat demo/prototipe jalan. Kalau kamera digeser, ulangi kalibrasi ini.
2. Jalankan: python3 calibrate_zone.py
3. Ikuti instruksi: taruh orang/figur pada jarak yang diminta, lalu
   tekan ENTER saat sudah siap dan sudah terlihat kamera.
4. Hasil otomatis tersimpan ke zone_config.json, langsung dipakai main.py.

Titik kalibrasi & jarak contoh di TITIK_KALIBRASI boleh diubah sesuai
skala mockup/model alat berat kamu (satuan tetap "meter" tapi bisa
diartikan sebagai skala model, yang penting konsisten).
"""

import json
import cv2

from vision import PersonDetector

TITIK_KALIBRASI = [
    ('aman', 10.0, 'jarak jauh (mis. 10 meter) -- masih AMAN'),
    ('waspada', 5.0, 'jarak sedang (mis. 5 meter) -- mulai WASPADA'),
    ('bahaya', 2.0, 'jarak dekat (mis. 2 meter) -- sudah BAHAYA'),
]


def main():
    print("=== KALIBRASI ZONA JARAK ===")
    print("Pastikan kamera sudah terpasang di posisi & sudut FINAL.\n")

    detector = PersonDetector()
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Kamera tidak terdeteksi. Cek koneksi webcam lalu coba lagi.")
        return

    hasil_y = {}
    jarak_map = {}

    for label, jarak_m, deskripsi in TITIK_KALIBRASI:
        jarak_map[label] = jarak_m
        print(f"\n>> Taruh orang/figur pada {deskripsi}.")
        input("   Tekan ENTER kalau sudah siap dan terlihat di kamera...")

        ret, frame = cap.read()
        if not ret:
            print("   Gagal ambil gambar dari kamera, lewati titik ini.")
            continue

        orang = detector.detect_people(frame)
        if not orang:
            print("   Tidak ada orang terdeteksi -- cek pencahayaan, coba lagi.")
            ret, frame = cap.read()
            orang = detector.detect_people(frame) if ret else []
            if not orang:
                print("   Masih gagal, titik ini dilewati. Bisa diulang manual nanti.")
                continue

        target = max(orang, key=lambda o: o['conf'])
        hasil_y[label] = target['y2']
        print(f"   Tercatat: y={target['y2']:.0f}px (confidence {target['conf']:.2f})")

    cap.release()

    if 'waspada' not in hasil_y or 'bahaya' not in hasil_y:
        print("\nKalibrasi belum lengkap -- titik 'waspada' dan 'bahaya' wajib berhasil.")
        print("Jalankan ulang skrip ini, atau edit zone_config.json manual.")
        return

    zone_config = {
        'y_waspada': hasil_y['waspada'],
        'y_bahaya': hasil_y['bahaya'],
        'jarak_waspada_m': jarak_map['waspada'],
        'jarak_bahaya_m': jarak_map['bahaya'],
    }

    with open('zone_config.json', 'w') as f:
        json.dump(zone_config, f, indent=2)

    print("\nKalibrasi selesai, tersimpan ke zone_config.json:")
    for k, v in zone_config.items():
        print(f"  {k} = {v}")
    print("\nKalau hasil deteksi di lapangan kurang pas, boleh edit langsung "
          "angka di zone_config.json tanpa perlu kalibrasi ulang dari awal.")


if __name__ == '__main__':
    main()
