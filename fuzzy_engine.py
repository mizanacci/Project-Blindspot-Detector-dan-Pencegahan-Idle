"""
fuzzy_engine.py
Fuzzy Logic Mamdani untuk menentukan tingkat urgensi alarm blind spot.

Input : jarak (meter, hasil interpolasi posisi bounding box hasil kalibrasi)
        durasi (detik, berapa lama orang terdeteksi terus-menerus dalam
                radius perhatian sejak episode saat ini dimulai)
Output: urgensi (Aman / Siaga / Bahaya)

Kenapa durasi ikut jadi input: orang yang lewat sekilas beda risikonya
dari orang yang berdiri lama di dekat alat berat yang sedang beroperasi.
Jarak tetap jadi faktor dominan -- posisi SANGAT dekat langsung dianggap
bahaya berapa pun durasinya, karena itu realistis: tidak ada alasan
menunggu "cukup lama" dulu sebelum bereaksi kalau orangnya sudah dekat.

Jalankan langsung file ini (`python3 fuzzy_engine.py`) untuk demo tanpa
kamera/YOLO -- berguna untuk validasi rule sebelum diintegrasikan.
"""

import numpy as np
import skfuzzy as fuzz
from skfuzzy import control as ctrl

TINGKATAN = ['aman', 'siaga', 'bahaya']


def build_fuzzy_system():
    jarak = ctrl.Antecedent(np.arange(0, 15.01, 0.1), 'jarak')
    jarak['dekat'] = fuzz.trapmf(jarak.universe, [0, 0, 2, 4])
    jarak['sedang'] = fuzz.trimf(jarak.universe, [2, 5, 8])
    jarak['jauh'] = fuzz.trapmf(jarak.universe, [5, 8, 15, 15])

    durasi = ctrl.Antecedent(np.arange(0, 30.01, 0.5), 'durasi')
    durasi['sebentar'] = fuzz.trapmf(durasi.universe, [0, 0, 3, 8])
    durasi['lama'] = fuzz.trapmf(durasi.universe, [5, 10, 30, 30])

    urgensi = ctrl.Consequent(np.arange(0, 100.01, 1), 'urgensi')
    urgensi['aman'] = fuzz.trapmf(urgensi.universe, [0, 0, 20, 40])
    urgensi['siaga'] = fuzz.trimf(urgensi.universe, [25, 50, 75])
    urgensi['bahaya'] = fuzz.trapmf(urgensi.universe, [60, 80, 100, 100])

    rules = [
    # Orang jauh dari alat berat -> AMAN
    ctrl.Rule(jarak['jauh'], urgensi['aman']),

    # Jarak sedang -> SIAGA
    # Durasi sebentar maupun lama tetap berada pada
    # zona SIAGA; durasi tidak boleh langsung membuat
    # jarak 5-6 meter menjadi BAHAYA.
    ctrl.Rule(
        jarak['sedang'] & durasi['sebentar'],
        urgensi['siaga']
    ),

    ctrl.Rule(
        jarak['sedang'] & durasi['lama'],
        urgensi['siaga']
    ),

    # Orang sangat dekat -> BAHAYA,
    # berapa pun durasinya.
    ctrl.Rule(
        jarak['dekat'] & durasi['sebentar'],
        urgensi['bahaya']
    ),

    ctrl.Rule(
        jarak['dekat'] & durasi['lama'],
        urgensi['bahaya']
    ),
]

    return ctrl.ControlSystemSimulation(ctrl.ControlSystem(rules))


# Beda dari fuzzy_engine sistem lereng sebelumnya: breakpoint di sini
# TETAP (tidak ada faktor eksternal yang menggeser ambang), jadi sistem
# cukup dibangun sekali di level modul, tidak perlu dibangun ulang tiap
# siklus -- lebih hemat komputasi untuk loop yang jalan tiap frame kamera.
_sim = build_fuzzy_system()


def evaluate_urgency(jarak_m, durasi_s):
    """Return: (skor: float 0-100, label: 'aman'/'siaga'/'bahaya')"""
    _sim.input['jarak'] = max(0.0, min(jarak_m, 15.0))
    _sim.input['durasi'] = max(0.0, min(durasi_s, 30.0))
    _sim.compute()

    skor = _sim.output['urgensi']
    if skor < 33:
        label = 'aman'
    elif skor < 66:
        label = 'siaga'
    else:
        label = 'bahaya'
    return skor, label


class StatusStabilizer:
    """
    Mencegah alarm 'kedip-kedip' akibat flicker deteksi sesaat (satu frame
    salah deteksi lalu balik normal). Status baru harus konsisten muncul
    beberapa kali berturut-turut sebelum benar-benar dianggap berubah.

    Sengaja ASIMETRIS: naik ke status lebih berbahaya butuh sedikit
    konfirmasi saja (reaksi cepat ke bahaya), tapi turun ke status lebih
    aman butuh lebih banyak konfirmasi (jangan buru-buru bilang "aman").
    Ini menjawab langsung salah satu keterbatasan yang paling penting:
    false alarm berlebihan adalah alasan utama sistem proximity gagal
    dipakai di lapangan nyata -- orang jadi mengabaikan atau mematikannya.
    """

    def __init__(self, ambang_naik=2, ambang_turun=3):
        self.ambang_naik = ambang_naik
        self.ambang_turun = ambang_turun
        self.status_stabil = 'aman'
        self._calon_status = None
        self._hitung = 0

    def update(self, status_mentah):
        naik = TINGKATAN.index(status_mentah) > TINGKATAN.index(self.status_stabil)
        ambang = self.ambang_naik if naik else self.ambang_turun

        if status_mentah == self._calon_status:
            self._hitung += 1
        else:
            self._calon_status = status_mentah
            self._hitung = 1

        if status_mentah != self.status_stabil and self._hitung >= ambang:
            self.status_stabil = status_mentah

        return self.status_stabil


if __name__ == '__main__':
    skenario = [
        (12, 1, "Jauh, baru terdeteksi"),
        (5, 1, "Jarak sedang, baru lewat sebentar"),
        (5, 20, "Jarak SAMA PERSIS, tapi sudah lama di situ"),
        (1.5, 1, "Sudah sangat dekat meski baru terdeteksi"),
        (1.5, 20, "Sangat dekat DAN sudah lama"),
    ]

    print(f"{'Skenario':50s} | {'Skor':>6s} | Status")
    print("-" * 72)
    for jarak, durasi, deskripsi in skenario:
        skor, label = evaluate_urgency(jarak, durasi)
        print(f"{deskripsi:50s} | {skor:6.1f} | {label}")

    print("\n--- Demo StatusStabilizer (anti false-alarm) ---")
    s = StatusStabilizer()
    urutan_demo = ['aman', 'aman', 'bahaya', 'aman', 'bahaya', 'bahaya',
                   'bahaya', 'aman', 'aman', 'aman']
    for mentah in urutan_demo:
        stabil = s.update(mentah)
        tanda = "  <- flicker diabaikan" if mentah == 'bahaya' and stabil == 'aman' else ""
        print(f"  input={mentah:8s} -> status stabil={stabil:8s}{tanda}")
