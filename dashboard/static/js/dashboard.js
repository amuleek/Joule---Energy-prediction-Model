/* Joule — Energy Market Intelligence — client-side logic */

const JOULE_TIPS = [
  "Joule online — tracking crude, RBOB & diesel across day 1, 4 & 7 horizons.",
  "Crack spreads reflect refinery margins. Joule tracks them daily.",
  "Headlines are scored for sentiment and geopolitical risk.",
  "Models: VAR, XGBoost, CatBoost — stacked for each horizon.",
  "Inventory draws often support prices. Joule monitors EIA weekly data.",
  "A stronger dollar (DXY) can pressure crude. Joule watches both.",
  "Click 'Run Joule' to trigger a fresh prediction pipeline.",
  "Day-1 direction accuracy is logged in Analytics.",
  "Geopolitical risk scores update with every news fetch.",
];

let tipIndex = 0;

function rotateJouleTip() {
  const el = document.getElementById("joule-tip");
  if (!el) return;
  tipIndex = (tipIndex + 1) % JOULE_TIPS.length;
  el.style.opacity = "0";
  setTimeout(() => {
    el.textContent = JOULE_TIPS[tipIndex];
    el.style.opacity = "1";
  }, 300);
}

function setBanner(cls, text) {
  const banner = document.getElementById("banner");
  const bannerText = document.getElementById("banner-text");
  if (banner) banner.className = `banner ${cls}`;
  if (bannerText) bannerText.textContent = text;
}

const COLORS = { RBOB: "#f59e0b", ULSD: "#10b981", Crude: "#3b82f6" };
const PLOT_LAYOUT = {
  paper_bgcolor: "transparent",
  plot_bgcolor: "transparent",
  font: { color: "#94a3b8", family: "Inter, Segoe UI, sans-serif", size: 11 },
  margin: { t: 30, r: 20, b: 40, l: 55 },
  xaxis: { gridcolor: "#1e2d42", zerolinecolor: "#1e2d42" },
  yaxis: { gridcolor: "#1e2d42", zerolinecolor: "#1e2d42" },
  legend: { orientation: "h", y: 1.12, font: { size: 10 } },
  hoverlabel: { bgcolor: "#111827", bordercolor: "#2a3f5c", font: { color: "#f1f5f9" } },
};
const PLOT_CONFIG = { responsive: true, displayModeBar: false };

