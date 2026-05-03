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

  // TIMELINE CONFIG
  const LONG_AGO_YEAR = -50001;
  const LONG_AGO_POSITION = 0;
  const OLD_BC_START_POSITION = 1;
  const RECENT_BC_START_POSITION = 4;
  const AD_START_POSITION = 9;
  const AD_END_POSITION = 14;
  const TIMELINE_MIN = LONG_AGO_POSITION;
  const NORMAL_TIMELINE_MIN = -50000; // 50,000 BC
  const RECENT_BC_MIN = -2000;
  const TIMELINE_MAX = 2026; // 2026 AD
  const RECENT_TICK_YEARS = 100;
  const OLD_BC_TICK_YEARS_LIST = [-50000, -40000, -30000, -20000, -10000];

  let activeTimelineYear = null; // null = no timeline filter
  let includeUnknownDatesWhenFiltering = false;

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

  // DATE NORMALIZATION (timeline_start/timeline_end preferred)
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

    if (d.BC_AD === "LONG_AGO") {
      return { start: LONG_AGO_YEAR, end: LONG_AGO_YEAR };
    }

    const timelineStart = Number(d.timeline_start);
    const timelineEnd = Number(d.timeline_end);
    if (Number.isFinite(timelineStart) && Number.isFinite(timelineEnd)) {
      return {
        start: Math.min(timelineStart, timelineEnd),
        end: Math.max(timelineStart, timelineEnd),
      };
    }

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

  function isFeatureVisibleAtTimelineYear(feature, selectedYear) {
    if (selectedYear == null) return true;

    const props = feature?.properties || feature || {};
    const { start, end } = normalizeFeatureDate(props);
    if (start == null || end == null) return includeUnknownDatesWhenFiltering;

    if (props?.date?.BC_AD === "LONG_AGO") {
      return selectedYear === LONG_AGO_YEAR;
    }

    return selectedYear >= start && selectedYear <= end;
  }

  function formatYear(y) {
    if (y === LONG_AGO_YEAR) return "A long time ago";
    if (y === 0) return "0 BC";
    if (y < 0) return `${Math.abs(y)} BC`;
    return `${y} AD`;
  }

  function formatTimelineReadout(value) {
    if (value == null) return "Timeline: All dates";
    return `Timeline: ${formatYear(value)}`;
  }

  function timelineYearToSliderPosition(year) {
    if (year === LONG_AGO_YEAR) return LONG_AGO_POSITION;
    if (year < RECENT_BC_MIN) {
      return (
        OLD_BC_START_POSITION +
        ((year - NORMAL_TIMELINE_MIN) /
          (RECENT_BC_MIN - NORMAL_TIMELINE_MIN)) *
          (RECENT_BC_START_POSITION - OLD_BC_START_POSITION)
      );
    }
    if (year <= 0) {
      return (
        RECENT_BC_START_POSITION +
        ((year - RECENT_BC_MIN) / Math.abs(RECENT_BC_MIN)) *
          (AD_START_POSITION - RECENT_BC_START_POSITION)
      );
    }
    return AD_START_POSITION + (year / TIMELINE_MAX) * (AD_END_POSITION - AD_START_POSITION);
  }

  function sliderPositionToTimelineYear(position) {
    if (position < OLD_BC_START_POSITION) return LONG_AGO_YEAR;
    if (position < RECENT_BC_START_POSITION) {
      const oldBcYear =
        NORMAL_TIMELINE_MIN +
        ((position - OLD_BC_START_POSITION) /
          (RECENT_BC_START_POSITION - OLD_BC_START_POSITION)) *
          (RECENT_BC_MIN - NORMAL_TIMELINE_MIN);
      return nearestYear(oldBcYear, OLD_BC_TICK_YEARS_LIST);
    }
    if (position <= AD_START_POSITION) {
      const recentBcYear =
        RECENT_BC_MIN +
        ((position - RECENT_BC_START_POSITION) /
          (AD_START_POSITION - RECENT_BC_START_POSITION)) *
          Math.abs(RECENT_BC_MIN);
      return Math.round(recentBcYear / RECENT_TICK_YEARS) * RECENT_TICK_YEARS;
    }
    const adYear =
      ((position - AD_START_POSITION) / (AD_END_POSITION - AD_START_POSITION)) *
      TIMELINE_MAX;
    if (adYear > TIMELINE_MAX - RECENT_TICK_YEARS / 2) return TIMELINE_MAX;
    return Math.min(
      TIMELINE_MAX,
      Math.max(0, Math.round(adYear / RECENT_TICK_YEARS) * RECENT_TICK_YEARS),
    );
  }

  function nearestYear(year, candidates) {
    return candidates.reduce((best, candidate) =>
      Math.abs(candidate - year) < Math.abs(best - year) ? candidate : best,
    );
  }

  function positionPercent(position) {
    return `${((position - TIMELINE_MIN) / (AD_END_POSITION - TIMELINE_MIN)) * 100}%`;
  }

