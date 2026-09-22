"""
tracker.py
Pelacak sederhana berbasis kedekatan centroid antar frame -- solusi untuk
keterbatasan "cuma melacak satu orang paling dekat" di versi sebelumnya.
Sekarang tiap orang dapat ID sendiri dan durasinya dilacak masing-masing.

Bukan tracker canggih seperti DeepSORT (yang butuh model re-identifikasi
terpisah), tapi untuk skenario blind spot alat berat -- biasanya cuma
1-3 orang dalam satu frame -- pendekatan sederhana ini realistis dan
cukup akurat, sekaligus jauh lebih ringan untuk Raspberry Pi 4.

KETERBATASAN YANG JUJUR PERLU DISEBUT: kalau dua orang saling menyilang
posisi persis berdekatan, ID keduanya bisa tertukar. Ini bukan masalah
besar untuk use case ini karena yang penting adalah JARAK & DURASI
tetap dilacak per track, bukan identitas orangnya secara presisi.
"""

import time


class SimpleTracker:
    def __init__(self, max_jarak_piksel=80, max_hilang_detik=2.0):
        """
        max_jarak_piksel: kalau centroid deteksi baru & track lama bergeser
                           lebih jauh dari ini, dianggap orang berbeda
        max_hilang_detik: toleransi waktu sebuah track tetap "hidup" walau
                           sempat tidak terdeteksi 1-2 frame (menghindari
                           track hilang gara-gara deteksi meleset sesaat,
                           bukan karena orangnya benar-benar pergi)
        """
        self.max_jarak_piksel = max_jarak_piksel
        self.max_hilang_detik = max_hilang_detik
        self.tracks = {}
        self._next_id = 0

    @staticmethod
    def _centroid(box):
        return ((box['x1'] + box['x2']) / 2, (box['y1'] + box['y2']) / 2)

    def update(self, deteksi):
        """
        deteksi: list bounding box dari PersonDetector.detect_people()
        return: list track aktif -- tiap item {'id', 'y2', 'durasi_s'}
        """
        now = time.time()
        belum_cocok = list(range(len(deteksi)))

        for tid in list(self.tracks.keys()):
            track = self.tracks[tid]
            terdekat, jarak_terdekat = None, None

            for i in belum_cocok:
                cx, cy = self._centroid(deteksi[i])
                tx, ty = track['centroid']
                jarak = ((cx - tx) ** 2 + (cy - ty) ** 2) ** 0.5
                if jarak_terdekat is None or jarak < jarak_terdekat:
                    jarak_terdekat, terdekat = jarak, i

            if terdekat is not None and jarak_terdekat <= self.max_jarak_piksel:
                box = deteksi[terdekat]
                track['centroid'] = self._centroid(box)
                track['y2'] = box['y2']
                track['terakhir_terlihat'] = now
                belum_cocok.remove(terdekat)
            elif now - track['terakhir_terlihat'] > self.max_hilang_detik:
                del self.tracks[tid]

        for i in belum_cocok:
            box = deteksi[i]
            self.tracks[self._next_id] = {
                'centroid': self._centroid(box),
                'y2': box['y2'],
                'masuk_sejak': now,
                'terakhir_terlihat': now,
            }
            self._next_id += 1

        return [
            {'id': tid, 'y2': t['y2'], 'durasi_s': now - t['masuk_sejak']}
            for tid, t in self.tracks.items()
        ]