const fmtPct = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(2)}%`);
const fmtNum = (v, d = 2) => (v == null ? "—" : Number(v).toFixed(d));
const dirClass = (d) => (d === "UP" ? "up" : d === "DOWN" ? "down" : "flat");
const badgeClass = (d) => {
  if (!d) return "neutral";
  const u = d.toUpperCase();
  if (u === "UP" || u === "BULLISH") return "up";
  if (u === "DOWN" || u === "BEARISH") return "down";
  if (u === "FLAT" || u === "NEUTRAL") return "flat";
  return "neutral";
};

async function fetchJson(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

/* ── Navigation ── */
function initNav() {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".section").forEach((s) => s.classList.remove("active"));
      btn.classList.add("active");
      const target = document.getElementById(btn.dataset.section);
      if (target) target.classList.add("active");
    });
  });
}

/* ── Ticker ── */
function renderTicker(news) {
  const track = document.getElementById("ticker-track");
  if (!track) return;
  const items = (news.items || []).slice(0, 15);
  if (!items.length) {
    track.innerHTML = '<span class="ticker-item">No headlines yet — click "Run Joule" to fetch news.</span>';
    return;
  }
  const html = items.map((n) => {
    const sentCls = n.sentiment > 0.05 ? "sent-pos" : n.sentiment < -0.05 ? "sent-neg" : "";
    return `<span class="ticker-item"><span class="${sentCls}">●</span> ${n.title} <em>— ${n.source}</em></span>`;
  }).join("");
  track.innerHTML = html + html;
}

/* ── KPI Strip ── */
function renderKPIs(preds, acc, market, news) {
  const el = document.getElementById("kpi-strip");
  if (!el) return;
  const o = acc.overall || {};
  const hurr = (market.hurricane || {});
  const dxy = (market.dollar_index || {}).latest || {};
  const op = market.operational || {};
  const ns = news.summary || {};

  const items = [
    ["Direction Accuracy", o.direction_pct != null ? `${o.direction_pct}%` : "—", `${o.count || 0} forecasts scored`],
    ["Day-1 Accuracy", o.day1_direction_pct != null ? `${o.day1_direction_pct}%` : "—", "Tomorrow direction"],
    ["Mean Abs Error", o.mean_abs_error_pct != null ? `${o.mean_abs_error_pct}%` : "—", "All horizons"],
    ["News Sentiment", ns.sentiment_label || "—", ns.latest_sentiment != null ? `Score: ${ns.latest_sentiment}` : ""],
    ["Geo Risk", ns.latest_geo_risk != null ? ns.latest_geo_risk.toFixed(3) : "—", "Headline risk index"],
    ["DXY", dxy.close ? fmtNum(dxy.close, 2) : "—", dxy.change_1d_pct != null ? fmtPct(dxy.change_1d_pct) : ""],
    ["Refinery Util", op.refinery_utilization_pct ? `${op.refinery_utilization_pct}%` : "—", "US capacity"],
    ["Hurricane Risk", hurr.risk_score != null ? hurr.risk_score.toFixed(2) : "—", `${hurr.active_storm_count || 0} active storms`],
  ];

  el.innerHTML = items.map(([label, val, sub]) =>
    `<div class="kpi"><div class="kpi-label">${label}</div><div class="kpi-value">${val}</div><div class="kpi-sub">${sub}</div></div>`
  ).join("");
}

/* ── Product Cards ── */
function renderProducts(data) {
  const wrap = document.getElementById("product-cards");
  if (!wrap) return;
  wrap.innerHTML = "";
  const products = Object.values(data.products || {});
  const cssMap = { RBOB_Gasoline: "rbob", ULSD_Diesel: "ulsd", Crude_Oil: "crude" };

  products.forEach((p) => {
    const d1 = (p.horizons || {}).day_1 || {};
    const sig = p.trading_signal || {};
    const dir = p.directional || {};
    const card = document.createElement("div");
    card.className = `product-card ${cssMap[p.key] || ""}`;

    const horizons = ["day_1", "day_4", "day_7"].map((k) => {
      const h = (p.horizons || {})[k];
      if (!h) return "";
      return `<div class="forecast-cell">
        <div class="fc-label">${h.label}</div>
        <div class="fc-price">$${h.price.toFixed(p.decimals)}</div>
        <div class="fc-pct ${dirClass(h.direction)}">${fmtPct(h.change_pct)}</div>
      </div>`;
    }).join("");

    card.innerHTML = `
      <div class="product-header">
        <div class="product-name">${p.label}</div>
        <span class="badge ${badgeClass(dir.label || d1.direction)}">${dir.emoji || ""} ${dir.label || d1.direction || "—"}</span>
      </div>
      <div class="product-price">$${p.current_price.toFixed(p.decimals)}</div>
      <div class="product-unit">${p.unit} · ${p.uncertainty || "—"}</div>
      <div class="forecast-grid">${horizons}</div>
      ${sig.headline ? `<div class="signal-box">
        <div class="signal-headline">${sig.headline}</div>
        <div class="signal-sub">${sig.subhead || sig.drivers_text || ""}</div>
      </div>` : ""}
      ${p.reasoning ? `<div class="uncertainty-tag">${p.reasoning}</div>` : ""}
    `;
    wrap.appendChild(card);
  });
}

/* ── Charts ── */
function renderPriceChart(prices) {
  const traces = [];
  for (const [col, rows] of Object.entries(prices)) {
    if (!rows.length) continue;
    traces.push({
      x: rows.map((r) => r.date),
      y: rows.map((r) => r.price),
      name: col,
      mode: "lines",
      line: { color: COLORS[col] || "#ccc", width: 2 },
      fill: "tozeroy",
      fillcolor: (COLORS[col] || "#ccc") + "15",
    });
  }
  Plotly.newPlot("price-chart", traces, {
    ...PLOT_LAYOUT,
    yaxis: { ...PLOT_LAYOUT.yaxis, title: "Settlement Price" },
    title: { text: "", font: { size: 12 } },
  }, PLOT_CONFIG);
}

function renderAccuracyChart(acc) {
  const rows = acc.forecast_chart || [];
  const products = [...new Set(rows.map((r) => r.product))];
  const traces = [];
  products.forEach((prod) => {
    const sub = rows.filter((r) => r.product === prod);
    const color = COLORS[prod] || "#ccc";
    traces.push({
      x: sub.map((r) => r.date), y: sub.map((r) => r.predicted),
      name: `${prod} forecast`, mode: "lines+markers",
      line: { dash: "dot", color, width: 1.5 },
      marker: { size: 4 },
    });
    traces.push({
      x: sub.map((r) => r.date), y: sub.map((r) => r.actual),
      name: `${prod} actual`, mode: "lines",
      line: { color, width: 2 },
    });
  });
  Plotly.newPlot("accuracy-chart", traces, {
    ...PLOT_LAYOUT,
    title: { text: "", font: { size: 12 } },
  }, PLOT_CONFIG);
}

function renderInventoryChart(inv) {
  const series = inv.series || {};
  const traces = [];
  const names = { gasoline: "Gasoline", diesel: "Diesel", crude: "Crude" };
  const colors = { gasoline: "#f59e0b", diesel: "#10b981", crude: "#3b82f6" };
  for (const [key, rows] of Object.entries(series)) {
    if (!rows.length) continue;
    traces.push({
      x: rows.map((r) => r.date),
      y: rows.map((r) => r.value),
      name: names[key] || key,
      mode: "lines+markers",
      line: { color: colors[key] || "#ccc", width: 2 },
      marker: { size: 5 },
    });
  }
  Plotly.newPlot("inventory-chart", traces, {
    ...PLOT_LAYOUT,
    yaxis: { ...PLOT_LAYOUT.yaxis, title: "Thousand Barrels" },
  }, PLOT_CONFIG);
}

function renderSentimentChart(news) {
  const rows = news.daily_sentiment || [];
  if (!rows.length) return;
  const traces = [
    {
      x: rows.map((r) => r.date),
      y: rows.map((r) => r.sentiment),
      name: "Sentiment",
      mode: "lines+markers",
      line: { color: "#8b5cf6", width: 2 },
      fill: "tozeroy",
      fillcolor: "rgba(139, 92, 246, 0.1)",
    },
    {
      x: rows.map((r) => r.date),
      y: rows.map((r) => r.geo_risk),
      name: "Geo Risk",
      mode: "lines",
      line: { color: "#ef4444", width: 1.5, dash: "dot" },
      yaxis: "y2",
    },
  ];
  Plotly.newPlot("sentiment-chart", traces, {
    ...PLOT_LAYOUT,
    yaxis: { ...PLOT_LAYOUT.yaxis, title: "Sentiment", range: [-0.3, 0.3] },
    yaxis2: { title: "Geo Risk", overlaying: "y", side: "right", gridcolor: "transparent", range: [0, 0.15] },
  }, PLOT_CONFIG);
}

function renderCrackChart(market) {
  const current = (market.crack_spreads || {}).current || {};
  const forecast = (market.crack_spreads || {}).forecast || {};
  const horizons = ["day_1", "day_4", "day_7"];
  const labels = ["Current", "Day 1", "Day 4", "Day 7"];

  const gasVals = [current.gasoline];
  const dieVals = [current.diesel];
  horizons.forEach((h) => {
    const f = forecast[h] || {};
    gasVals.push(f.gasoline_crack_usd_per_bbl);
    dieVals.push(f.diesel_crack_usd_per_bbl);
  });

  Plotly.newPlot("crack-chart", [
    { x: labels, y: gasVals, name: "Gasoline Crack", type: "bar", marker: { color: "#f59e0b" } },
    { x: labels, y: dieVals, name: "Diesel Crack", type: "bar", marker: { color: "#10b981" } },
  ], {
    ...PLOT_LAYOUT,
    barmode: "group",
    yaxis: { ...PLOT_LAYOUT.yaxis, title: "$/bbl" },
  }, PLOT_CONFIG);
}

function renderDXYChart(market) {
  const series = (market.dollar_index || {}).series || [];
  if (!series.length) return;
  Plotly.newPlot("dxy-chart", [{
    x: series.map((r) => r.date),
    y: series.map((r) => r.close),
    name: "DXY",
    mode: "lines",
    line: { color: "#6366f1", width: 2 },
    fill: "tozeroy",
    fillcolor: "rgba(99, 102, 241, 0.08)",
  }], {
    ...PLOT_LAYOUT,
    yaxis: { ...PLOT_LAYOUT.yaxis, title: "US Dollar Index" },
  }, PLOT_CONFIG);
}

function renderForecastFan(preds) {
  const traces = [];
  const products = Object.values(preds.products || {});
  products.forEach((p) => {
    const horizons = ["day_1", "day_4", "day_7"];
    const x = ["Current", ...horizons.map((h) => (p.horizons[h] || {}).label || h)];
    const y = [p.current_price, ...horizons.map((h) => (p.horizons[h] || {}).price || null)];
    const cr = p.confidence_range;
    traces.push({
      x, y, name: p.label, mode: "lines+markers",
      line: { color: COLORS[p.column] || "#ccc", width: 2 },
      marker: { size: 7 },
    });
    if (cr && cr.lower && cr.upper) {
      traces.push({
        x: [x[x.length - 1], x[x.length - 1]],
        y: [cr.lower, cr.upper],
        mode: "lines",
        line: { color: COLORS[p.column] || "#ccc", width: 4, dash: "dot" },
        showlegend: false,
        opacity: 0.4,
      });
    }
  });
  Plotly.newPlot("fan-chart", traces, {
    ...PLOT_LAYOUT,
    yaxis: { ...PLOT_LAYOUT.yaxis, title: "Price" },
  }, PLOT_CONFIG);
}

/* ── News Feed ── */
function renderNewsFeed(news) {
  const wrap = document.getElementById("news-feed");
  if (!wrap) return;
  const items = news.items || [];
  if (!items.length) {
    wrap.innerHTML = '<div class="news-item">No headlines yet — click "Run Joule" to fetch the latest news.</div>';
    return;
  }
  wrap.innerHTML = items.map((n) => {
    const sentBadge = n.sentiment != null
      ? `<span class="badge ${n.sentiment > 0.05 ? "up" : n.sentiment < -0.05 ? "down" : "flat"}">${n.sentiment > 0 ? "+" : ""}${n.sentiment}</span>`
      : "";
    const topic = n.top_topic ? `<span class="topic-tag">${n.top_topic}</span>` : "";
    const date = n.date ? new Date(n.date).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
    return `<div class="news-item">
      <div class="news-meta">
        <span class="news-source">${n.source}</span>
        <span class="news-date">${date}</span>
        ${sentBadge}${topic}
      </div>
      <div class="news-title">${n.title}</div>
      <div class="news-desc">${n.description || ""}</div>
    </div>`;
  }).join("");
}

/* ── Fundamentals ── */
function renderFundamentals(market, inv) {
  const el = document.getElementById("fund-grid");
  if (!el) return;
  const op = market.operational || {};
  const retail = market.retail_pump || {};
  const freight = market.freight || {};
  const cracks = (market.crack_spreads || {}).current || {};
  const invLatest = inv.latest || {};

  const items = [
    ["Gasoline Crack", cracks.gasoline ? `$${cracks.gasoline}/bbl` : "—", "Refinery margin proxy"],
    ["Diesel Crack", cracks.diesel ? `$${cracks.diesel}/bbl` : "—", "Refinery margin proxy"],
    ["Gasoline Stocks", invLatest.gasoline ? `${(invLatest.gasoline.value / 1000).toFixed(0)}M bbl` : "—", invLatest.gasoline?.wow_pct != null ? fmtPct(invLatest.gasoline.wow_pct) + " WoW" : ""],
    ["Diesel Stocks", invLatest.diesel ? `${(invLatest.diesel.value / 1000).toFixed(0)}M bbl` : "—", invLatest.diesel?.wow_pct != null ? fmtPct(invLatest.diesel.wow_pct) + " WoW" : ""],
    ["Crude Stocks", invLatest.crude ? `${(invLatest.crude.value / 1000).toFixed(0)}M bbl` : "—", invLatest.crude?.wow_pct != null ? fmtPct(invLatest.crude.wow_pct) + " WoW" : ""],
    ["Refinery Utilization", op.refinery_utilization_pct ? `${op.refinery_utilization_pct}%` : "—", "US operating capacity"],
    ["Crude Imports", op.crude_imports_kbpd ? `${(op.crude_imports_kbpd / 1000).toFixed(1)}M bpd` : "—", "Weekly EIA"],
    ["Crude Exports", op.crude_exports_kbpd ? `${(op.crude_exports_kbpd / 1000).toFixed(1)}M bpd` : "—", "Weekly EIA"],
    ["Retail Gasoline", retail.regular_gasoline ? `$${retail.regular_gasoline}/gal` : "—", retail.region_label || ""],
    ["Retail Diesel", retail.ulsd_diesel ? `$${retail.ulsd_diesel}/gal` : "—", retail.period || ""],
    ["Baltic Dry Proxy", freight.baltic_dry_proxy ? fmtNum(freight.baltic_dry_proxy, 2) : "—", freight.freight_return_1d != null ? fmtPct(freight.freight_return_1d * 100) + " 1d" : ""],
    ["Model Stack", (market.model_stack || []).join(" → ") || market.model || "—", "Active models"],
  ];

  el.innerHTML = items.map(([label, val, sub]) =>
    `<div class="fund-card"><div class="fund-label">${label}</div><div class="fund-value">${val}</div><div class="kpi-sub">${sub}</div></div>`
  ).join("");
}

/* ── Intelligence ── */
function renderIntelligence(preds) {
  const wrap = document.getElementById("intel-panel");
  if (!wrap) return;
  const products = Object.values(preds.products || {});
  wrap.innerHTML = products.map((p) => {
    const dir = p.directional || {};
    const rationale = dir.scenario_rationale || {};
    const bullets = (rationale.bullets || []).map((b) => `<li>${b}</li>`).join("");
    return `<div class="intel-card">
      <h4>${dir.emoji || ""} ${p.label} — ${dir.label || "Analysis"}</h4>
      <p>${dir.summary || p.reasoning || "No analysis available."}</p>
      ${rationale.headline ? `<p style="margin-top:0.5rem;font-weight:600;font-size:0.82rem">${rationale.headline}</p>` : ""}
      ${bullets ? `<ul class="intel-bullets">${bullets}</ul>` : ""}
      ${rationale.closing ? `<p style="margin-top:0.5rem;font-style:italic;font-size:0.78rem;color:var(--text-muted)">${rationale.closing}</p>` : ""}
    </div>`;
  }).join("");
}

/* ── Accuracy Table ── */
function renderRecentTable(acc) {
  const tbody = document.querySelector("#recent-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  (acc.recent || []).slice().reverse().forEach((r) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.target_date || ""}</td>
      <td>${r.display || r.product || ""}</td>
      <td>${r.horizon || ""}</td>
      <td>${r.predicted != null ? Number(r.predicted).toFixed(4) : "—"}</td>
      <td>${r.actual != null ? Number(r.actual).toFixed(4) : "—"}</td>
      <td class="${r.direction_correct ? "up" : "down"}">${r.error_pct != null ? fmtPct(r.error_pct) : "—"}</td>
      <td class="${r.direction_correct ? "up" : "down"}">${r.predicted_direction || ""} → ${r.actual_direction || ""}</td>
    `;
    tbody.appendChild(tr);
  });
}

