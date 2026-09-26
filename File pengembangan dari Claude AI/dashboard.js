// dashboard.js
// Polling sederhana ke endpoint /status setiap 500ms.

const LABEL_STATUS = { aman: "AMAN", siaga: "SIAGA", bahaya: "BAHAYA" };
const SUBTEKS_STATUS = {
  aman: "Area kerja aman dipantau",
  siaga: "Ada orang di area perhatian",
  bahaya: "Segera perlambat / hentikan alat",
};

function formatDurasi(detik) {
  const bulat = Math.max(0, Math.floor(detik));
  const menit = Math.floor(bulat / 60);
  const sisaDetik = bulat % 60;
  return `${String(menit).padStart(2, "0")}:${String(sisaDetik).padStart(2, "0")}`;
}

function perbaruiJam() {
  document.getElementById("clock").textContent =
    new Date().toLocaleTimeString("id-ID", { hour12: false });
}

function renderEvents(events, history) {
  const el = document.getElementById("event-list");
  const historyItems = Array.isArray(history) ? history : [];
  const eventItems = Array.isArray(events) ? events : [];

  const items = [...eventItems, ...historyItems.slice(0, 5)].slice(0, 8);

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

// Panel sensor tambahan (mesin/idle/GPS) -- render terpisah dari
// status blind spot, dan sengaja TIDAK mengubah warna panelnya
// sendiri jadi merah/kuning/hijau seperti status-panel utama.
function renderSensorTambahan(data) {
  const belumAdaData = !data.sensor_last_update;

  document.getElementById("sensor-mesin").textContent = belumAdaData
    ? "\u2014" : (data.status_mesin || "\u2014");
  document.getElementById("sensor-idle").textContent = belumAdaData
    ? "\u2014" : (data.status_idle || "\u2014");
  document.getElementById("sensor-durasi-idle").textContent = belumAdaData
    ? "--:--" : formatDurasi(data.durasi_idle_s);
  document.getElementById("sensor-getaran").textContent = belumAdaData
    ? "\u2014 g" : `${Number(data.getaran_g || 0).toFixed(3)} g`;

  const tiltX = belumAdaData ? 0 : Number(data.tilt_x_deg || 0);
  const tiltY = belumAdaData ? 0 : Number(data.tilt_y_deg || 0);
  const tiltStatus = belumAdaData ? "NORMAL" : (data.tilt_status || "NORMAL");
  document.getElementById("sensor-tilt").textContent = `X: ${tiltX.toFixed(1)}° / Y: ${tiltY.toFixed(1)}° / STATUS: ${tiltStatus}`;

  const gpsEl = document.getElementById("sensor-gps");
  const gpsDetailEl = document.getElementById("sensor-gps-detail");
  if (belumAdaData || !data.gps_fix) {
    gpsEl.textContent = "Tidak ada fix";
    gpsDetailEl.textContent = "Lat: ---.------° / Lon: ---.------°";
  } else {
    const lat = Number(data.gps_lat || 0);
    const lon = Number(data.gps_lon || 0);
    gpsEl.textContent = `FIX AKTIF`;
    gpsDetailEl.textContent = `Lat: ${lat.toFixed(6)}° / Lon: ${lon.toFixed(6)}°`;
  }

  document.getElementById("sensor-last-update").textContent = belumAdaData
    ? "Menunggu data sensor\u2026"
    : `Update terakhir ${data.sensor_last_update}`;

  const banner = document.getElementById("startup-banner");
  if (banner) {
    banner.textContent = data.operator_message || "Sistem siap — menunggu operator menekan start";
  }
}

async function perbaruiStatus() {
  try {
    const res = await fetch("/status", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const panel = document.getElementById("status-panel");
    panel.classList.remove("aman", "siaga", "bahaya");
    panel.classList.add(data.status);

    document.getElementById("status-word").textContent =
      LABEL_STATUS[data.status] || data.status.toUpperCase();
    document.getElementById("status-sub").textContent =
      SUBTEKS_STATUS[data.status] || "";

    document.getElementById("metric-jarak").textContent = `${data.jarak_m.toFixed(1)} m`;
    document.getElementById("metric-durasi").textContent = formatDurasi(data.durasi_s);
    document.getElementById("metric-orang").textContent = data.jumlah_orang;

    renderEvents(data.events, data.history);
    renderStartupChecks(data.startup_checks);
    renderSensorTambahan(data);

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
