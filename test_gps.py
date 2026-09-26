"""Live NEO-6M UART diagnostic; run outdoors for a satellite fix."""

import os
import sys

SENSOR_DIR = os.path.join(os.path.dirname(__file__), "File pengembangan dari Claude AI")
if SENSOR_DIR not in sys.path:
    sys.path.insert(0, SENSOR_DIR)

from gps_neo6m import GPSNeo6M


def main():
    gps = GPSNeo6M(port="/dev/serial0", baud=9600, timeout=0.05)
    try:
        print("UART: OPEN")
        print("Bawa antena GPS ke area terbuka, menghadap ke atas.")
        for attempt in range(12):
            result = gps.baca_lokasi(maks_baris=5)
            print(
                f"[{attempt + 1:02d}] UART={result['uart_status']} "
                f"NMEA={'RECEIVED' if result['nmea_received'] else 'NO DATA'} "
                f"GGA={'RECEIVED' if result['gga_received'] else 'NO'} "
                f"RMC={'RECEIVED' if result['rmc_received'] else 'NO'} "
                f"FIX={'YES' if result['fix'] else 'NO'} "
                f"SAT={result['satellites'] or '-'}"
            )
            if result["fix"]:
                print(f"LAT={result['lat']:.6f} LON={result['lon']:.6f}")
                break
        else:
            print("Belum mendapat fix. Ulangi di area terbuka beberapa menit.")
    finally:
        gps.close()


if __name__ == "__main__":
    main()
