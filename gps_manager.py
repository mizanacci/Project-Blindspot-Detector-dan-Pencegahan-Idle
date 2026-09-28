import time


class GPSManager:
    """Selects the best GPS source while keeping NEO-6M as the primary source."""

    def __init__(self, neo6m=None, phone=None, phone_timeout_s=5.0, phone_max_accuracy_m=30.0):
        self.neo6m = neo6m
        self.phone = phone
        self.phone_timeout_s = phone_timeout_s
        self.phone_max_accuracy_m = phone_max_accuracy_m

    def _normalize_neo6m(self, result):
        if not isinstance(result, dict):
            return {"fix": False, "source": None, "latitude": None, "longitude": None, "lat": None, "lon": None, "status": "GPS NO DATA"}

        fix = bool(result.get("fix") in (1, True, "1", "true", "True"))
        if not fix:
            return {
                "fix": False,
                "source": None,
                "latitude": None,
                "longitude": None,
                "lat": None,
                "lon": None,
                "status": result.get("status") or "GPS UART NO DATA",
            }

        lat = result.get("lat")
        lon = result.get("lon")
        if lat is None and result.get("latitude") is not None:
            lat = result.get("latitude")
        if lon is None and result.get("longitude") is not None:
            lon = result.get("longitude")

        return {
            "fix": True,
            "source": "neo6m",
            "latitude": lat,
            "longitude": lon,
            "lat": lat,
            "lon": lon,
            "accuracy_m": result.get("accuracy_m"),
            "altitude_m": result.get("altitude_m"),
            "speed_mps": result.get("speed_mps"),
            "timestamp": result.get("timestamp"),
            "status": result.get("status") or "GPS FIX AKTIF",
        }

    def _normalize_phone(self, result):
        if not isinstance(result, dict):
            return {"fix": False, "source": None, "latitude": None, "longitude": None, "lat": None, "lon": None, "status": "PHONE GPS NO DATA"}

        if not result.get("fix"):
            return {
                "fix": False,
                "source": None,
                "latitude": None,
                "longitude": None,
                "lat": None,
                "lon": None,
                "status": result.get("status") or "PHONE GPS NO DATA",
            }

        lat = result.get("latitude")
        lon = result.get("longitude")
        if lat is None and result.get("lat") is not None:
            lat = result.get("lat")
        if lon is None and result.get("lon") is not None:
            lon = result.get("lon")

        return {
            "fix": True,
            "source": "phone",
            "latitude": lat,
            "longitude": lon,
            "lat": lat,
            "lon": lon,
            "accuracy_m": result.get("accuracy_m"),
            "altitude_m": result.get("altitude_m"),
            "speed_mps": result.get("speed_mps"),
            "timestamp": result.get("timestamp"),
            "status": result.get("status") or "PHONE GPS FIX ACTIVE",
        }

    def get_gps(self):
        if self.neo6m is not None:
            neo_result = self.neo6m.baca_lokasi(maks_baris=15)
            neo_norm = self._normalize_neo6m(neo_result)
            if neo_norm["fix"]:
                return neo_norm

        if self.phone is not None:
            if hasattr(self.phone, "get_latest_for_manager"):
                phone_result = self.phone.get_latest_for_manager()
            elif hasattr(self.phone, "get_latest"):
                phone_result = self.phone.get_latest()
            else:
                phone_result = {"fix": False, "source": None, "status": "PHONE GPS NO DATA"}
            phone_norm = self._normalize_phone(phone_result)
            if phone_norm["fix"]:
                return phone_norm

        return {
            "fix": False,
            "source": None,
            "latitude": None,
            "longitude": None,
            "lat": None,
            "lon": None,
            "accuracy_m": None,
            "altitude_m": None,
            "speed_mps": None,
            "timestamp": None,
            "status": "NO VALID GPS FIX",
            "updated_at": time.time(),
        }
