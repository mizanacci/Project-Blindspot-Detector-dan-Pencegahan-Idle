import csv
import numpy as np

CSV_FILE = "calibration_samples.csv"


def load_data():
    data = []

    with open(CSV_FILE, newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            data.append({
                "jarak": float(row["jarak_aktual_m"]),
                "y2": float(row["y2"])
            })

    # Urutkan berdasarkan y2 dari kecil -> besar
    # y2 kecil = orang jauh
    # y2 besar = orang dekat
    data.sort(key=lambda x: x["y2"])

    return data


def linear_interpolation(y, data):
    ys = np.array([d["y2"] for d in data])
    ds = np.array([d["jarak"] for d in data])

    # Di luar rentang kalibrasi -> clamp
    if y <= ys[0]:
        return ds[0]

    if y >= ys[-1]:
        return ds[-1]

    # Cari interval
    for i in range(len(ys) - 1):

        y1 = ys[i]
        y2 = ys[i + 1]

        d1 = ds[i]
        d2 = ds[i + 1]

        if y1 <= y <= y2:

            t = (y - y1) / (y2 - y1)

            return d1 + t * (d2 - d1)

    return ds[-1]


def rmse(actual, predicted):
    actual = np.array(actual)
    predicted = np.array(predicted)

    return np.sqrt(np.mean((actual - predicted) ** 2))


data = load_data()

print("\n=== KALIBRASI INTERPOLASI 8 TITIK ===")
print(f"Jumlah sampel : {len(data)}")

print("\nData terurut berdasarkan y2:")
print("y2 (px) | Jarak aktual")

for d in data:
    print(f"{d['y2']:7.2f} | {d['jarak']:6.2f} m")


print("\n=== VALIDASI PADA TITIK KALIBRASI ===")

actual = []
predicted = []

for d in data:

    pred = linear_interpolation(d["y2"], data)

    actual.append(d["jarak"])
    predicted.append(pred)

    error = pred - d["jarak"]

    print(
        f"y2={d['y2']:7.2f} px"
        f" | aktual={d['jarak']:5.2f} m"
        f" | prediksi={pred:5.2f} m"
        f" | error={error:+.3f} m"
    )


print(f"\nRMSE = {rmse(actual, predicted):.3f} meter")


print("\n=== PREDIKSI ANTAR TITIK ===")

test_y2 = [
    250,
    260,
    270,
    280,
    290,
    300,
    310,
    320,
    330,
    340,
    350,
    360,
    370,
    380,
    390,
    400,
    410,
    420,
    430,
    440,
    450,
    460
]

for y in test_y2:

    jarak = linear_interpolation(y, data)

    print(
        f"y2 = {y:3d} px"
        f" -> jarak ≈ {jarak:.2f} m"
    )

