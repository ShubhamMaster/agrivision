/* ===================================================================
   AgriVision — front-end behaviour.

   1. Live AI price helper on the "add crop" form
   2. Photo preview before upload
   3. Comparison tray on the marketplace
   4. Price trend + forecast chart (Chart.js)
   =================================================================== */

document.addEventListener("DOMContentLoaded", function () {
  initPriceHelper();
  initPhotoPreview();
  initCompareTray();
  initTrendChart();
  initChatScroll();
  initGallery();
});

/* -------------------------------------------------------------------
   Lot gallery: clicking a thumbnail swaps the main plate.
   Keyboard accessible, since the thumbnails are the only way to see the
   other photographs of the lot.
   ------------------------------------------------------------------- */
function initGallery() {
  const strip = document.querySelector("[data-gallery]");
  const main = document.getElementById("galleryMain");
  if (!strip || !main) return;

  const thumbs = Array.from(strip.querySelectorAll(".av-thumb"));

  function show(thumb) {
    main.src = thumb.src;
    thumbs.forEach(t => t.classList.toggle("is-active", t === thumb));
  }

  thumbs.forEach(t => {
    t.addEventListener("click", () => show(t));
    t.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); show(t); }
    });
  });
}

/* -------------------------------------------------------------------
   1. Live price suggestion while the farmer fills the listing form
   ------------------------------------------------------------------- */
function initPriceHelper() {
  const box = document.getElementById("priceHelper");
  if (!box) return;

  const cropSel = document.getElementById("crop_name");
  const district = document.getElementById("district");
  const state = document.getElementById("state");
  const organic = document.getElementById("organic");
  const askInput = document.getElementById("expected_price");
  const endpoint = box.dataset.endpoint;

  let lastBand = null;

  async function refresh() {
    if (!cropSel || !cropSel.value) {
      box.innerHTML = '<div class="text-muted small">Choose a crop to see the AI price suggestion.</div>';
      return;
    }
    box.innerHTML = '<div class="text-muted small"><span class="spinner-border spinner-border-sm"></span> Analysing market data…</div>';

    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          crop_name: cropSel.value,
          district: district ? district.value : "",
          state: state ? state.value : "",
          organic: organic ? organic.checked : false
        })
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "failed");
      lastBand = data;
      render(data);
    } catch (e) {
      box.innerHTML = '<div class="text-muted small">Price suggestion is unavailable right now.</div>';
    }
  }

  function render(d) {
    const certLine = d.certificate_required
      ? '<div class="alert alert-warning py-2 px-3 small mb-2 mt-2"><i class="bi bi-patch-exclamation"></i> ' +
        'This crop needs a quality certificate. You can upload it right after creating the listing.</div>'
      : "";

    box.innerHTML = `
      <div class="d-flex justify-content-between align-items-center">
        <strong class="text-success"><i class="bi bi-cpu"></i> AI suggested price</strong>
        <span class="badge bg-${d.demand.colour}">${d.demand.label} · ${Math.round(d.demand.index)}/100</span>
      </div>
      <div class="display-6 fw-bold text-success my-1">₹${Number(d.recommended).toLocaleString("en-IN")}
        <span class="fs-6 fw-normal text-muted">/quintal</span></div>
      <div class="small text-muted">Fair band ₹${Number(d.min).toLocaleString("en-IN")} – ₹${Number(d.max).toLocaleString("en-IN")}</div>
      <hr class="my-2">
      <div class="small"><strong>How this was calculated</strong></div>
      <ul class="small ps-3 mb-1">
        ${d.factors.map(f => `<li>${f.name}: <strong>${f.effect}</strong> <span class="text-muted">— ${f.note}</span></li>`).join("")}
      </ul>
      <div class="small text-muted">Base: ${d.source}</div>
      ${certLine}
      <button type="button" class="btn btn-sm btn-outline-success mt-2 w-100" id="useAiPrice">
        <i class="bi bi-magic"></i> Use ₹${Number(d.recommended).toLocaleString("en-IN")} as my price
      </button>
      <div id="askFeedback" class="small mt-2"></div>`;

    const btn = document.getElementById("useAiPrice");
    if (btn && askInput) {
      btn.addEventListener("click", () => { askInput.value = d.recommended; checkAsk(); });
    }
    checkAsk();
  }

  function checkAsk() {
    const fb = document.getElementById("askFeedback");
    if (!fb || !lastBand || !askInput || !askInput.value) return;
    const v = parseFloat(askInput.value);
    if (isNaN(v)) return;
    if (v < lastBand.min) {
      fb.className = "small mt-2 text-warning";
      fb.innerHTML = `<i class="bi bi-arrow-down-circle"></i> ₹${Math.round(lastBand.min - v).toLocaleString("en-IN")}/quintal below the fair band — you may be under-selling.`;
    } else if (v > lastBand.max) {
      fb.className = "small mt-2 text-danger";
      fb.innerHTML = `<i class="bi bi-arrow-up-circle"></i> ₹${Math.round(v - lastBand.max).toLocaleString("en-IN")}/quintal above the fair band — buyers may skip this listing.`;
    } else {
      fb.className = "small mt-2 text-success";
      fb.innerHTML = '<i class="bi bi-check-circle"></i> Inside the AI fair band. Good pricing.';
    }
  }

  [cropSel, district, state].forEach(el => el && el.addEventListener("change", refresh));
  if (organic) organic.addEventListener("change", refresh);
  if (askInput) askInput.addEventListener("input", checkAsk);
  refresh();
}