/* ── Main Load ── */
async function loadAll() {
  setBanner("", "Joule is loading market data…");
  try {
    const [status, preds, prices, acc, news, inv, market] = await Promise.all([
      fetchJson("/api/status"),
      fetchJson("/api/predictions"),
      fetchJson("/api/prices?days=90"),
      fetchJson("/api/accuracy"),
      fetchJson("/api/news?limit=40"),
      fetchJson("/api/inventory"),
      fetchJson("/api/market"),
    ]);

    const spot = preds.spot_reference || {};
    document.getElementById("spot-label").textContent =
      `${spot.label || "NYMEX Session Close"} · ${spot.as_of_date || ""}`;
    document.getElementById("generated-at").textContent =
      preds.generated_at || status.generated_at || "—";

    setBanner("ok", `Joule live · ${status.product_count} products · Updated ${preds.generated_at || status.generated_at || "—"}`);

    renderTicker(news);
    renderKPIs(preds, acc, market, news);
    renderProducts(preds);
    renderPriceChart(prices);
    renderAccuracyChart(acc);
    renderInventoryChart(inv);
    renderSentimentChart(news);
    renderCrackChart(market);
    renderDXYChart(market);
    renderForecastFan(preds);
    renderNewsFeed(news);
    renderFundamentals(market, inv);
    renderIntelligence(preds);
    renderRecentTable(acc);
  } catch (e) {
    setBanner("err", "Joule error: " + e.message);
  }
}

async function pollRunStatus() {
  const btn = document.getElementById("run-btn");
  const tick = async () => {
    const st = await fetchJson("/api/run/status");
    if (st.running) {
      btn.disabled = true;
      setBanner("running", "Joule running pipeline… fetching prices, news & forecasts (1–2 min)");
      setTimeout(tick, 3000);
    } else {
      btn.disabled = false;
      if (st.last_error) {
        setBanner("err", "Joule pipeline error: " + st.last_error);
      } else {
        setBanner("ok", "Joule finished a fresh prediction run.");
        await loadAll();
      }
    }
  };
  await tick();
}

/* ── Init ── */
document.addEventListener("DOMContentLoaded", () => {
  initNav();
  document.getElementById("refresh-btn").addEventListener("click", loadAll);
  document.getElementById("run-btn").addEventListener("click", async () => {
    try {
      await fetchJson("/api/run", { method: "POST" });
      pollRunStatus();
    } catch (e) {
      setBanner("err", e.message);
    }
  });
  loadAll();
  setInterval(loadAll, 120000);
  setInterval(rotateJouleTip, 15000);
});
