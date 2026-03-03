// app.js
document.addEventListener("DOMContentLoaded", () => {
  // CONFIG
  const DANGER_FIELD = "danger";
  const CATEGORY_FIELD = "heritage_category";
  const CLUSTER_MIN_COUNT = 10;

  const DISABLE_CLUSTERING_AT_ZOOM = 6;
  const RADIUS_ZOOM6PLUS = 12;
  const RADIUS_ZOOM4TO5 = 25;
  const RADIUS_ZOOM0TO3 = 60;

  // DOT COLOURS
  const DANGER_RED = "#d32f2f";
  const CULTURAL_BLUE = "#1565c0";
  const NATURAL_GREEN = "#2e7d32";
  const MIXED_PURPLE = "#6a1b9a";
  const UNKNOWN_GRAY = "#6b7280";

  // TIMELINE CONFIG (slider, 100-year bins)
  const TIMELINE_MIN = -1400; // 1400 BC
  const TIMELINE_MAX = 2026; // 2026 AD
  const BIN_SIZE = 100;

  // If true: when a bin is selected, ALSO show sites with unknown/null dates.
  // If false: unknown dates are hidden when a bin is selected.
  const SHOW_UNKNOWN_DATES_WHEN_FILTERING = false;

  let activeBinStart = null; // null = no timeline filter

  // MAP SETUP
  const map = L.map("map", { preferCanvas: true, worldCopyJump: true }).setView(
    [20, 0],
    2,
  );

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(map);

  // CLUSTER SETUP
  function defaultClusterIcon(cluster) {
    const count = cluster.getChildCount();
    const sizeClass =
      count < 10
        ? "marker-cluster-small"
        : count < 100
          ? "marker-cluster-medium"
          : "marker-cluster-large";

    return new L.DivIcon({
      html: `<div><span>${count}</span></div>`,
      className: `marker-cluster ${sizeClass}`,
      iconSize: new L.Point(40, 40),
    });
  }

  const cluster = L.markerClusterGroup({
    chunkedLoading: true,
    chunkInterval: 50,
    chunkDelay: 10,

    disableClusteringAtZoom: DISABLE_CLUSTERING_AT_ZOOM,

    maxClusterRadius: (zoom) => {
      if (zoom >= DISABLE_CLUSTERING_AT_ZOOM) return RADIUS_ZOOM6PLUS;
      if (zoom >= 4) return RADIUS_ZOOM4TO5;
      return RADIUS_ZOOM0TO3;
    },

    spiderfyOnMaxZoom: true,
    showCoverageOnHover: false,

    iconCreateFunction: (cl) => {
      const count = cl.getChildCount();
      if (count < CLUSTER_MIN_COUNT) {
        return new L.DivIcon({
          html: "",
          className: "marker-cluster-hidden",
          iconSize: new L.Point(0, 0),
        });
      }
      return defaultClusterIcon(cl);
    },
  });

  map.addLayer(cluster);

  cluster.on("clusterclick", (e) => {
    if (e.layer.getChildCount() < CLUSTER_MIN_COUNT) e.layer.spiderfy();
  });

  function spiderfySmallClusters() {
    cluster.eachLayer((layer) => {
      if (layer && typeof layer.getChildCount === "function") {
        if (layer.getChildCount() < CLUSTER_MIN_COUNT) layer.spiderfy();
      }
    });
  }

  map.on("zoomend moveend", () => setTimeout(spiderfySmallClusters, 0));

  // HELPERS
  function escapeHtml(str) {
    return String(str)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function normCategory(cat) {
    return String(cat ?? "")
      .trim()
      .toLowerCase();
  }

  function isDangerous(v) {
    return Number(String(v ?? "").trim()) === 1;
  }

  function categoryColor(catRaw) {
    const cat = normCategory(catRaw);
    if (cat === "cultural") return CULTURAL_BLUE;
    if (cat === "natural") return NATURAL_GREEN;
    if (cat === "mixed") return MIXED_PURPLE;
    return UNKNOWN_GRAY;
  }

  // ---------------------------
  // DATE NORMALIZATION (BC/AD)
  // bc_ad can be null -> default AD
  // ---------------------------
  function toYearNumber(year, bcAd) {
    if (year == null || year === "") return null;

    const y = Number(year);
    if (!Number.isFinite(y)) return null;

    const era = String(bcAd ?? "AD")
      .trim()
      .toUpperCase(); // default AD if null
    return era === "BC" || era === "BCE" ? -Math.abs(y) : Math.abs(y);
  }

  // returns { start: number|null, end: number|null }
  function normalizeFeatureDate(props) {
    const d = props?.date ?? null;
    if (!d) return { start: null, end: null };

    const bcAd = d.BC_AD; // can be null

    let start = toYearNumber(d.start_date, bcAd);
    let end = toYearNumber(d.end_date, bcAd);

    // If only one side exists, treat as a single-year point
    if (start != null && end == null) end = start;
    if (start == null && end != null) start = end;

    // Ensure start <= end
    if (start != null && end != null && start > end)
      [start, end] = [end, start];

    return { start, end };
  }

	function rangesOverlap(start, end, binStart, binEndExclusive) {
	  if (start == null || end == null) return false;

	  // Treat feature as [start, end) (end exclusive)
	  // and bin as [binStart, binEndExclusive)
	  return start < binEndExclusive && end > binStart;
	}

  function timelinePasses(props) {
    if (activeBinStart == null) return true;

    const { start, end } = normalizeFeatureDate(props);
    if (start == null || end == null) return SHOW_UNKNOWN_DATES_WHEN_FILTERING;

    const binStart = activeBinStart;
    const binEndExclusive = Math.min(
      activeBinStart + BIN_SIZE,
      TIMELINE_MAX + 1,
    );

    return rangesOverlap(start, end, binStart, binEndExclusive);
  }

  function formatYear(y) {
    if (y < 0) return `${Math.abs(y)} BC`;
    return `${y} AD`;
  }

  function formatRange(binStart) {
    if (binStart == null) return "All dates";
    const end = Math.min(binStart + BIN_SIZE, TIMELINE_MAX);
    return `${formatYear(binStart)} → ${formatYear(end)}`;
  }

  // FILTER UI (categories panel)
  const toggleBtn = document.getElementById("togglePanelBtn");
  const panelBody = document.getElementById("panelBody");
  const statusLine = document.getElementById("statusLine");

  const chkCultural = document.getElementById("chkCultural");
  const chkNatural = document.getElementById("chkNatural");
  const chkMixed = document.getElementById("chkMixed");

  let minimized = false;

  toggleBtn?.addEventListener("click", () => {
    minimized = !minimized;
    panelBody.style.display = minimized ? "none" : "block";
    toggleBtn.textContent = minimized ? "+" : "–";
    toggleBtn.title = minimized ? "Expand" : "Minimize";
  });

  function shouldShow(categoryRaw) {
    const category = normCategory(categoryRaw);

    const c = chkCultural.checked;
    const n = chkNatural.checked;
    const m = chkMixed.checked;

    if (!c && !n && !m) return false;

    if (m && !c && !n) return category === "mixed";
    if (c && n) return true;
    if (c) return category === "cultural" || category === "mixed";
    if (n) return category === "natural" || category === "mixed";

    return false;
  }

  function filterLabel() {
    const c = chkCultural.checked;
    const n = chkNatural.checked;
    const m = chkMixed.checked;

    if (!c && !n && !m) return "None";
    if (m && !c && !n) return "Mixed";
    if (c && n) return "All";
    if (c) return "Cultural + Mixed";
    if (n) return "Natural + Mixed";
    return "None";
  }

  // TIMELINE UI (slider in top-left)
  function buildTimelineSliderUI() {
    const slider = document.getElementById("timelineSlider");
    const readout = document.getElementById("timelineReadout");
    const clearBtn = document.getElementById("timelineClear");
    if (!slider || !readout || !clearBtn) return;

    const steps = Math.floor((TIMELINE_MAX - TIMELINE_MIN) / BIN_SIZE);
    slider.min = "0";
    slider.max = String(steps);
    slider.step = "1";
    slider.value = "0";

    // Default to "All dates"
    activeBinStart = null;
    readout.textContent = `Timeline: ${formatRange(activeBinStart)}`;

    // Drag updates while sliding
    slider.addEventListener("input", () => {
      const idx = Number(slider.value);
      const binStart = TIMELINE_MIN + idx * BIN_SIZE;

      activeBinStart = binStart;
      readout.textContent = `Timeline: ${formatRange(activeBinStart)}`;
      renderFiltered();
    });

    // Clear back to all
    clearBtn.addEventListener("click", () => {
      activeBinStart = null;
      readout.textContent = `Timeline: ${formatRange(activeBinStart)}`;
      renderFiltered();
    });
  }

  // DATA + RENDER
  let allGeojsonData = null;
  let didInitialFit = false;

  function renderFiltered() {
    if (!allGeojsonData) return;

    cluster.clearLayers();
    let shown = 0;

    const geo = L.geoJSON(allGeojsonData, {
      filter: (feature) => {
        const props = feature?.properties || {};
        return shouldShow(props?.[CATEGORY_FIELD]) && timelinePasses(props);
      },

      pointToLayer: (feature, latlng) => {
        shown++;

        const props = feature.properties || {};

        const name = props.name_en ?? "(no name)";
        const country = props.states_name_en ?? "";
        const descHtml = props.short_description_en ?? "";
        const categoryText = props[CATEGORY_FIELD] ?? "";

        const dangerous = isDangerous(props[DANGER_FIELD]);
        const color = dangerous ? DANGER_RED : categoryColor(categoryText);

        const marker = L.circleMarker(latlng, {
          radius: 5.5,
          weight: 1,
          color: color,
          fillColor: color,
          fillOpacity: 0.85,
        });

        marker.bindTooltip(String(name), { direction: "top", sticky: true });

        // backend call on click
        marker.on("click", async () => {
          const { lat, lng } = marker.getLatLng();
          try {
            const res = await fetch("http://localhost:8000/api/aggregate", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                lat,
                lng,
                return_limit: 10,
                included_types: [
                  "park",
                  "tourist_attraction",
                  "museum",
                  "hiking_area",
                ],
              }),
            });
            const data = await res.json();
            console.log(data.places);
          } catch (err) {
            console.error("backend call failed", err);
          }
        });

        // POPUP IMAGE (lazy load on popup open)
        const pictureUrl = props.picture_url ?? "";
        const safeIdBase = (props.id_no ?? name)
          .toString()
          .replace(/\W+/g, "_");
        const imgId = `img_${safeIdBase}_${Math.random().toString(36).slice(2, 7)}`;

        const popupHtml = `
          <div class="popup-title-row">
            <div class="popup-title">${escapeHtml(name)}</div>
            ${dangerous ? `<span class="danger-badge">DANGEROUS</span>` : ``}
          </div>

          ${country ? `<div class="popup-country">${escapeHtml(country)}</div>` : ``}
          ${categoryText ? `<div class="popup-meta">${escapeHtml(categoryText)}</div>` : ``}

          ${
            pictureUrl
              ? `
            <img
              id="${imgId}"
              class="popup-img"
              alt="${escapeHtml(name)}"
              loading="lazy"
              referrerpolicy="no-referrer"
              src=""
            />
            <div id="${imgId}_note" class="popup-img-note">Loading image…</div>
          `
              : ``
          }

          <div class="popup-desc">${descHtml}</div>
        `;

        marker.bindPopup(popupHtml, { maxWidth: 520, closeButton: true });

        marker.on("popupopen", () => {
          if (!pictureUrl) return;

          const img = document.getElementById(imgId);
          const note = document.getElementById(`${imgId}_note`);
          if (!img || img.dataset.loaded === "1") return;

          img.onload = () => {
            img.dataset.loaded = "1";
            if (note) note.remove();
          };

          img.onerror = () => {
            img.dataset.loaded = "1";
            img.style.display = "none";
            if (note) note.textContent = "Image failed to load.";
          };

          img.src = pictureUrl;
        });

        return marker;
      },
    });

    cluster.addLayer(geo);

    // status line includes category + timeline
    statusLine.textContent = `Showing: ${filterLabel()} • Timeline: ${formatRange(activeBinStart)} • Points: ${shown}`;

    if (!didInitialFit) {
      didInitialFit = true;
      try {
        map.fitBounds(cluster.getBounds(), { padding: [20, 20] });
      } catch (e) {}
    }

    setTimeout(spiderfySmallClusters, 0);
  }

  [chkCultural, chkNatural, chkMixed].forEach((el) => {
    el.addEventListener("change", renderFiltered);
  });

  // Init timeline slider UI (requires timelineBox HTML in index.html)
  buildTimelineSliderUI();

  // Load GeoJSON
	fetch("/convert/sites.geojson")
	  .then((r) => {
		if (!r.ok) throw new Error(`HTTP ${r.status} while loading /convert/sites.geojson`);
		return r.json();
	  })
	  .then((data) => {
		allGeojsonData = data;
		window.__DEBUG_GEOJSON__ = data;
		renderFiltered();
	  })
	  .catch((err) => {
		console.error("Failed to load sites.geojson:", err);
		alert("Could not load sites.geojson. Check /convert/sites.geojson path.");
	  });
});
