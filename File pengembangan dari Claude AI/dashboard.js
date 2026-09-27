const LABEL_STATUS = { aman: "AMAN", siaga: "SIAGA", bahaya: "BAHAYA" };
const SUBTEKS_STATUS = {
  aman: "Area kerja aman dipantau",
  siaga: "Ada orang di area perhatian",
  bahaya: "Segera perlambat / hentikan alat",
};

const vibrationCtx = document.getElementById("vibration-chart")?.getContext("2d");
const tiltCtx = document.getElementById("tilt-chart")?.getContext("2d");
let routeMap = null;
let routeLayer = null;
let routeMarkers = [];

function setFillText(canvas, value) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#edf2f7";
  ctx.font = "14px IBM Plex Sans";
  ctx.fillText(value, 10, 22);
}

function formatDurasi(detik) {
  const bulat = Math.max(0, Math.floor(detik));
  const menit = Math.floor(bulat / 60);
  const sisaDetik = bulat % 60;
  return `${String(menit).padStart(2, "0")}:${String(sisaDetik).padStart(2, "0")}`;
}

function perbaruiJam() {
  const clock = document.getElementById("clock");
  if (clock) clock.textContent = new Date().toLocaleTimeString("id-ID", { hour12: false });
}

function renderEvents(events, history) {
  const el = document.getElementById("event-list");
  const historyItems = Array.isArray(history) ? history : [];
  const eventItems = Array.isArray(events) ? events : [];
  const items = [...eventItems, ...historyItems.slice(0, 5)].slice(0, 8);

  if (!el) return;
  if (items.length === 0) {
    el.innerHTML = '<span class="event-empty">Belum ada perubahan status</span>';
    return;
  }

  el.innerHTML = items.map((item) => {
    if (item.status) {
      return `<span class="event-item ${item.status}">${item.waktu} — ${LABEL_STATUS[item.status] || item.status}</span>`;
    }
    const status = item.status_stabil || item.status_mentah || "status";
    return `<span class="event-item ${status}">${item.timestamp} — ${status.toUpperCase()} / ${Number(item.jarak_m || 0).toFixed(1)}m</span>`;
  }).join("");
}

function renderHistoryTable(history) {
  const el = document.getElementById("history-list");
  if (!el) return;
  const items = Array.isArray(history) ? history : [];
  if (items.length === 0) {
    el.innerHTML = '<tr><td colspan="10">Belum ada data histori</td></tr>';
    return;
  }
  el.innerHTML = items.map((item) => {
    const tilt = item.tilt_status ? `${Number(item.tilt_x_deg || 0).toFixed(1)} / ${Number(item.tilt_y_deg || 0).toFixed(1)} ${item.tilt_status}` : "--";
    const gps = item.gps_fix ? `${Number(item.gps_lat || 0).toFixed(4)}, ${Number(item.gps_lon || 0).toFixed(4)}` : "NO FIX";
    return `<tr>
      <td>${item.timestamp || "--"}</td>
      <td class="history-status ${item.status_stabil || ""}">${(item.status_stabil || "--").toUpperCase()}</td>
      <td>${item.jarak_m || "--"} m</td>
      <td>${item.jumlah_orang || 0}</td>
      <td>${item.status_mesin || "--"}</td>
      <td>${item.status_idle || "--"}</td>
      <td>${item.getaran_g || "--"}</td>
      <td>${item.sw420_terdeteksi === undefined ? "--" : item.sw420_terdeteksi}</td>
      <td>${tilt}</td>
      <td>${gps}</td>
    </tr>`;
  }).join("");
}

function renderStartupChecks(checks) {
  const el = document.getElementById("checklist-list");
  if (!el) return;
  const items = Array.isArray(checks) ? checks : [];
  if (items.length === 0) {
    el.innerHTML = '<li class="checklist-item">Menunggu hasil checklist startup…</li>';
    return;
  }
  el.innerHTML = items.map((item) => `
    <li class="checklist-item ${item.ok ? 'ok' : 'bad'} ${item.critical ? 'critical' : ''}">
      ${item.label}: ${item.ok ? 'OK' : 'PERIKSA'} ${item.critical ? ' [KRITIS]' : ' [OPSIONAL]'}
    </li>
  `).join("");
}