/* -------------------------------------------------------------------
   2. Preview the chosen photos before uploading
   ------------------------------------------------------------------- */
function initPhotoPreview() {
  const input = document.getElementById("photos");
  const target = document.getElementById("photoPreview");
  if (!input || !target) return;

  input.addEventListener("change", () => {
    target.innerHTML = "";
    Array.from(input.files).slice(0, 5).forEach(file => {
      const img = document.createElement("img");
      img.className = "av-thumb me-2 mb-2 border";
      img.src = URL.createObjectURL(file);
      img.onload = () => URL.revokeObjectURL(img.src);
      target.appendChild(img);
    });
    if (input.files.length) {
      const note = document.createElement("div");
      note.className = "small text-muted";
      note.textContent = input.files.length + " photo(s) selected — the AI will grade the lot from these.";
      target.appendChild(note);
    }
  });
}

/* -------------------------------------------------------------------
   3. Comparison tray on the marketplace
   ------------------------------------------------------------------- */
function initCompareTray() {
  const boxes = document.querySelectorAll(".av-compare");
  const bar = document.getElementById("compareBar");
  if (!boxes.length || !bar) return;

  const count = document.getElementById("compareCount");
  const link = document.getElementById("compareLink");

  function update() {
    const ids = Array.from(boxes).filter(b => b.checked).map(b => b.value);
    if (!ids.length) { bar.style.display = "none"; return; }
    bar.style.display = "block";
    count.textContent = ids.length;
    link.href = link.dataset.base + "?" + ids.map(i => "id=" + i).join("&");
    if (ids.length > 4) {
      boxes.forEach(b => { if (!b.checked) b.disabled = true; });
    } else {
      boxes.forEach(b => b.disabled = false);
    }
  }
  boxes.forEach(b => b.addEventListener("change", update));
  const clear = document.getElementById("compareClear");
  if (clear) clear.addEventListener("click", () => {
    boxes.forEach(b => { b.checked = false; b.disabled = false; });
    update();
  });
}

/* -------------------------------------------------------------------
   4. Price history + forecast chart
   ------------------------------------------------------------------- */
function initTrendChart() {
  const canvas = document.getElementById("trendChart");
  if (!canvas || typeof Chart === "undefined") return;

  const url = canvas.dataset.url;
  fetch(url).then(r => r.json()).then(d => {
    if (!d.ok) return;

    const histLabels = d.history.map(p => p.label);
    const fcLabels = d.forecast.map(p => p.label);
    const labels = histLabels.concat(fcLabels);

    const hist = d.history.map(p => p.price);
    const pad = new Array(hist.length - 1).fill(null);
    const fc = pad.concat([hist[hist.length - 1]], d.forecast.map(p => p.price));

    new Chart(canvas, {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Actual modal price (₹/quintal)",
            data: hist,
            borderColor: "#1f6b3b",
            backgroundColor: "rgba(31,107,59,.12)",
            fill: true, tension: .3, pointRadius: 2
          },
          {
            label: "Forecast",
            data: fc,
            borderColor: "#f0a500",
            borderDash: [6, 4],
            fill: false, tension: .3, pointRadius: 3
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom" },
          tooltip: {
            callbacks: {
              label: ctx => ctx.dataset.label + ": ₹" +
                Number(ctx.parsed.y).toLocaleString("en-IN")
            }
          }
        },
        scales: {
          y: { ticks: { callback: v => "₹" + Number(v).toLocaleString("en-IN") } }
        }
      }
    });

    const arrivalCanvas = document.getElementById("arrivalChart");
    if (arrivalCanvas) {
      new Chart(arrivalCanvas, {
        type: "bar",
        data: {
          labels: histLabels,
          datasets: [{
            label: "Weekly mandi arrivals (quintal)",
            data: d.history.map(p => p.arrivals),
            backgroundColor: "rgba(107,79,58,.65)"
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false } }
        }
      });
    }
  }).catch(() => {});
}

/* -------------------------------------------------------------------
   5. Keep the deal chat scrolled to the newest message
   ------------------------------------------------------------------- */
function initChatScroll() {
  const chat = document.querySelector(".av-chat");
  if (chat) chat.scrollTop = chat.scrollHeight;
}