function addTimelineLabel(container, label, year, className = "") {
    const span = document.createElement("span");
    span.textContent = label;
    span.className = `timeline-label ${className}`.trim();
    span.style.left = positionPercent(timelineYearToSliderPosition(year));
    container.appendChild(span);
  }

  function addTimelineTick(container, year, className = "") {
    const span = document.createElement("span");
    span.className = `timeline-tick ${className}`.trim();
    span.style.left = positionPercent(timelineYearToSliderPosition(year));
    container.appendChild(span);
  }

  function addTimelineEndpoint(container, year) {
    const span = document.createElement("span");
    span.className = "timeline-tick timeline-endpoint";
    span.style.left = positionPercent(timelineYearToSliderPosition(year));
    container.appendChild(span);
  }

  function formatBuiltHistory(props) {
    const history = props?.construction_history;
    const dateDisplay = props?.date?.display;
    const builtText = dateDisplay || history?.llm_built;
    if (!builtText) return "";

    const built = escapeHtml(builtText);
    const evidence = history?.llm_evidence
      ? `<div class="popup-evidence">${escapeHtml(history.llm_evidence)}</div>`
      : "";
    const renovated = history?.llm_renovated
      ? `<div class="popup-meta">Renovated: ${escapeHtml(history.llm_renovated)}</div>`
      : "";

    return `
      <div class="popup-built">Built: ${built}</div>
      ${renovated}
      ${evidence}
    `;
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
    const unknownBtn = document.getElementById("timelineUnknownToggle");
    const labelBox = document.getElementById("timelineLabels");
    if (!slider || !readout || !clearBtn) return;

    slider.min = String(TIMELINE_MIN);
    slider.max = String(AD_END_POSITION);
    slider.step = "0.01";
    slider.value = String(timelineYearToSliderPosition(TIMELINE_MAX));

    if (labelBox) {
      labelBox.innerHTML = "";
      addTimelineEndpoint(labelBox, LONG_AGO_YEAR);
      OLD_BC_TICK_YEARS_LIST.forEach((year) => {
        addTimelineTick(labelBox, year, "timeline-tick-major");
      });
      for (let year = RECENT_BC_MIN; year <= 0; year += RECENT_TICK_YEARS) {
        addTimelineTick(labelBox, year);
      }
      for (let year = RECENT_TICK_YEARS; year <= 2000; year += RECENT_TICK_YEARS) {
        addTimelineTick(labelBox, year);
      }
      addTimelineEndpoint(labelBox, TIMELINE_MAX);
      addTimelineLabel(labelBox, "2000 BC", RECENT_BC_MIN);
      addTimelineLabel(labelBox, "0 BC", 0);
      addTimelineLabel(labelBox, "1000", 1000);
      addTimelineLabel(labelBox, "1500", 1500);
      addTimelineLabel(labelBox, "1900", 1900);
    }

    // Default to "All dates"
    activeTimelineYear = null;
    readout.textContent = formatTimelineReadout(activeTimelineYear);

    // Drag updates while sliding
    slider.addEventListener("input", () => {
      const selectedYear = sliderPositionToTimelineYear(Number(slider.value));

      activeTimelineYear = selectedYear;
      slider.value = String(timelineYearToSliderPosition(selectedYear));
      readout.textContent = formatTimelineReadout(activeTimelineYear);
      renderFiltered();
    });

    // Clear back to all
    clearBtn.addEventListener("click", () => {
      activeTimelineYear = null;
      readout.textContent = formatTimelineReadout(activeTimelineYear);
      renderFiltered();
    });

    unknownBtn?.addEventListener("click", () => {
      includeUnknownDatesWhenFiltering = !includeUnknownDatesWhenFiltering;
      unknownBtn.classList.toggle("is-active", includeUnknownDatesWhenFiltering);
      unknownBtn.setAttribute("aria-pressed", String(includeUnknownDatesWhenFiltering));
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
        return (
          shouldShow(props?.[CATEGORY_FIELD]) &&
          isFeatureVisibleAtTimelineYear(feature, activeTimelineYear)
        );
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
          ${formatBuiltHistory(props)}

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
          const img = document.getElementById(imgId);
          const note = document.getElementById(`${imgId}_note`);

          if (!pictureUrl) {
            if (img) img.remove();
            if (note) note.textContent = "No image available.";
            return;
          }

          if (!img || img.dataset.loaded === "1") return;

          img.onload = () => {
            img.dataset.loaded = "1";
            if (note) note.remove();
          };

          img.onerror = () => {
            img.dataset.loaded = "1";
            if (img) img.remove();
            if (note) note.textContent = "No image available.";
          };

          img.src = pictureUrl;
        });

        return marker;
      },
    });

    cluster.addLayer(geo);

    // status line includes category + timeline
    statusLine.textContent = `Showing: ${filterLabel()} - ${formatTimelineReadout(activeTimelineYear)} - Points: ${shown}`;

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

  console.debug("Timeline date checks", [
    { input: "ten million years ago", visibleAt: LONG_AGO_YEAR, sliderAt: LONG_AGO_POSITION },
    { input: "17th century", range: [1600, 1699] },
    { input: "1310", range: [1310, 1310] },
    { input: "1700s", range: [1700, 1799] },
    { input: "10th century BC", range: [-999, -900] },
    { input: "5th millennium BC", range: [-5000, -4000] },
    { input: "1400-1600", range: [1400, 1600] },
  ]);

  // Load GeoJSON
  fetch("/convert/sites.geojson")
    .then((r) => {
      if (!r.ok)
        throw new Error(
          `HTTP ${r.status} while loading /convert/sites.geojson`,
        );
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