function drawSimpleLineChart(context, values, color, threshold) {
  if (!context) return;
  const canvas = context.canvas;
  const { width, height } = canvas;
  context.clearRect(0, 0, width, height);
  context.strokeStyle = "#2f3a44";
  context.lineWidth = 1;
  context.beginPath();
  context.moveTo(12, 10);
  context.lineTo(12, height - 12);
  context.lineTo(width - 10, height - 12);
  context.stroke();

  if (Array.isArray(values) && values.length > 0) {
    const maxValue = Math.max(...values, threshold || 0, 1);
    context.beginPath();
    values.forEach((value, index) => {
      const x = 12 + (index / Math.max(values.length - 1, 1)) * (width - 22);
      const y = height - 12 - (Number(value) / maxValue) * (height - 22);
      if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
    });
    context.strokeStyle = color;
    context.lineWidth = 2;
    context.stroke();
  }

  if (threshold) {
    const y = height - 12 - (threshold / Math.max(...values, threshold, 1)) * (height - 22);
    context.beginPath();
    context.moveTo(12, y);
    context.lineTo(width - 10, y);
    context.strokeStyle = "rgba(245,166,35,0.7)";
    context.setLineDash([6, 4]);
    context.stroke();
    context.setLineDash([]);
  }
}

function renderSensorTambahan(data) {
  const belumAdaData = !data.sensor_last_update;

  document.getElementById("sensor-mesin").textContent = belumAdaData ? "\u2014" : (data.status_mesin || "\u2014");
  document.getElementById("sensor-idle").textContent = belumAdaData ? "\u2014" : (data.status_idle || "\u2014");
  document.getElementById("sensor-durasi-idle").textContent = belumAdaData ? "--:--" : formatDurasi(data.durasi_idle_s);
  document.getElementById("sensor-getaran").textContent = belumAdaData ? "\u2014 g" : `${Number(data.getaran_g || 0).toFixed(3)} g`;

  const tiltX = belumAdaData ? 0 : Number(data.tilt_x_deg || 0);
  const tiltY = belumAdaData ? 0 : Number(data.tilt_y_deg || 0);
  const tiltStatus = belumAdaData ? "NORMAL" : (data.tilt_status || "NORMAL");
  document.getElementById("sensor-tilt").textContent = `X: ${tiltX.toFixed(1)}° / Y: ${tiltY.toFixed(1)}° / STATUS: ${tiltStatus}`;

  const gpsEl = document.getElementById("sensor-gps");
  const gpsDetailEl = document.getElementById("sensor-gps-detail");
  const gpsSatellitesEl = document.getElementById("sensor-gps-satellites");
  const gpsMapEl = document.getElementById("sensor-gps-map");
  gpsSatellitesEl.textContent = data.gps_satellites ?? "--";
  if (belumAdaData || !data.gps_fix) {
    gpsEl.textContent = data.gps_status || "GPS belum dicek";
    gpsDetailEl.textContent = "Lat: ---.------° / Lon: ---.------°";
    gpsMapEl.hidden = true;
    gpsMapEl.removeAttribute("href");
  } else {
    const lat = Number(data.gps_lat || 0);
    const lon = Number(data.gps_lon || 0);
    gpsEl.textContent = "FIX AKTIF";
    gpsDetailEl.textContent = `Lat: ${lat.toFixed(6)}° / Lon: ${lon.toFixed(6)}°`;
    gpsMapEl.href = `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=17/${lat}/${lon}`;
    gpsMapEl.hidden = false;
  }

  document.getElementById("sensor-last-update").textContent = belumAdaData ? "Menunggu data sensor…" : `Update terakhir ${data.sensor_last_update}`;

  const banner = document.getElementById("startup-banner");
  if (banner) banner.textContent = data.operator_message || "Sistem siap — menunggu operator menekan start";

  const startButton = document.getElementById("start-button");
  if (startButton) {
    const active = (data.operator_message || "").includes("aktif");
    startButton.disabled = active || data.start_requested;
    startButton.textContent = active ? "DETEKSI AKTIF" : (data.start_requested ? "MENUNGGU START" : "MULAI DETEKSI");
  }

  const cameraHealth = document.getElementById("health-camera");
  const yoloHealth = document.getElementById("health-yolo");
  const mpuHealth = document.getElementById("health-mpu");
  const swHealth = document.getElementById("health-sw420");
  const gpsHealth = document.getElementById("health-gps");
  if (cameraHealth) cameraHealth.textContent = "OK";
  if (yoloHealth) yoloHealth.textContent = "OK";
  if (mpuHealth) mpuHealth.textContent = data.tilt_status ? "OK" : "OFFLINE";
  if (swHealth) swHealth.textContent = "OK";
  if (gpsHealth) gpsHealth.textContent = data.gps_fix ? "FIX ACTIVE" : (data.gps_status || "NO DATA");
}

