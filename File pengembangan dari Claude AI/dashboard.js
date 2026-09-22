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

function renderEvents(events) {
  const el = document.getElementById("event-list");
  if (!events || events.length === 0) {
    el.innerHTML = '<span class="event-empty">Belum ada perubahan status</span>';
    return;
  }
  el.innerHTML = events
    .map((e) => `<span class="event-item ${e.status}">${e.waktu} — ${LABEL_STATUS[e.status] || e.status}</span>`)
    .join("");
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
    ? "\u2014 g" : `${data.getaran_g.toFixed(3)} g`;

  const gpsEl = document.getElementById("sensor-gps");
  if (belumAdaData || !data.gps_fix) {
    gpsEl.textContent = "Tidak ada fix";
  } else {
    gpsEl.textContent = `${data.gps_lat.toFixed(5)}, ${data.gps_lon.toFixed(5)}`;
  }

  document.getElementById("sensor-last-update").textContent = belumAdaData
    ? "Menunggu data sensor\u2026"
    : `Update terakhir ${data.sensor_last_update}`;
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

    renderEvents(data.events);
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