function updateSummaryCards(data) {
  const safety = data.safety || {};
  const blindspot = data.status || "aman";
  const trip = safety.trip || { active: false, total_distance_km: 0.0, track_points: 0 };

  document.getElementById("blindspot-count").textContent = data.jumlah_orang ?? 0;
  document.getElementById("blindspot-nearest").textContent = `${Number(data.jarak_m || 0).toFixed(1)} m`;
  document.getElementById("blindspot-duration").textContent = formatDurasi(data.durasi_s);
  document.getElementById("blindspot-status").textContent = LABEL_STATUS[blindspot] || blindspot.toUpperCase();

  document.getElementById("machine-gps-status").textContent = data.gps_fix ? "FIX ACTIVE" : (data.gps_status || "MENUNGGU FIX");
  document.getElementById("machine-stationary-duration").textContent = `${Number(data.safety?.stationary_vibration?.duration_s || 0).toFixed(0)} s`;
  document.getElementById("machine-vibration").textContent = `${Number(data.getaran_g || 0).toFixed(3)} g`;
  document.getElementById("machine-last-event").textContent = safety.stationary_vibration ? safety.stationary_vibration.reason || "STATIONARY" : "--";

  document.getElementById("terrain-risk").textContent = safety.terrain_stability ? (safety.terrain_stability.severity || "WARNING") : "NORMAL";
  document.getElementById("terrain-tilt-x").textContent = `${Number(data.tilt_x_deg || 0).toFixed(1)}°`;
  document.getElementById("terrain-tilt-y").textContent = `${Number(data.tilt_y_deg || 0).toFixed(1)}°`;
  document.getElementById("terrain-event-count").textContent = safety.terrain_stability ? "1" : "0";

  document.getElementById("route-start").textContent = trip.start_time || "--";
  document.getElementById("route-end").textContent = trip.end_time || (trip.active ? "ACTIVE" : "--");
  document.getElementById("route-distance").textContent = `${Number(trip.total_distance_km || 0).toFixed(2)} km`;
  document.getElementById("route-points").textContent = trip.track_points || 0;
}

function renderMap(data) {
  if (typeof window.L === "undefined") return;
  const mapContainer = document.getElementById("route-map");
  if (!mapContainer) return;

  if (!routeMap) {
    routeMap = L.map("route-map", { zoomControl: true }).setView([-6.2, 106.8], 12);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(routeMap);
    routeLayer = L.layerGroup().addTo(routeMap);
  }

  routeLayer.clearLayers();
  const points = Array.isArray(data.route_points) ? data.route_points : [];
  if (points.length > 1) {
    const latlngs = points.map((p) => [p.lat, p.lon]);
    L.polyline(latlngs, { color: "#f5a623", weight: 4 }).addTo(routeLayer);
  }

  if (data.gps_fix && data.gps_lat && data.gps_lon) {
    const currentMarker = L.marker([Number(data.gps_lat), Number(data.gps_lon)]).addTo(routeLayer);
    currentMarker.bindPopup("Current machine position");
  }

  if (points.length > 0) {
    const first = points[0];
    const startMarker = L.marker([first.lat, first.lon], { icon: L.divIcon({ className: "map-pin-start", html: "S" }) }).addTo(routeLayer);
    startMarker.bindPopup("START");
  }

  document.getElementById("map-status").textContent = data.gps_fix ? "FIX ACTIVE" : "NO FIX";
}

function renderCharts(data) {
  const vibrationValues = Array.isArray(data.vibration_history) ? data.vibration_history.map((v) => Number(v.value || 0)) : [];
  const tiltValuesX = Array.isArray(data.tilt_history) ? data.tilt_history.map((v) => Number(v.tilt_x || 0)) : [];
  const tiltValuesY = Array.isArray(data.tilt_history) ? data.tilt_history.map((v) => Number(v.tilt_y || 0)) : [];
  if (vibrationCtx) drawSimpleLineChart(vibrationCtx, vibrationValues, "#4db6ff", 0.15);
  if (tiltCtx) {
    const combined = tiltValuesX.length > 0 ? tiltValuesX.map((v, idx) => Math.max(Math.abs(v), Math.abs(tiltValuesY[idx] || 0))) : [];
    drawSimpleLineChart(tiltCtx, combined, "#f5a623", 12);
  }
  const vibrationHeader = document.getElementById("vibration-header");
  if (vibrationHeader) vibrationHeader.textContent = vibrationValues.length ? "ACTIVE" : "MPU6050 OFFLINE";
  const tiltHeader = document.getElementById("tilt-header");
  if (tiltHeader) tiltHeader.textContent = tiltValuesX.length ? "NORMAL" : "NORMAL";
}

async function perbaruiStatus() {
  try {
    const res = await fetch("/status", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const panel = document.getElementById("status-panel");
    panel.classList.remove("aman", "siaga", "bahaya");
    panel.classList.add(data.status);

    document.getElementById("status-word").textContent = LABEL_STATUS[data.status] || data.status.toUpperCase();
    document.getElementById("status-sub").textContent = SUBTEKS_STATUS[data.status] || "";
    document.getElementById("metric-jarak").textContent = `${Number(data.jarak_m || 0).toFixed(1)} m`;
    document.getElementById("metric-durasi").textContent = formatDurasi(data.durasi_s);
    document.getElementById("metric-orang").textContent = data.jumlah_orang;

    renderEvents(data.events, data.history);
    renderHistoryTable(data.history);
    renderStartupChecks(data.startup_checks);
    renderSensorTambahan(data);
    updateSummaryCards(data);
    renderMap(data);
    renderCharts(data);

    document.getElementById("live-dot").style.background = "var(--status-aman)";
    document.getElementById("live-label").textContent = "live";
  } catch (err) {
    document.getElementById("live-dot").style.background = "var(--status-bahaya)";
    document.getElementById("live-label").textContent = "putus";
    console.error("Gagal ambil status dari server:", err);
  }
}

perbaruiJam();
perbaruiStatus();
setInterval(perbaruiJam, 1000);
setInterval(perbaruiStatus, 500);

for (const button of document.querySelectorAll(".download-btn")) {
  button.addEventListener("click", async () => {
    const filename = button.dataset.file;
    if (!filename) return;
    const url = `/download/${encodeURIComponent(filename)}`;
    window.open(url, "_blank");
  });
}

document.getElementById("trip-start-button")?.addEventListener("click", async () => {
  try {
    await fetch("/trip/start", { method: "POST" });
  } catch (err) { console.error("Gagal memulai perjalanan:", err); }
});

document.getElementById("trip-end-button")?.addEventListener("click", async () => {
  try {
    await fetch("/trip/end", { method: "POST" });
  } catch (err) { console.error("Gagal mengakhiri perjalanan:", err); }
});

document.getElementById("start-button")?.addEventListener("click", async () => {
  const button = document.getElementById("start-button");
  button.disabled = true;
  try {
    await fetch("/start", { method: "POST" });
  } catch (err) {
    button.disabled = false;
    console.error("Gagal mengirim permintaan start:", err);
  }
});
