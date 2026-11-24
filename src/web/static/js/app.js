// State
let currentSymbol = "AAPL";
let currentTimeframe = "1D";
let chart = null;
let candleSeries = null;
let volumeSeries = null;
let emaSeries = {};
let priceLines = [];
let currentTrackingLine = null;

// Initialize on Load
document.addEventListener("DOMContentLoaded", () => {
  initClocks();
  initChart();
  loadDataSourceStatus().then(() => {
    loadOverviewSymbols();
    loadChartData(currentSymbol, currentTimeframe);
    startChartPolling(); // Enable live real-time chart polling immediately
  });
  loadSystemStatus();
  loadZones(currentSymbol);
  loadSymbolPlan(currentSymbol);
  loadAINarrative(currentSymbol);
  loadNonEntryJournal();
  loadScreenshots();
});

// Data Source Switcher
async function loadDataSourceStatus() {
  try {
    const res = await fetch("/api/data-source");
    const data = await res.json();
    const select = document.getElementById("select-data-source");
    if (select) select.value = data.active_source;

    const pillData = document.getElementById("pill-data-status");
    const pillAccount = document.getElementById("pill-account-badge");
    const valAccount = document.getElementById("val-account-login");

    if (data.active_source === "MT5") {
      pillData.innerText = "DATA: EXNESS LIVE";
      pillData.className = "pill pill-live";
      pillData.style.background = "var(--dime-green-bg)";
      pillData.style.color = "var(--dime-green)";
      pillData.style.borderColor = "rgba(16, 185, 129, 0.4)";
      if (data.account_login) {
        pillAccount.style.display = "inline-flex";
        const isReal = !data.is_demo;
        const typeStr = data.account_type || (isReal ? "REAL" : "DEMO");
        valAccount.innerText = `#${data.account_login} (${typeStr})`;

        if (isReal) {
          pillAccount.style.background = "rgba(239, 68, 68, 0.15)";
          pillAccount.style.color = "#ef4444";
          pillAccount.style.borderColor = "rgba(239, 68, 68, 0.4)";
        } else {
          pillAccount.style.background = "var(--dime-green-bg)";
          pillAccount.style.color = "var(--dime-green)";
          pillAccount.style.borderColor = "rgba(16, 185, 129, 0.3)";
        }
      }
    } else {
      pillData.innerText = "DATA: SIMULATION";
      pillData.className = "pill pill-sim";
      pillData.style.background = "";
      pillData.style.color = "";
      pillData.style.borderColor = "";
      pillAccount.style.display = "none";
    }
  } catch (err) {
    console.error("Failed to load data source status:", err);
  }
}

async function onSwitchDataSource(newSource) {
  try {
    const res = await fetch("/api/data-source/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: newSource })
    });
    const data = await res.json();
    if (!data.success) {
      alert(`ไม่สามารถสลับไปยัง ${newSource} ได้: ${data.error || "เกิดข้อผิดพลาด"}`);
      loadDataSourceStatus();
      return;
    }

    // Refresh all data on current screen
    await loadDataSourceStatus();
    await loadSystemStatus();
    loadOverviewSymbols();
    loadChartData(currentSymbol, currentTimeframe);
    loadZones(currentSymbol);
    loadSymbolPlan(currentSymbol);
    loadAINarrative(currentSymbol);
  } catch (err) {
    alert("เกิดข้อผิดพลาดในการสลับแหล่งข้อมูล");
  }
}

// Clocks Update
function initClocks() {
  function updateTime() {
    const now = new Date();
    document.getElementById("clock-utc").innerText = now.toUTCString().slice(17, 25);

    // NY Time (EDT/EST)
    const nyTime = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false
    }).format(now);
    document.getElementById("clock-et").innerText = nyTime;

    // Bangkok Time (UTC+7)
    const bkkTime = new Intl.DateTimeFormat("en-US", {
      timeZone: "Asia/Bangkok",
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false
    }).format(now);
    document.getElementById("clock-bkk").innerText = bkkTime;
  }
  updateTime();
  setInterval(updateTime, 1000);
}

// Experimental Gold Strategy
async function fetchGoldAnalysis() {
  try {
    const res = await fetch("/api/gold/analysis");
    const data = await res.json();
    if (data.error) {
      alert("Gold Analysis Error: " + data.error);
      return;
    }
    const session = data.session_info ? data.session_info.session_description : "N/A";
    const demandCount = data.demand_zones ? data.demand_zones.length : 0;
    const supplyCount = data.supply_zones ? data.supply_zones.length : 0;

    let msg = `⚡ XAU/USD (Gold) Strategy วิเคราะห์โซนทองคำ\n` +
      `----------------------------------------\n` +
      `คู่เงิน: ${data.symbol} (${data.mt5_symbol}) | ราคาปัจจุบัน: $${data.current_price}\n` +
      `ค่าความผันผวน ATR(15m): $${data.atr_15m}\n` +
      `บัญชีเป้าหมาย: #${data.target_account} (Safety Guard ล็อกสิทธิ์)\n\n` +
      `🕒 Session ปัจจุบัน: ${session}\n` +
      `📊 โซนที่ตรวจพบ: Demand (${demandCount} โซน) | Supply (${supplyCount} โซน) | Role Reversals (${data.role_reversal_count})\n` +
      `🎯 สถานะและมุมมอง: ${data.status}\n` +
      `💡 เหตุผล: ${data.setup_reason}\n\n`;

    if (data.recommended_direction && data.recommended_direction !== "NEUTRAL") {
      msg += `📌 คำแนะนำเข้าทำ: ${data.recommended_direction} @ $${data.recommended_entry}\n` +
        `🛑 จุดตัดขาดทุน (SL): $${data.recommended_sl} (Moat Buffer)\n` +
        `🎯 จุดทำกำไร (TP): $${data.recommended_tp} (Front-Running)\n` +
        `คำสั่ง Antigravity: ${data.antigravity_command}\n\n`;
    }
    msg += `(หมายเหตุ: อิงตามแนวรับ-ต้าน, Role Reversal, Demand/Supply และ Session Overlap | ไม่รวม Order Block)`;
    alert(msg);
  } catch (err) {
    alert("เกิดข้อผิดพลาดในการดึงข้อมูลวิเคราะห์ทองคำ: " + err);
  }
}

// Navigation Tabs
let ordersPollingInterval = null;
let chartsPollingInterval = null;

async function updateLiveChartTick() {
  if (!candleSeries || !currentSymbol || !currentTimeframe) return;
  try {
    const res = await fetch(`/api/market/bars/${currentSymbol}?timeframe=${currentTimeframe}&limit=10`);
    const data = await res.json();
    if (!data.bars || data.bars.length === 0) return;

    const latestBar = data.bars[data.bars.length - 1];
    candleSeries.update({
      time: latestBar.time,
      open: latestBar.open,
      high: latestBar.high,
      low: latestBar.low,
      close: latestBar.close
    });

    if (volumeSeries) {
      volumeSeries.update({
        time: latestBar.time,
        value: latestBar.volume,
        color: latestBar.close >= latestBar.open ? "rgba(0, 192, 118, 0.35)" : "rgba(239, 68, 68, 0.35)"
      });
    }

    document.getElementById("chart-label-price").innerText = `$${latestBar.close.toFixed(2)}`;

    // Update real-time blue tracking line
    if (currentTrackingLine && candleSeries) {
      candleSeries.removePriceLine(currentTrackingLine);
      currentTrackingLine = null;
    }
    if (candleSeries) {
      currentTrackingLine = candleSeries.createPriceLine({
        price: latestBar.close,
        color: "#2563eb",
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Solid,
        axisLabelVisible: true,
        title: `NOW ${currentSymbol}: $${latestBar.close.toFixed(2)}`,
      });
    }
  } catch (err) {
    // Silent fail for polling
  }
}

function startChartPolling() {
  if (!chartsPollingInterval) {
    chartsPollingInterval = setInterval(updateLiveChartTick, 3000);
  }
}

function stopChartPolling() {
  if (chartsPollingInterval) {
    clearInterval(chartsPollingInterval);
    chartsPollingInterval = null;
  }
}

function switchTab(tabId) {
  document.querySelectorAll(".nav-tab").forEach(tab => tab.classList.remove("active"));
  document.querySelectorAll(".tab-pane").forEach(pane => pane.classList.remove("active"));

  if (event && event.target && event.target.classList.contains("nav-tab")) {
    event.target.classList.add("active");
  } else {
    const tabBtn = document.querySelector(`.nav-tab[onclick="switchTab('${tabId}')"]`);
    if (tabBtn) tabBtn.classList.add("active");
  }
  document.getElementById(`tab-${tabId}`).classList.add("active");

  // Real-time polling: active only on orders tab
  if (tabId === "orders") {
    loadMT5Status();
    loadMT5Positions();
    if (!ordersPollingInterval) {
      ordersPollingInterval = setInterval(() => {
        loadMT5Positions();
        loadMT5Status();
      }, 3000);
    }
  } else {
    if (ordersPollingInterval) {
      clearInterval(ordersPollingInterval);
      ordersPollingInterval = null;
    }
  }

  // Real-time polling on charts tab
  if (tabId === "charts") {
    startChartPolling();
    if (chart) {
      chart.resize(
        document.querySelector(".chart-wrapper").clientWidth,
        document.querySelector(".chart-wrapper").clientHeight
      );
    }
  } else {
    stopChartPolling();
  }

  if (tabId === "journal") {
    loadJournalPortfolios();
  }

  if (tabId === "plans") {
    loadSymbolPlan(currentSymbol);
    loadAINarrative(currentSymbol);
    loadNonEntryJournal();
  } else if (tabId === "backtest") {
    loadBacktestResults();
  } else if (tabId === "gallery") {
    loadScreenshots();
  } else if (tabId === "memory") {
    loadMemoryPlaybook();
    loadMemoryCases();
  }
}

// AI Memory & Continuous Learning Functions
async function loadMemoryPlaybook() {
  try {
    const res = await fetch("/api/memory/playbook");
    const data = await res.json();
    const box = document.getElementById("playbook-content-box");
    if (box) box.textContent = data.content || "Playbook is currently empty.";
  } catch (err) {
    console.error("Error loading playbook:", err);
  }
}

async function loadMemoryCases() {
  try {
    const res = await fetch("/api/memory/cases");
    const data = await res.json();
    const container = document.getElementById("cases-list-container");
    if (!container) return;
    container.innerHTML = "";

    const cases = data.cases || [];
    if (cases.length === 0) {
      container.innerHTML = `<div style="color: var(--text-muted); text-align: center; padding: 30px;">No closed trade cases found yet.</div>`;
      return;
    }

    cases.forEach(c => {
      const isWin = c.profit_usd > 0;
      const isLoss = c.profit_usd < 0;
      const badgeText = isWin ? 'ชนะ (WIN)' : (isLoss ? 'แพ้ (LOSS)' : 'เสมอตัว (BE)');
      const badgeClass = isWin ? 'badge-ready' : (isLoss ? 'badge-rejected' : 'badge-active');
      const card = document.createElement("div");
      card.style.cssText = "background: var(--bg-card-subtle); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 12px; display: flex; flex-direction: column; gap: 6px;";
      card.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <strong style="font-size: 13px;">#${c.ticket} - ${c.symbol} (${c.direction})</strong>
          <span class="dime-plan-badge ${badgeClass}" style="font-size: 11px;">
            ${badgeText} (${isWin ? '+' : ''}$${c.profit_usd.toFixed(2)})
          </span>
        </div>
        <div style="font-size: 11.5px; color: var(--text-muted);">
          เวลาปิด: ${c.close_time} | ตัวกระตุ้น: ${c.exit_reason === 'SL_HIT' ? 'ชน Stop Loss' : (c.exit_reason === 'TP_HIT' ? 'ชน Take Profit' : c.exit_reason)}
        </div>
        <div style="font-size: 12.5px; color: var(--text-primary); margin-top: 4px; line-height: 1.4;">
          <strong style="color: var(--dime-amber);">🔍 สาเหตุ (Root Cause):</strong> ${c.root_cause || '-'}
        </div>
        <div style="font-size: 12.5px; color: var(--dime-blue); background: rgba(59, 130, 246, 0.08); padding: 6px 10px; border-radius: 4px; border-left: 3px solid var(--dime-blue); line-height: 1.4;">
          <strong>💡 บทเรียนที่ได้:</strong> ${c.lesson_learned || '-'}
        </div>
      `;
      container.appendChild(card);
    });
  } catch (err) {
    console.error("Error loading cases:", err);
  }
}

async function syncMemoryDeals() {
  try {
    const res = await fetch("/api/memory/sync", { method: "POST" });
    const data = await res.json();
    if (data.status === "SUCCESS") {
      alert(`Sync Complete!\nFound ${data.synced_count} new closed deals.`);
      loadMemoryCases();
      loadMemoryPlaybook();
    } else {
      alert("Sync notice: " + (data.message || "Failed"));
    }
  } catch (err) {
    alert("Error syncing memory: " + err);
  }
}

// System Status API
async function loadSystemStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    document.getElementById("card-mode-val").innerText = data.trading_mode;
    document.getElementById("card-adapter-val").innerText = data.adapter_status.adapter.toUpperCase();
    document.getElementById("pill-market-session").innerText = `SESSION: ${data.market_session}`;

    // Update Settings form inputs and Header Capital pill
    if (data.risk_profile) {
      const capVal = data.risk_profile.base_capital_thb;
      document.getElementById("setting-capital").value = capVal;
      const headerCap = document.getElementById("val-header-capital");
      if (headerCap) headerCap.innerText = `${capVal.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} THB`;
      document.getElementById("setting-leverage").value = data.risk_profile.max_leverage;
      document.getElementById("setting-risk").value = data.risk_profile.risk_per_trade_percent;
      document.getElementById("setting-overnight").checked = data.risk_profile.allow_overnight;
      document.getElementById("setting-weekend").checked = data.risk_profile.allow_weekend;
      const autoExecEl = document.getElementById("setting-auto-exec");
      if (autoExecEl) autoExecEl.checked = data.execution_enabled !== undefined ? data.execution_enabled : true;
    }
  } catch (err) {
    console.error("Failed to load status:", err);
  }
}

// Overview Symbols
async function loadOverviewSymbols() {
  try {
    const res = await fetch("/api/symbols");
    const data = await res.json();
    const tbody = document.getElementById("stocks-table-body");
    tbody.innerHTML = "";

    const symbols = data.symbols;
    for (const sym of Object.keys(symbols)) {
      const info = symbols[sym];
      let lastPrice = info.base_price_estimate.toFixed(2);
      try {
        const qRes = await fetch(`/api/market/quote/${sym}`);
        const qData = await qRes.json();
        if (qData.last) lastPrice = qData.last.toFixed(2);
      } catch (e) { }

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td style="font-weight: 800; color: var(--text-primary);">${sym}</td>
        <td>${info.name}</td>
        <td><span class="brand-badge">${info.exchange}</span></td>
        <td style="font-weight: 800; color: var(--dime-blue);">$${lastPrice}</td>
        <td><code>${info.mt5_symbol}</code></td>
        <td>${info.contract_size} shares</td>
        <td>${info.min_volume} Lot</td>
        <td>
          <button class="btn" style="padding: 4px 10px;" onclick="goToChart('${sym}')">View Chart</button>
        </td>
      `;
      tbody.appendChild(tr);
    }
  } catch (err) {
    console.error("Failed to load overview symbols:", err);
  }
}

function goToChart(symbol) {
  selectSymbol(symbol);
  document.querySelectorAll(".nav-tab")[1].click();
}

// Initialize Lightweight Chart (Modern Fintech Light Mode)
function initChart() {
  const container = document.getElementById("tradingview-chart-container");
  if (!container || !window.LightweightCharts) return;

  chart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: container.clientHeight,
    layout: {
      background: { color: "#ffffff" },
      textColor: "#475569",
    },
    grid: {
      vertLines: { color: "#f8fafc" },
      horzLines: { color: "#f1f5f9" },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
    },
    rightPriceScale: {
      borderColor: "#e2e8f0",
    },
    timeScale: {
      borderColor: "#e2e8f0",
      timeVisible: true,
      secondsVisible: false,
    },
  });

  // Helper for Lightweight Charts v4 vs v5 API compatibility
  const addCandlestick = (opts) => {
    if (typeof chart.addCandlestickSeries === "function") return chart.addCandlestickSeries(opts);
    if (LightweightCharts.CandlestickSeries) return chart.addSeries(LightweightCharts.CandlestickSeries, opts);
    return null;
  };
  const addHistogram = (opts) => {
    if (typeof chart.addHistogramSeries === "function") return chart.addHistogramSeries(opts);
    if (LightweightCharts.HistogramSeries) return chart.addSeries(LightweightCharts.HistogramSeries, opts);
    return null;
  };
  const addLine = (opts) => {
    if (typeof chart.addLineSeries === "function") return chart.addLineSeries(opts);
    if (LightweightCharts.LineSeries) return chart.addSeries(LightweightCharts.LineSeries, opts);
    return null;
  };

  // Candlestick Series (Dime Colors: Emerald Green & Coral Red)
  candleSeries = addCandlestick({
    upColor: "#00c076",
    downColor: "#ef4444",
    borderVisible: false,
    wickUpColor: "#00c076",
    wickDownColor: "#ef4444",
    priceScaleId: "right",
  });

  // Volume Series on separate scale at bottom
  volumeSeries = addHistogram({
    color: "rgba(0, 192, 118, 0.2)",
    priceFormat: { type: "volume" },
    priceScaleId: "volume-scale",
  });

  // Configure separate scale for volume so it stays low at bottom (20% height)
  chart.priceScale("volume-scale").applyOptions({
    scaleMargins: {
      top: 0.82,
      bottom: 0,
    },
    visible: false,
  });

  // EMA Series
  emaSeries["15"] = addLine({ color: "#0284c7", lineWidth: 1, title: "EMA 15" });
  emaSeries["50"] = addLine({ color: "#eab308", lineWidth: 1, title: "EMA 50" });
  emaSeries["100"] = addLine({ color: "#f97316", lineWidth: 1, title: "EMA 100" });
  emaSeries["200"] = addLine({ color: "#8b5cf6", lineWidth: 2, title: "EMA 200" });

  window.addEventListener("resize", () => {
    if (chart && container) {
      chart.resize(container.clientWidth, container.clientHeight);
    }
  });
}

function toggleChartFullscreen() {
  const wrapper = document.querySelector(".chart-wrapper");
  const btn = document.getElementById("btn-fullscreen-chart");
  const container = document.getElementById("tradingview-chart-container");
  if (!wrapper) return;

  const isFullscreen = wrapper.classList.toggle("fullscreen");
  if (btn) {
    btn.innerHTML = isFullscreen ? "✕ ย่อกลับขนาดปกติ" : "⛶ ขยายเต็มจอ";
    btn.classList.toggle("btn-danger", isFullscreen);
    btn.classList.toggle("btn-outline", !isFullscreen);
  }

  setTimeout(() => {
    if (chart && container) {
      chart.resize(container.clientWidth, container.clientHeight);
      chart.timeScale().scrollToRealTime();
    }
  }, 100);
}

// Support ESC key to exit fullscreen
window.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const wrapper = document.querySelector(".chart-wrapper.fullscreen");
    if (wrapper) {
      toggleChartFullscreen();
    }
  }
});

// Load Chart Data
async function loadChartData(symbol, timeframe) {
  try {
    const res = await fetch(`/api/market/bars/${symbol}?timeframe=${timeframe}&limit=500`);
    const data = await res.json();

    if (!data.bars || data.bars.length === 0) return;

    const candles = data.bars.map(b => ({
      time: b.time,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close
    }));
    candleSeries.setData(candles);

    const volumes = data.bars.map(b => ({
      time: b.time,
      value: b.volume,
      color: b.close >= b.open ? "rgba(0, 192, 118, 0.35)" : "rgba(239, 68, 68, 0.35)"
    }));
    volumeSeries.setData(volumes);

    if (data.indicators) {
      if (data.indicators.ema15) emaSeries["15"].setData(data.indicators.ema15);
      if (data.indicators.ema50) emaSeries["50"].setData(data.indicators.ema50);
      if (data.indicators.ema100) emaSeries["100"].setData(data.indicators.ema100);
      if (data.indicators.ema200) emaSeries["200"].setData(data.indicators.ema200);

      const latestATR = data.indicators.atr14.length > 0
        ? data.indicators.atr14[data.indicators.atr14.length - 1].value
        : 0;
      document.getElementById("chart-label-atr").innerText = `ATR(14): ${latestATR.toFixed(2)}`;
    }

    const lastBar = candles[candles.length - 1];
    document.getElementById("chart-label-sym").innerText = symbol;
    document.getElementById("chart-label-tf").innerText = `[${timeframe}]`;
    document.getElementById("chart-label-price").innerText = `$${lastBar.close.toFixed(2)}`;

    // Real-time Current Price Tracking Line on right price axis
    if (currentTrackingLine && candleSeries) {
      candleSeries.removePriceLine(currentTrackingLine);
      currentTrackingLine = null;
    }
    if (candleSeries) {
      currentTrackingLine = candleSeries.createPriceLine({
        price: lastBar.close,
        color: "#2563eb",
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Solid,
        axisLabelVisible: true,
        title: `NOW ${symbol}: $${lastBar.close.toFixed(2)}`,
      });
    }

    // Scroll to latest price bar and focus on the most recent candles
    if (candles.length > 0) {
      const totalBars = candles.length;
      const visibleBars = Math.min(totalBars, 90); // Show recent 90 candles for clear view
      chart.timeScale().setVisibleLogicalRange({
        from: totalBars - visibleBars,
        to: totalBars + 5 // 5 bars right margin for real-time room
      });
      chart.timeScale().scrollToRealTime();
    } else {
      chart.timeScale().fitContent();
    }

    loadZones(symbol);
    loadSymbolPlan(symbol);
    loadAINarrative(symbol);
  } catch (err) {
    console.error("Failed to load chart bars:", err);
  }
}

// Load S/R Zones (Multi-Timeframe DAY & M15)
async function loadZones(symbol) {
  try {
    const res = await fetch(`/api/zones/${symbol}`);
    const data = await res.json();

    priceLines.forEach(pl => candleSeries.removePriceLine(pl));
    priceLines = [];

    const showDaySR = document.getElementById("check-sr")?.checked ?? true;
    const showM15SR = document.getElementById("check-sr-m15")?.checked ?? true;
    const tbody = document.getElementById("zones-table-body");
    if (tbody) tbody.innerHTML = "";

    // 1. Process DAY S/R Zones (Major Framework)
    const autoZones = data.auto_sr_zones || [];
    autoZones.forEach(z => {
      const isSup = z.zone_type === "SUPPORT";
      if (tbody) {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><span class="dime-plan-badge" style="background: rgba(0, 192, 118, 0.15); color: #00c076; font-weight: 800; margin-right: 4px;">DAY</span> <span class="dime-plan-badge ${isSup ? 'badge-ready' : 'badge-rejected'}">${z.zone_type}</span></td>
          <td style="font-weight: 700;">$${z.price_low.toFixed(2)} - $${z.price_high.toFixed(2)}</td>
          <td>${z.touch_count} times</td>
          <td><strong>${z.freshness}</strong></td>
          <td>${z.is_broken ? '<span style="color: var(--dime-red); font-weight: 700;">BROKEN / FLIPPED</span>' : '<span style="color: var(--dime-green); font-weight: 700;">ACTIVE</span>'}</td>
        `;
        tbody.appendChild(tr);
      }

      if (showDaySR && candleSeries) {
        const line = candleSeries.createPriceLine({
          price: z.price_mid,
          color: isSup ? "#00c076" : "#ef4444",
          lineWidth: 2,
          lineStyle: LightweightCharts.LineStyle.Solid,
          axisLabelVisible: true,
          title: `[DAY ${isSup ? 'SUP' : 'RES'}] $${z.price_mid.toFixed(1)}`,
        });
        priceLines.push(line);
      }
    });

    // 2. Process M15 S/R Zones (Intraday Framework)
    const m15Zones = data.m15_sr_zones || [];
    m15Zones.forEach(z => {
      const isSup = z.zone_type === "SUPPORT";
      if (tbody) {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><span class="dime-plan-badge" style="background: rgba(0, 229, 255, 0.15); color: #00e5ff; font-weight: 800; margin-right: 4px;">M15</span> <span class="dime-plan-badge" style="background: ${isSup ? 'rgba(0, 229, 255, 0.2)' : 'rgba(255, 145, 0, 0.2)'}; color: ${isSup ? '#00e5ff' : '#ff9100'}; font-weight: 700;">${z.zone_type}</span></td>
          <td style="font-weight: 700; color: ${isSup ? '#00e5ff' : '#ff9100'};">$${z.price_low.toFixed(2)} - $${z.price_high.toFixed(2)}</td>
          <td>${z.touch_count} times</td>
          <td><strong>${z.freshness}</strong></td>
          <td>${z.is_broken ? '<span style="color: var(--dime-red); font-weight: 700;">BROKEN</span>' : '<span style="color: #00e5ff; font-weight: 700;">ACTIVE</span>'}</td>
        `;
        tbody.appendChild(tr);
      }

      if (showM15SR && candleSeries) {
        const line = candleSeries.createPriceLine({
          price: z.price_mid,
          color: isSup ? "#00e5ff" : "#ff9100",
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          axisLabelVisible: true,
          title: `[M15 ${isSup ? 'SUP' : 'RES'}] $${z.price_mid.toFixed(1)}`,
        });
        priceLines.push(line);
      }
    });

    const manTbody = document.getElementById("manual-zones-table-body");
    manTbody.innerHTML = "";
    (data.manual_zones || []).forEach(m => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td style="font-weight: 700;">${m.label}</td>
        <td><span class="dime-plan-badge ${m.zone_type === 'SUPPORT' ? 'badge-ready' : 'badge-rejected'}">${m.zone_type}</span></td>
        <td>$${m.price_low.toFixed(2)} - $${m.price_high.toFixed(2)}</td>
        <td>
          <button class="btn" style="padding: 2px 8px;" onclick="toggleLockZone('${m.zone_id}')">
            ${m.is_locked ? '🔒 Locked' : '🔓 Unlocked'}
          </button>
        </td>
        <td>
          <button class="btn btn-danger" style="padding: 2px 8px;" onclick="deleteManualZone('${m.zone_id}')" ${m.is_locked ? 'disabled' : ''}>
            Delete
          </button>
        </td>
      `;
      manTbody.appendChild(tr);

      if (showSR && candleSeries) {
        const line = candleSeries.createPriceLine({
          price: m.price_mid,
          color: "#8b5cf6",
          lineWidth: 2,
          lineStyle: LightweightCharts.LineStyle.Solid,
          axisLabelVisible: true,
          title: `MANUAL: ${m.label}`,
        });
        priceLines.push(line);
      }
    });

  } catch (err) {
    console.error("Failed to load zones:", err);
  }
}

// Load Symbol Plan (Dime Plan Card)
async function loadSymbolPlan(symbol) {
  try {
    const res = await fetch(`/api/plans/${symbol}`);
    const plan = await res.json();

    document.getElementById("plan-symbol-title").innerText = plan.symbol;
    document.getElementById("plan-strategy-desc").innerText = `${plan.strategy_name} (WEEK ${plan.week_trend})`;

    // Status Badge
    const badge = document.getElementById("plan-badge-status");
    let statusTextTH = "กำลังรอจังหวะ";
    if (plan.status === "READY_FOR_REVIEW") statusTextTH = "พร้อมให้ตรวจสอบ";
    else if (plan.status === "REJECTED_NO_TRADE") statusTextTH = "งดเข้าเทรด";
    badge.innerText = statusTextTH;
    badge.className = "dime-plan-badge " + (
      plan.status === "READY_FOR_REVIEW" ? "badge-ready" :
        plan.status === "REJECTED_NO_TRADE" ? "badge-rejected" : "badge-waiting"
    );

    // Price Row
    document.getElementById("plan-entry-val").innerText = plan.entry_price > 0 ? `$${plan.entry_price.toFixed(2)}` : "-";
    document.getElementById("plan-sl-val").innerText = plan.stop_loss > 0 ? `$${plan.stop_loss.toFixed(2)}` : "-";
    document.getElementById("plan-tp-val").innerText = plan.take_profit > 0 ? `$${plan.take_profit.toFixed(2)}` : "-";

    // Risk & Sizing Block
    document.getElementById("plan-rr-val").innerText = plan.risk_reward_ratio > 0 ? `1 : ${plan.risk_reward_ratio.toFixed(2)}` : "-";
    document.getElementById("plan-lot-val").innerText = plan.lot_size > 0 ? `${plan.lot_size.toFixed(2)} Lot (${plan.shares} share)` : "0.00 Lot";
    document.getElementById("plan-risk-thb-val").innerText = plan.risk_thb > 0 ? `~${plan.risk_thb.toFixed(2)} THB` : "0.00 THB";
    document.getElementById("plan-leverage-val").innerText = plan.effective_leverage > 0 ? `1 : ${plan.effective_leverage.toFixed(2)} (Cap 1:5)` : "1 : 0.00";
    document.getElementById("plan-headroom-val").innerText = plan.headroom_to_resistance > 0 ? `$${plan.headroom_to_resistance.toFixed(2)}` : "None";

  } catch (err) {
    console.error("Failed to load symbol plan:", err);
  }
}

// Load AI Narrative
async function loadAINarrative(symbol) {
  try {
    const res = await fetch(`/api/ai/narrative/${symbol}`);
    const data = await res.json();
    const n = data.narrative;
    if (n) {
      document.getElementById("ai-week-desc").innerText = n.macro_week_insight;
      document.getElementById("ai-day-desc").innerText = n.day_structure_insight;
      document.getElementById("ai-headroom-desc").innerText = n.headroom_insight;
      document.getElementById("ai-verdict-desc").innerText = n.actionable_verdict;
    }
  } catch (err) {
    console.error("Failed to load AI narrative:", err);
  }
}

// Evaluate All 7 Stocks
async function evaluateAllPlans() {
  try {
    const res = await fetch("/api/plans/evaluate", { method: "POST" });
    const data = await res.json();
    alert("Evaluated all 7 stocks! Updated plans & non-entry journal.");
    loadSymbolPlan(currentSymbol);
    loadAINarrative(currentSymbol);
    loadNonEntryJournal();
  } catch (err) {
    alert("Evaluation error: " + err);
  }
}

// Load Non-Entry Reasons Journal
async function loadNonEntryJournal() {
  try {
    const res = await fetch("/api/plans/journal/list");
    const data = await res.json();
    const tbody = document.getElementById("journal-table-body");
    tbody.innerHTML = "";

    const list = data.journal || [];
    if (list.length === 0) {
      tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 24px;">No rejected setups recorded. All candidates currently qualify.</td></tr>`;
      return;
    }

    list.forEach(item => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td style="font-weight: 800;">${item.symbol}</td>
        <td><span class="journal-badge-rejected">${item.status}</span></td>
        <td>$${item.entry_price ? item.entry_price.toFixed(2) : '-'}</td>
        <td style="color: var(--text-secondary); font-size: 12.5px; line-height: 1.4;">${item.reason}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Failed to load non-entry journal:", err);
  }
}

// Copy Context for Antigravity
async function copyAntigravityContext() {
  try {
    const res = await fetch(`/api/ai/narrative/${currentSymbol}`);
    const data = await res.json();
    if (data.antigravity_context) {
      await navigator.clipboard.writeText(data.antigravity_context);
      alert(`Copied Technical Context for ${currentSymbol} to Clipboard!\n\nYou can now paste it into your conversation with Antigravity.`);
    }
  } catch (err) {
    alert("Failed to copy context: " + err);
  }
}

// Experimental BTC 1m Scalper
async function fetchBtcScalpAnalysis() {
  try {
    const res = await fetch("/api/crypto/btc-1m");
    const data = await res.json();
    if (data.error) {
      alert("BTC Scalper: " + data.error);
      return;
    }
    const setup = data.scalp_setup;
    const msg = `⚡ BTCUSD 1m Fast Scalper (Experimental)\n` +
      `----------------------------------------\n` +
      `Price: $${data.current_price} | RSI(14): ${data.rsi_14}\n` +
      `Structure: Overhead Resistance $${data.structure.key_resistance}\n` +
      `Demand Box: $${data.structure.demand_zone ? data.structure.demand_zone.price_low + ' - $' + data.structure.demand_zone.price_high : 'N/A'}\n` +
      `Ascending Trendline: ${data.structure.ascending_trendline ? 'ACTIVE (Higher Lows)' : 'Forming'}\n\n` +
      `🎯 Plan: ${setup.direction} @ $${setup.entry_price}\n` +
      `Stop Loss (below Demand): $${setup.stop_loss}\n` +
      `Take Profit (Resistance): $${setup.take_profit}\n` +
      `Risk/Reward Ratio: 1 : ${setup.risk_reward_ratio}\n\n` +
      `💡 Note: ${setup.narrative}\n\n` +
      `Antigravity Command:\n${data.antigravity_execution_command}`;

    if (confirm(msg + "\n\nDo you want to copy the Antigravity command to clipboard?")) {
      await navigator.clipboard.writeText(data.antigravity_execution_command);
      alert("Command copied to clipboard!");
    }
  } catch (err) {
    alert("Error fetching BTC 1m Scalp: " + err);
  }
}

// ----------------- MT5 DEMO & ORDERS -----------------
let currentModalPlan = null;

async function loadMT5Status() {
  try {
    const res = await fetch("/api/mt5/status");
    const data = await res.json();
    const badge = document.getElementById("mt5-badge-status");
    if (data.is_connected) {
      const typeLabel = data.account_type === "REAL" || !data.is_demo ? (data.account && data.account.currency === "USC" ? "REAL (Cent)" : "REAL") : "DEMO";
      badge.innerText = `MT5: CONNECTED (${typeLabel})`;
      badge.className = data.is_demo ? "dime-plan-badge badge-ready" : "dime-plan-badge";
      if (!data.is_demo) {
        badge.style.background = "rgba(239, 68, 68, 0.15)";
        badge.style.color = "#ef4444";
        badge.style.borderColor = "rgba(239, 68, 68, 0.4)";
      }
    } else {
      badge.innerText = "MT5: DISCONNECTED (Simulation)";
      badge.className = "dime-plan-badge badge-waiting";
      badge.style.background = "";
      badge.style.color = "";
      badge.style.borderColor = "";
    }

    if (data.account) {
      const acc = data.account;
      const curr = acc.currency || "USD";
      const currSym = curr === "USC" ? " USC" : "$";
      const isCent = curr === "USC";

      document.getElementById("mt5-val-balance").innerText = isCent ? `${acc.balance.toFixed(2)} USC` : `$${acc.balance.toFixed(2)}`;
      document.getElementById("mt5-val-balance-thb").innerText = isCent ? `~${((acc.balance / 100.0) * 35.0).toFixed(2)} THB` : `~${(acc.balance * 35.0).toFixed(2)} THB`;
      document.getElementById("mt5-val-equity").innerText = isCent ? `${acc.equity.toFixed(2)} USC` : `$${acc.equity.toFixed(2)}`;
      document.getElementById("mt5-val-equity-thb").innerText = isCent ? `~${((acc.equity / 100.0) * 35.0).toFixed(2)} THB` : `~${(acc.equity * 35.0).toFixed(2)} THB`;
      document.getElementById("mt5-val-margin").innerText = isCent ? `${acc.free_margin.toFixed(2)} USC` : `$${acc.free_margin.toFixed(2)}`;
      document.getElementById("mt5-val-server").innerText = `Server: ${acc.server} | Mode: ${acc.currency === "USC" ? "REAL CENT" : (!data.is_demo ? "REAL" : "DEMO")}`;
    }

    document.getElementById("mt5-val-auto-mode").innerText = data.auto_execution_enabled ? "AUTO EXECUTION" : "TWO-STEP CONFIRM";
    document.getElementById("setting-auto-exec").checked = data.auto_execution_enabled;
  } catch (err) {
    console.error("Failed to load MT5 status:", err);
  }
}

async function loadMT5Positions() {
  try {
    const res = await fetch("/api/mt5/positions");
    const data = await res.json();
    const tbody = document.getElementById("mt5-positions-table-body");
    tbody.innerHTML = "";

    const list = data.positions || [];
    if (list.length === 0) {
      tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--text-muted); padding: 24px;">No active open positions in MT5.</td></tr>`;
      return;
    }

    list.forEach(p => {
      const tr = document.createElement("tr");
      const isCent = p.currency === "USC";
      const isWin = p.profit_native !== undefined ? p.profit_native >= 0 : p.profit_usd >= 0;
      const nativeVal = p.profit_native !== undefined ? p.profit_native : p.profit_usd;
      const profitDisplay = isCent ?
        `${isWin ? '+' : ''}${nativeVal.toFixed(2)} USC (${isWin ? '+' : ''}$${p.profit_usd.toFixed(2)} / ${p.profit_thb.toFixed(2)} THB)` :
        `${isWin ? '+' : ''}$${p.profit_usd.toFixed(2)} (${p.profit_thb.toFixed(2)} THB)`;

      tr.innerHTML = `
        <td><strong>#${p.ticket}</strong></td>
        <td style="font-weight: 800;">${p.symbol}</td>
        <td><span class="dime-plan-badge ${p.direction === 'BUY' ? 'badge-ready' : 'badge-rejected'}">${p.direction}</span></td>
        <td>${p.volume.toFixed(2)} Lot</td>
        <td>$${p.open_price.toFixed(2)}</td>
        <td>$${p.current_price.toFixed(2)}</td>
        <td style="color: var(--dime-red); font-weight: 700;">$${p.sl ? p.sl.toFixed(2) : '-'}</td>
        <td style="color: var(--dime-green); font-weight: 700;">$${p.tp ? p.tp.toFixed(2) : '-'}</td>
        <td style="font-weight: 800; color: ${isWin ? 'var(--dime-green)' : 'var(--dime-red)'};">
          ${profitDisplay}
        </td>
        <td>
          <button class="btn btn-danger" style="padding: 3px 8px; font-size: 11px;" onclick="closeMT5Position(${p.ticket})">Close</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Failed to load positions:", err);
  }
}

async function reconnectMT5() {
  try {
    await fetch("/api/mt5/reconnect", { method: "POST" });
    alert("Reconnecting to MT5 terminal...");
    loadMT5Status();
  } catch (err) {
    alert("Reconnect error: " + err);
  }
}

// Two-Step Order Confirmation Modal
async function triggerTwoStepModal() {
  try {
    const res = await fetch(`/api/plans/${currentSymbol}`);
    const plan = await res.json();
    currentModalPlan = plan;

    document.getElementById("modal-symbol").innerText = plan.symbol;
    document.getElementById("modal-direction").innerText = `${plan.direction} (${plan.strategy_name})`;
    document.getElementById("modal-volume").innerText = `${plan.lot_size} Lot (${plan.shares} share)`;
    document.getElementById("modal-entry").innerText = `$${plan.entry_price.toFixed(2)}`;
    document.getElementById("modal-sl").innerText = `$${plan.stop_loss.toFixed(2)}`;
    document.getElementById("modal-tp").innerText = `$${plan.take_profit.toFixed(2)}`;
    document.getElementById("modal-risk-thb").innerText = `~${plan.risk_thb.toFixed(2)} THB (${((plan.risk_thb / 3000) * 100).toFixed(2)}%)`;
    document.getElementById("modal-leverage").innerText = `1:${plan.effective_leverage.toFixed(2)} (Max Cap: 1:5)`;

    document.getElementById("order-confirm-modal").style.display = "flex";
  } catch (err) {
    alert("Error preparing order confirmation: " + err);
  }
}

function closeTwoStepModal() {
  document.getElementById("order-confirm-modal").style.display = "none";
}

async function confirmAndSendOrderToMT5() {
  if (!currentModalPlan) return;
  const btn = document.getElementById("btn-confirm-send-order");
  btn.innerText = "⏳ Transmitting...";
  btn.disabled = true;

  try {
    const payload = {
      symbol: currentModalPlan.symbol,
      direction: currentModalPlan.direction,
      volume: currentModalPlan.lot_size,
      sl_price: currentModalPlan.stop_loss,
      tp_price: currentModalPlan.take_profit,
      comment: `AutoTrade ${currentModalPlan.symbol}`,
      plan_id: currentModalPlan.plan_id
    };

    const res = await fetch("/api/mt5/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await res.json();

    if (result.success) {
      alert(`✓ Order Sent Successfully to MT5!\nTicket: #${result.ticket}\nHard SL verified at $${result.sl}`);
      closeTwoStepModal();
      loadSymbolPlan(currentSymbol);
      loadMT5Positions();
    } else {
      alert(`✕ Order Failed: ${result.error}`);
    }
  } catch (err) {
    alert("Execution error: " + err);
  } finally {
    btn.innerText = "✓ Confirm & Send to MT5";
    btn.disabled = false;
  }
}

async function closeMT5Position(ticket) {
  if (!confirm(`Are you sure you want to close position #${ticket}?`)) return;
  try {
    const res = await fetch(`/api/mt5/close/${ticket}`, { method: "POST" });
    const data = await res.json();
    if (data.success) {
      alert(data.message);
      loadMT5Positions();
    } else {
      alert("Close failed: " + data.error);
    }
  } catch (err) {
    alert("Error closing position: " + err);
  }
}

async function emergencyCloseAllPositions() {
  if (!confirm("⚠️ CAUTION: Are you sure you want to immediately CLOSE ALL open positions at market?")) return;
  try {
    const res = await fetch("/api/mt5/emergency-close-all", { method: "POST" });
    const data = await res.json();
    alert(`Emergency Protocol Complete.\nClosed ${data.closed_count} positions.\nErrors: ${data.errors.length}`);
    loadMT5Positions();
  } catch (err) {
    alert("Emergency close error: " + err);
  }
}

async function toggleAutoExecutionMode() {
  try {
    const res = await fetch("/api/mt5/toggle-auto", { method: "POST" });
    const data = await res.json();
    alert(`Auto-Execution mode is now: ${data.auto_execution_enabled ? 'ENABLED (Hands-free)' : 'DISABLED (Two-Step Review)'}`);
    loadMT5Status();
  } catch (err) {
    alert("Error toggling auto execution: " + err);
  }
}

// ----------------- BACKTEST & ANALYTICS -----------------
async function loadBacktestResults() {
  try {
    const res = await fetch("/api/backtest/results");
    const report = await res.json();
    renderBacktestReport(report);
  } catch (err) {
    console.error("Failed to load backtest results:", err);
  }
}

async function runNewBacktest() {
  const btn = document.getElementById("btn-run-backtest");
  if (btn) btn.innerText = "⏳ Running Backtest...";
  try {
    const res = await fetch("/api/backtest/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ split_ratio: 0.70 })
    });
    const data = await res.json();
    renderBacktestReport(data.report);
    alert("Backtest completed across all 7 assets with 70/30 In-Sample/Out-of-Sample split!");
  } catch (err) {
    alert("Error running backtest: " + err);
  } finally {
    if (btn) btn.innerText = "🚀 Re-Run 7-Asset Backtest (70/30 Split)";
  }
}

function renderBacktestReport(report) {
  if (!report || !report.overall) return;
  const o = report.overall;
  const inS = report.in_sample;
  const outS = report.out_of_sample;

  // 1. KPI Cards
  document.getElementById("bt-net-profit").innerText = `${o.net_profit_thb >= 0 ? '+' : ''}${o.net_profit_thb.toFixed(2)} THB`;
  document.getElementById("bt-net-profit").style.color = o.net_profit_thb >= 0 ? "var(--dime-green)" : "var(--dime-red)";
  document.getElementById("bt-net-return").innerText = `${o.net_return_percent >= 0 ? '+' : ''}${o.net_return_percent.toFixed(2)}% on 3,000 THB Capital`;

  document.getElementById("bt-win-rate").innerText = `${o.win_rate_percent.toFixed(1)}%`;
  document.getElementById("bt-trade-count").innerText = `${o.win_trades} Wins / ${o.loss_trades} Losses (Total: ${o.total_trades})`;

  document.getElementById("bt-profit-factor").innerText = o.profit_factor.toFixed(2);
  document.getElementById("bt-max-dd").innerText = `${o.max_drawdown_percent.toFixed(2)}%`;
  document.getElementById("bt-max-dd-thb").innerText = `Maximum peak drop: ${o.max_drawdown_thb.toFixed(2)} THB`;

  document.getElementById("bt-final-equity").innerText = `Current Equity: ${report.final_equity_thb.toFixed(2)} THB`;

  // 2. In-Sample vs Out-of-Sample Comparison Table
  const splitTbody = document.getElementById("bt-split-table-body");
  splitTbody.innerHTML = `
    <tr>
      <td><strong>Total Trades Count</strong></td>
      <td>${inS.total_trades} trades</td>
      <td>${outS.total_trades} trades</td>
      <td><span class="dime-plan-badge badge-ready">Adequate Sample</span></td>
    </tr>
    <tr>
      <td><strong>Win Rate (%)</strong></td>
      <td style="font-weight: 700;">${inS.win_rate_percent.toFixed(1)}%</td>
      <td style="font-weight: 700; color: ${outS.win_rate_percent >= 45 ? 'var(--dime-green)' : 'var(--dime-red)'};">${outS.win_rate_percent.toFixed(1)}%</td>
      <td>${Math.abs(inS.win_rate_percent - outS.win_rate_percent) < 15 ? '✓ Robust (Stable)' : '⚠ Variance Observed'}</td>
    </tr>
    <tr>
      <td><strong>Profit Factor</strong></td>
      <td style="font-weight: 700;">${inS.profit_factor.toFixed(2)}</td>
      <td style="font-weight: 700;">${outS.profit_factor.toFixed(2)}</td>
      <td>${outS.profit_factor >= 1.2 ? '<span style="color: var(--dime-green);">✓ Profitable Out-of-Sample</span>' : 'Sub-optimal'}</td>
    </tr>
    <tr>
      <td><strong>Net Profit (THB)</strong></td>
      <td style="color: var(--dime-green); font-weight: 700;">+${inS.net_profit_thb.toFixed(2)} THB</td>
      <td style="color: ${outS.net_profit_thb >= 0 ? 'var(--dime-green)' : 'var(--dime-red)'}; font-weight: 700;">${outS.net_profit_thb >= 0 ? '+' : ''}${outS.net_profit_thb.toFixed(2)} THB</td>
      <td>${outS.net_profit_thb >= 0 ? '✓ Positive Drift' : 'Review Parameters'}</td>
    </tr>
    <tr>
      <td><strong>Max Drawdown (%)</strong></td>
      <td style="color: var(--dime-red);">${inS.max_drawdown_percent.toFixed(2)}%</td>
      <td style="color: var(--dime-red);">${outS.max_drawdown_percent.toFixed(2)}%</td>
      <td>${outS.max_drawdown_percent <= 10.0 ? '✓ Within Risk Tolerance' : 'High Volatility'}</td>
    </tr>
    <tr>
      <td><strong>Expectancy per Trade</strong></td>
      <td>${inS.expectancy_thb.toFixed(2)} THB</td>
      <td>${outS.expectancy_thb.toFixed(2)} THB</td>
      <td>${outS.expectancy_thb > 0 ? '✓ Positive Edge' : 'Negative Edge'}</td>
    </tr>
    <tr>
      <td><strong>Total Execution Costs (Exness Spread/Swap)</strong></td>
      <td>${inS.total_costs_thb.toFixed(2)} THB</td>
      <td>${outS.total_costs_thb.toFixed(2)} THB</td>
      <td><span style="color: var(--text-muted);">Real Spreads Subtracted</span></td>
    </tr>
  `;

  // 3. Equity Curve Canvas
  renderEquityCurveCanvas(report.equity_curve);

  // 4. Asset Breakdown Table
  const assetTbody = document.getElementById("bt-asset-table-body");
  assetTbody.innerHTML = "";
  for (const [sym, sMet] of Object.entries(report.symbol_breakdown || {})) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td style="font-weight: 800;">${sym}</td>
      <td>${sMet.total_trades}</td>
      <td>${sMet.win_rate_percent.toFixed(1)}%</td>
      <td style="font-weight: 700; color: ${sMet.net_profit_thb >= 0 ? 'var(--dime-green)' : 'var(--dime-red)'};">
        ${sMet.net_profit_thb >= 0 ? '+' : ''}${sMet.net_profit_thb.toFixed(2)} THB
      </td>
      <td>${sMet.profit_factor.toFixed(2)}</td>
    `;
    assetTbody.appendChild(tr);
  }

  // 5. Detailed Trade Logs
  const logTbody = document.getElementById("bt-trade-log-body");
  logTbody.innerHTML = "";
  const recentLogs = (report.trade_logs || []).slice(-30).reverse();
  recentLogs.forEach(t => {
    const tr = document.createElement("tr");
    const isWin = t.net_pnl_thb > 0;
    tr.innerHTML = `
      <td style="font-weight: 800;">${t.symbol}</td>
      <td style="font-size: 11.5px; color: var(--text-muted);">${t.exit_time.slice(0, 10)}</td>
      <td style="font-weight: 700; color: ${isWin ? 'var(--dime-green)' : 'var(--dime-red)'};">
        ${isWin ? '+' : ''}${t.net_pnl_thb.toFixed(2)}
      </td>
      <td style="font-size: 11px;"><code>${t.exit_reason}</code></td>
      <td><span class="dime-plan-badge ${t.sample_type === 'IN_SAMPLE' ? 'badge-waiting' : 'badge-ready'}" style="font-size: 9.5px;">${t.sample_type === 'IN_SAMPLE' ? 'In-Sample' : 'Out-Sample'}</span></td>
    `;
    logTbody.appendChild(tr);
  });
}

function renderEquityCurveCanvas(curveData) {
  const canvas = document.getElementById("equity-curve-canvas");
  if (!canvas || !curveData || curveData.length === 0) return;

  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();

  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const w = rect.width;
  const h = rect.height;
  const pad = 24;

  ctx.clearRect(0, 0, w, h);

  const values = curveData.map(d => d.equity_thb);
  const minVal = Math.min(...values) * 0.98;
  const maxVal = Math.max(...values) * 1.02;
  const valRange = Math.max(maxVal - minVal, 1.0);

  function getX(idx) {
    return pad + (idx / Math.max(values.length - 1, 1)) * (w - pad * 2);
  }
  function getY(val) {
    return (h - pad) - ((val - minVal) / valRange) * (h - pad * 2);
  }

  // Draw grid line at 3,000 THB base
  const baseY = getY(3000.0);
  ctx.strokeStyle = "#e2e8f0";
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(pad, baseY);
  ctx.lineTo(w - pad, baseY);
  ctx.stroke();
  ctx.setLineDash([]);

  // Base line label
  ctx.fillStyle = "#94a3b8";
  ctx.font = "10.5px -apple-system, BlinkMacSystemFont, sans-serif";
  ctx.fillText("Base: 3,000 THB", pad + 4, baseY - 4);

  // Draw Gradient Fill
  const gradient = ctx.createLinearGradient(0, pad, 0, h - pad);
  gradient.addColorStop(0, "rgba(0, 192, 118, 0.2)");
  gradient.addColorStop(1, "rgba(0, 192, 118, 0.0)");

  ctx.beginPath();
  ctx.moveTo(getX(0), h - pad);
  for (let i = 0; i < values.length; i++) {
    ctx.lineTo(getX(i), getY(values[i]));
  }
  ctx.lineTo(getX(values.length - 1), h - pad);
  ctx.closePath();
  ctx.fillStyle = gradient;
  ctx.fill();

  // Draw Curve Line
  ctx.beginPath();
  ctx.moveTo(getX(0), getY(values[0]));
  for (let i = 1; i < values.length; i++) {
    ctx.lineTo(getX(i), getY(values[i]));
  }
  ctx.strokeStyle = "#00c076";
  ctx.lineWidth = 2.5;
  ctx.stroke();

  // Draw End Point Dot
  const endX = getX(values.length - 1);
  const endY = getY(values[values.length - 1]);
  ctx.fillStyle = "#00c076";
  ctx.beginPath();
  ctx.arc(endX, endY, 4, 0, Math.PI * 2);
  ctx.fill();
}

// Selectors
function selectSymbol(symbol) {
  currentSymbol = symbol;
  document.querySelectorAll("#symbol-buttons .btn").forEach(btn => {
    btn.classList.toggle("active", btn.innerText.includes(symbol));
  });
  loadChartData(currentSymbol, currentTimeframe);
}

function selectTimeframe(tf) {
  currentTimeframe = tf;
  const labelMap = { "1W": "WEEK", "1D": "DAY", "15m": "M15", "5m": "M5", "1m": "M1" };
  document.querySelectorAll("#tf-buttons .btn").forEach(btn => {
    btn.classList.toggle("active", btn.innerText === labelMap[tf]);
  });
  loadChartData(currentSymbol, currentTimeframe);
}

function toggleEMA() {
  const visible = document.getElementById("check-ema").checked;
  Object.values(emaSeries).forEach(series => series.applyOptions({ visible }));
}

function toggleSR() {
  loadZones(currentSymbol);
}

// Manual Zone Creation
async function handleCreateManualZone(e) {
  e.preventDefault();
  const payload = {
    symbol: currentSymbol,
    timeframe: currentTimeframe,
    zone_type: document.getElementById("man-zone-type").value,
    label: document.getElementById("man-zone-label").value,
    price_high: parseFloat(document.getElementById("man-zone-high").value),
    price_low: parseFloat(document.getElementById("man-zone-low").value),
    is_locked: false
  };

  try {
    const res = await fetch("/api/zones/manual", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      document.getElementById("manual-zone-form").reset();
      loadZones(currentSymbol);
    }
  } catch (err) {
    alert("Failed to create manual zone: " + err);
  }
}

async function toggleLockZone(zoneId) {
  try {
    await fetch(`/api/zones/manual/${zoneId}/lock`, { method: "PATCH" });
    loadZones(currentSymbol);
  } catch (e) {
    alert("Error updating lock: " + e);
  }
}

async function deleteManualZone(zoneId) {
  if (!confirm("Are you sure you want to delete this manual zone?")) return;
  try {
    const res = await fetch(`/api/zones/manual/${zoneId}`, { method: "DELETE" });
    if (!res.ok) {
      const err = await res.json();
      alert(err.detail || "Cannot delete zone");
      return;
    }
    loadZones(currentSymbol);
  } catch (e) {
    alert("Error deleting zone: " + e);
  }
}

// Screenshot Capture
async function triggerSnapshot() {
  try {
    const res = await fetch("/api/capture", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        symbol: currentSymbol,
        timeframe: currentTimeframe,
        event_id: "DIME_VIEW_CAPTURE",
        notes: "Captured from Modern Fintech Light dashboard"
      })
    });
    const data = await res.json();
    alert(`Screenshot saved successfully:\n${data.metadata.file_name}\nStored in screenshots/${data.metadata.relative_path}`);
  } catch (err) {
    alert("Failed to capture screenshot: " + err);
  }
}

// Current Gallery Filter
let currentGalleryFilter = null;

function filterGallery(sym) {
  currentGalleryFilter = sym;
  document.querySelectorAll(".gallery-filters button").forEach(b => b.classList.remove("active"));
  const btnId = sym ? `gallery-filter-${sym}` : "gallery-filter-ALL";
  const btn = document.getElementById(btnId);
  if (btn) btn.classList.add("active");
  loadScreenshots();
}

// Load Gallery
async function loadScreenshots() {
  try {
    const url = currentGalleryFilter ? `/api/screenshots?symbol=${currentGalleryFilter}` : "/api/screenshots";
    const res = await fetch(url);
    const data = await res.json();
    const container = document.getElementById("gallery-container");
    container.innerHTML = "";

    const list = data.screenshots || [];
    if (list.length === 0) {
      const filterLabel = currentGalleryFilter ? `สำหรับ ${currentGalleryFilter}` : "";
      container.innerHTML = `<div style="grid-column: 1 / -1; color: var(--text-muted); text-align: center; padding: 40px;">ไม่พบประวัติภาพบันทึกกราฟ ${filterLabel} (สามารถกด "Capture Screenshot" ในหน้า Charts ได้ตลอดเวลา)</div>`;
      return;
    }

    list.forEach(item => {
      const card = document.createElement("div");
      card.className = "gallery-item";
      card.innerHTML = `
        <img class="gallery-thumb" src="/screenshots-view/${item.relative_path}" alt="${item.file_name}" onerror="this.src='/static/img/chart-placeholder.png'">
        <div class="gallery-info">
          <div style="font-weight: 800; font-size: 13px; color: var(--text-primary);">${item.symbol} [${item.timeframe}]</div>
          <div style="color: var(--text-muted); margin: 3px 0;">Event: ${item.event_id}</div>
          <div style="color: var(--text-secondary); font-size: 11.5px;">BKK: ${item.bangkok_time.slice(0, 19).replace('T', ' ')}</div>
          <div style="margin-top: 10px;">
            <a href="/screenshots-view/${item.relative_path}" target="_blank" class="btn" style="text-decoration: none; padding: 4px 10px; font-size: 11.5px;">View Full Image</a>
          </div>
        </div>
      `;
      container.appendChild(card);
    });
  } catch (err) {
    console.error("Failed to load gallery:", err);
  }
}

// Save Settings
async function handleSaveSettings(e) {
  e.preventDefault();
  const payload = {
    base_capital_thb: parseFloat(document.getElementById("setting-capital").value),
    max_leverage: parseFloat(document.getElementById("setting-leverage").value),
    risk_per_trade_percent: parseFloat(document.getElementById("setting-risk").value),
    allow_overnight: document.getElementById("setting-overnight").checked,
    allow_weekend: document.getElementById("setting-weekend").checked,
    execution_enabled: document.getElementById("setting-auto-exec").checked
  };

  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      alert("Settings saved successfully.");
      loadSystemStatus();
      loadMT5Status();
    }
  } catch (err) {
    alert("Failed to save settings: " + err);
  }
}

// -------------------------------------------------------------
// TRADING JOURNAL PRO DASHBOARD (MULTI-PORTFOLIO ISOLATION)
// -------------------------------------------------------------

let activeJournalPortfolioId = null;
let cachedJournalDashboardData = null;
let journalMetricMode = "R"; // "R", "MONEY", "PERCENT"

function formatPortMoney(val, currency = null) {
  if (val === undefined || val === null || isNaN(val)) return "-";
  const curr = currency || (cachedJournalDashboardData?.portfolio?.currency) || "USD";
  const num = Number(val);
  if (curr === "USC") {
    return `${num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USC`;
  } else if (curr === "THB") {
    return `฿${num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  } else {
    return `$${num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
}

function setJournalMetricMode(mode) {
  journalMetricMode = mode;
  ["R", "MONEY", "PERCENT"].forEach(m => {
    const btn = document.getElementById(`btn-mode-${m}`);
    if (btn) {
      if (m === mode) {
        btn.classList.add("active");
        btn.style.background = "var(--bg-card)";
        btn.style.color = "var(--text-primary)";
        btn.style.boxShadow = "0 1px 3px rgba(0,0,0,0.1)";
      } else {
        btn.classList.remove("active");
        btn.style.background = "transparent";
        btn.style.color = "var(--text-secondary)";
        btn.style.boxShadow = "none";
      }
    }
  });

  const hintEl = document.getElementById("jp-view-mode-hint");
  if (hintEl) {
    let modeText = "🎯 R Multiple";
    if (mode === "MONEY") modeText = "💵 จำนวนเงิน (Amount)";
    if (mode === "PERCENT") modeText = "📈 เปอร์เซ็นต์ (%)";
    hintEl.innerHTML = `แสดงผลทุกการ์ด, กราฟ, และปฏิทินเป็นค่า: <strong style="color: var(--dime-blue);">${modeText}</strong>`;
  }

  if (cachedJournalDashboardData) {
    updateJournalDashboardDisplay();
  }
}

async function loadJournalPortfolios() {
  try {
    const res = await fetch("/api/portfolios");
    const data = await res.json();
    const select = document.getElementById("jp-portfolio-select");
    if (!select) return;

    select.innerHTML = "";
    (data.portfolios || []).forEach(p => {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = `${p.name} (${p.currency || 'USD'} ${p.initial_capital || 1000})`;
      select.appendChild(opt);
    });

    if (!activeJournalPortfolioId && data.portfolios && data.portfolios.length > 0) {
      activeJournalPortfolioId = data.portfolios[0].id;
    }

    if (activeJournalPortfolioId) {
      select.value = activeJournalPortfolioId;
      await loadJournalDashboard(activeJournalPortfolioId);
      await loadJournalTrades();
      // Auto-sync live MT5 orders in background
      syncMT5ToJournal(true);
    }
  } catch (err) {
    console.error("Failed to load journal portfolios:", err);
  }
}

async function onSelectJournalPortfolio(portfolioId) {
  activeJournalPortfolioId = portfolioId;
  await loadJournalDashboard(portfolioId);
  await loadJournalTrades();
}

async function loadJournalDashboard(portfolioId) {
  try {
    const res = await fetch(`/api/portfolios/${portfolioId}/dashboard`);
    if (!res.ok) return;
    const data = await res.json();
    cachedJournalDashboardData = data;

    // 1. Update Portfolio Header Context
    const p = data.portfolio;
    const capEl = document.getElementById("jp-cap-pill");
    const riskEl = document.getElementById("jp-risk-pill");
    const accEl = document.getElementById("jp-acc-pill");
    if (capEl) capEl.textContent = `CAPITAL: ${formatPortMoney(p.initial_capital, p.currency)}`;
    if (riskEl) riskEl.textContent = `RISK: ${p.risk_per_trade_percent}% (${formatPortMoney(p.risk_amount_per_trade, p.currency)}/ไม้)`;
    if (accEl) accEl.textContent = `ACCOUNT: ${p.account_login || 'DEFAULT'}`;

    // Check MT5 connection status for this portfolio
    try {
      const mt5Res = await fetch(`/api/portfolios/${portfolioId}/mt5-status`);
      if (mt5Res.ok) {
        const mt5Data = await mt5Res.json();
        const mt5Pill = document.getElementById("jp-mt5-status-pill");
        if (mt5Pill) {
          if (mt5Data.mt5_info && mt5Data.mt5_info.connected) {
            const accNum = mt5Data.mt5_info.login;
            const accCurr = mt5Data.mt5_info.is_cent ? "USC Cent" : mt5Data.mt5_info.currency;
            mt5Pill.textContent = `🟢 MT5: #${accNum} (${accCurr})`;
            mt5Pill.style.background = "var(--dime-green-bg)";
            mt5Pill.style.color = "var(--dime-green)";
            mt5Pill.style.border = "1px solid rgba(16, 185, 129, 0.4)";
          } else {
            mt5Pill.textContent = `⚪ MT5: DISCONNECTED`;
            mt5Pill.style.background = "#f1f5f9";
            mt5Pill.style.color = "var(--text-muted)";
            mt5Pill.style.border = "1px solid var(--border-color)";
          }
        }
      }
    } catch (e) {
      console.warn("Could not check MT5 status:", e);
    }

    // Render all components based on active metric mode
    updateJournalDashboardDisplay();

  } catch (err) {
    console.error("Failed to load portfolio dashboard:", err);
  }
}

function updateJournalDashboardDisplay() {
  if (!cachedJournalDashboardData) return;
  const data = cachedJournalDashboardData;
  const p = data.portfolio;
  const k = data.kpi;
  const qs = data.quick_stats;
  const initCap = p.initial_capital || 1000.0;
  const curr = p.currency || "USD";
  const isCent = (curr === "USC");

  const isR = (journalMetricMode === "R");
  const isMoney = (journalMetricMode === "MONEY");
  const isPercent = (journalMetricMode === "PERCENT");

  // 1. KPI Cards
  const elBal = document.getElementById("jp-kpi-balance");
  const elPnl = document.getElementById("jp-kpi-pnl");
  const elTotR = document.getElementById("jp-kpi-total-r");
  const elTotRTitle = document.getElementById("jp-kpi-ret-title");
  const elTotRSub = document.getElementById("jp-kpi-total-r-sub");
  const elWr = document.getElementById("jp-kpi-winrate");
  const elWrSub = document.getElementById("jp-kpi-wr-sub");
  const elTrades = document.getElementById("jp-kpi-trades");
  const elTradesSub = document.getElementById("jp-kpi-trades-sub");
  const elAvgW = document.getElementById("jp-kpi-avg-win");
  const elAvgWTitle = document.getElementById("jp-kpi-avgw-title");
  const elAvgWSub = document.getElementById("jp-kpi-avgw-sub");
  const elAvgL = document.getElementById("jp-kpi-avg-loss");
  const elAvgLTitle = document.getElementById("jp-kpi-avgl-title");
  const elAvgLSub = document.getElementById("jp-kpi-avgl-sub");

  if (elBal) elBal.textContent = formatPortMoney(k.current_balance, curr);
  if (elPnl) {
    const pnlSign = k.total_pnl >= 0 ? "+" : "";
    if (isCent) {
      const usdVal = (k.total_pnl / 100.0).toFixed(2);
      elPnl.textContent = `Net P/L: ${pnlSign}${k.total_pnl.toFixed(2)} USC (~${pnlSign}$${usdVal})`;
    } else {
      elPnl.textContent = `Net P/L: ${pnlSign}${formatPortMoney(Math.abs(k.total_pnl), curr)}`;
    }
    elPnl.style.color = k.total_pnl >= 0 ? "var(--dime-green)" : "var(--dime-red)";
  }

  // Return card
  if (elTotRTitle) {
    elTotRTitle.textContent = isR ? "ผลตอบแทนรวม (Total R)" : (isMoney ? "กำไรขาดทุนสุทธิ (Net P/L)" : "ผลตอบแทนสะสม (% Return)");
  }
  if (elTotR) {
    if (isR) {
      const rSign = k.total_r >= 0 ? "+" : "";
      elTotR.textContent = `${rSign}${k.total_r.toFixed(2)} R`;
      elTotR.style.color = k.total_r >= 0 ? "var(--dime-green)" : "var(--dime-red)";
    } else if (isMoney) {
      const pnlSign = k.total_pnl >= 0 ? "+" : "-";
      elTotR.textContent = `${pnlSign}${formatPortMoney(Math.abs(k.total_pnl), curr)}`;
      elTotR.style.color = k.total_pnl >= 0 ? "var(--dime-green)" : "var(--dime-red)";
    } else {
      const pctVal = (k.total_pnl / initCap) * 100.0;
      const pctSign = pctVal >= 0 ? "+" : "";
      elTotR.textContent = `${pctSign}${pctVal.toFixed(2)}%`;
      elTotR.style.color = pctVal >= 0 ? "var(--dime-green)" : "var(--dime-red)";
    }
  }
  if (elTotRSub) {
    elTotRSub.textContent = isR ? "ผลตอบแทนสะสมคิดเป็น R" : (isMoney ? "กำไรสุทธิเทียบตามเงินต้น" : `เทียบเงินต้น ${formatPortMoney(initCap, curr)}`);
  }

  // Avg Win / Loss
  if (elAvgWTitle) elAvgWTitle.textContent = isR ? "เฉลี่ยชนะ (Avg Win R)" : (isMoney ? `เฉลี่ยชนะ (${curr})` : "เฉลี่ยชนะ (%)");
  if (elAvgLTitle) elAvgLTitle.textContent = isR ? "เฉลี่ยแพ้ (Avg Loss R)" : (isMoney ? `เฉลี่ยแพ้ (${curr})` : "เฉลี่ยแพ้ (%)");

  if (elAvgW) {
    if (isR) elAvgW.textContent = `+${k.avg_win_r.toFixed(2)} R`;
    else if (isMoney) elAvgW.textContent = `+${formatPortMoney(k.avg_win_pnl || 0, curr)}`;
    else elAvgW.textContent = `+${(((k.avg_win_pnl || 0) / initCap) * 100.0).toFixed(2)}%`;
  }
  if (elAvgL) {
    if (isR) elAvgL.textContent = `${k.avg_loss_r.toFixed(2)} R`;
    else if (isMoney) elAvgL.textContent = `${formatPortMoney(k.avg_loss_pnl || 0, curr)}`;
    else elAvgL.textContent = `${(((k.avg_loss_pnl || 0) / initCap) * 100.0).toFixed(2)}%`;
  }

  if (elWr) elWr.textContent = `${k.win_rate.toFixed(1)}%`;
  if (elWrSub) elWrSub.textContent = `${k.win_count} Wins / ${k.loss_count} Losses / ${k.be_count} BE`;
  if (elTrades) elTrades.textContent = k.total_trades;
  if (elTradesSub) elTradesSub.textContent = `ออเดอร์ทั้งหมดในพอร์ตนี้`;

  // 2. Quick Stats
  const elBt = document.getElementById("jp-stat-best-trade");
  const elWt = document.getElementById("jp-stat-worst-trade");
  const elBm = document.getElementById("jp-stat-best-month");
  const elExp = document.getElementById("jp-stat-expectancy");

  if (elBt) {
    if (isR) elBt.textContent = qs.best_trade_r > 0 ? `+${qs.best_trade_r.toFixed(2)} R` : `${qs.best_trade_r.toFixed(2)} R`;
    else if (isMoney) elBt.textContent = (qs.best_trade_pnl >= 0 ? "+" : "") + formatPortMoney(qs.best_trade_pnl, curr);
    else elBt.textContent = `${((qs.best_trade_pnl / initCap) * 100.0).toFixed(2)}%`;
  }
  if (elWt) {
    if (isR) elWt.textContent = `${qs.worst_trade_r.toFixed(2)} R`;
    else if (isMoney) elWt.textContent = formatPortMoney(qs.worst_trade_pnl, curr);
    else elWt.textContent = `${((qs.worst_trade_pnl / initCap) * 100.0).toFixed(2)}%`;
  }
  if (elBm) elBm.textContent = qs.best_month;
  if (elExp) {
    if (isR) {
      const expSign = qs.avg_r_per_trade >= 0 ? "+" : "";
      elExp.textContent = `${expSign}${qs.avg_r_per_trade.toFixed(2)} R`;
    } else if (isMoney) {
      const pnlSign = qs.avg_pnl_per_trade >= 0 ? "+" : "";
      elExp.textContent = `${pnlSign}${formatPortMoney(qs.avg_pnl_per_trade, curr)}`;
    } else {
      const expPct = (qs.avg_pnl_per_trade / initCap) * 100.0;
      const pctSign = expPct >= 0 ? "+" : "";
      elExp.textContent = `${pctSign}${expPct.toFixed(2)}%`;
    }
  }

  // 3. Render Setup Breakdown Table
  renderSetupBreakdownTable(data.setup_breakdown);

  // 4. Render Charts
  drawCumulativeRChart("jp-cumulative-canvas", data.cumulative_curve);
  drawMonthlyRChart("jp-monthly-canvas", data.monthly_performance);

  // 5. Render Calendar Heatmap
  if (!userSelectedCalendarMonth) {
    goToLatestCalendarDate(false);
  } else {
    renderCalendarForSelectedMonth();
  }
}

function renderSetupBreakdownTable(setups) {
  const tbody = document.getElementById("jp-setup-table-body");
  if (!tbody) return;

  if (!setups || setups.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 24px;">ยังไม่มีข้อมูลการเทรดในพอร์ตนี้</td></tr>`;
    return;
  }

  const isR = (journalMetricMode === "R");
  const isMoney = (journalMetricMode === "MONEY");
  const isPercent = (journalMetricMode === "PERCENT");
  const curr = cachedJournalDashboardData?.portfolio?.currency || "USD";
  const initCap = cachedJournalDashboardData?.portfolio?.initial_capital || 1000.0;

  tbody.innerHTML = setups.map(s => {
    let totValFormatted = "";
    let avgValFormatted = "";
    let isPos = false;

    if (isR) {
      isPos = s.total_r >= 0;
      totValFormatted = `${isPos ? '+' : ''}${s.total_r.toFixed(2)} R`;
      avgValFormatted = `${s.avg_r >= 0 ? '+' : ''}${s.avg_r.toFixed(2)} R`;
    } else if (isMoney) {
      const pnl = s.total_pnl || 0;
      isPos = pnl >= 0;
      totValFormatted = `${isPos ? '+' : ''}${formatPortMoney(pnl, curr)}`;
      avgValFormatted = `${(s.avg_pnl || 0) >= 0 ? '+' : ''}${formatPortMoney(s.avg_pnl || 0, curr)}`;
    } else {
      const pct = ((s.total_pnl || 0) / initCap) * 100.0;
      const avgPct = ((s.avg_pnl || 0) / initCap) * 100.0;
      isPos = pct >= 0;
      totValFormatted = `${isPos ? '+' : ''}${pct.toFixed(2)}%`;
      avgValFormatted = `${avgPct >= 0 ? '+' : ''}${avgPct.toFixed(2)}%`;
    }

    const rColor = isPos ? "var(--dime-green)" : "var(--dime-red)";
    return `
      <tr>
        <td style="font-weight: 700; color: var(--text-primary);">${s.setup}</td>
        <td style="text-align: center; font-weight: 600;">${s.trades}</td>
        <td style="text-align: center;">
          <span style="font-weight: 700; color: ${s.win_rate >= 50 ? 'var(--dime-green)' : 'var(--dime-amber)'};">${s.win_rate}%</span>
        </td>
        <td class="jp-num" style="text-align: right; color: ${rColor}; font-weight: 700;">
          ${avgValFormatted}
        </td>
        <td class="jp-num" style="text-align: right; color: ${rColor}; font-weight: 800;">
          ${totValFormatted}
        </td>
      </tr>
    `;
  }).join("");
}

function drawCumulativeRChart(canvasId, curveData) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const w = rect.width;
  const h = rect.height;
  ctx.clearRect(0, 0, w, h);

  if (!curveData || curveData.length === 0) {
    ctx.fillStyle = "#94a3b8";
    ctx.font = "13px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("ยังไม่มีประวัติการเทรดเพื่อพล็อตกราฟ", w / 2, h / 2);
    return;
  }

  const isR = (journalMetricMode === "R");
  const isMoney = (journalMetricMode === "MONEY");
  const isPercent = (journalMetricMode === "PERCENT");
  const curr = cachedJournalDashboardData?.portfolio?.currency || "USD";
  const initCap = cachedJournalDashboardData?.portfolio?.initial_capital || 1000.0;

  // Prepend starting point (Trade 0, Val = 0)
  const points = [{ trade_no: 0, val: 0.0 }, ...curveData.map(c => {
    let v = c.cumulative_r;
    if (isMoney) v = c.cumulative_pnl;
    else if (isPercent) v = (c.cumulative_pnl / initCap) * 100.0;
    return { trade_no: c.trade_no, val: v };
  })];

  const padding = { top: 25, right: 35, bottom: 35, left: 55 };
  const plotW = w - padding.left - padding.right;
  const plotH = h - padding.top - padding.bottom;

  let minVal = Math.min(...points.map(p => p.val), -0.5);
  let maxVal = Math.max(...points.map(p => p.val), 0.5);
  if (minVal === maxVal) { minVal -= 1; maxVal += 1; }

  // Draw Horizontal Zero Line
  const zeroY = padding.top + plotH - ((0 - minVal) / (maxVal - minVal)) * plotH;
  ctx.strokeStyle = "#cbd5e1";
  ctx.setLineDash([4, 4]);
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padding.left, zeroY);
  ctx.lineTo(padding.left + plotW, zeroY);
  ctx.stroke();
  ctx.setLineDash([]);

  // Label 0 line
  ctx.fillStyle = "#94a3b8";
  ctx.font = "10px ui-monospace, monospace";
  ctx.textAlign = "right";
  ctx.fillText("0.0", padding.left - 6, zeroY + 3.5);

  // Label Max & Min
  function formatAxisVal(v) {
    if (isR) return `${v.toFixed(1)} R`;
    if (isPercent) return `${v.toFixed(1)}%`;
    return formatPortMoney(v, curr);
  }
  ctx.fillText(formatAxisVal(maxVal), padding.left - 6, padding.top + 4);
  ctx.fillText(formatAxisVal(minVal), padding.left - 6, padding.top + plotH);

  // Map Coordinates
  const coords = points.map((p, i) => {
    const x = padding.left + (i / (points.length - 1)) * plotW;
    const y = padding.top + plotH - ((p.val - minVal) / (maxVal - minVal)) * plotH;
    return { x, y, val: p.val };
  });

  // Gradient Fill Area
  const lastVal = coords[coords.length - 1].val;
  const isPositive = lastVal >= 0;
  const grad = ctx.createLinearGradient(0, padding.top, 0, padding.top + plotH);
  if (isPositive) {
    grad.addColorStop(0, "rgba(16, 185, 129, 0.25)");
    grad.addColorStop(1, "rgba(16, 185, 129, 0.01)");
  } else {
    grad.addColorStop(0, "rgba(239, 68, 68, 0.25)");
    grad.addColorStop(1, "rgba(239, 68, 68, 0.01)");
  }

  ctx.beginPath();
  ctx.moveTo(coords[0].x, zeroY);
  coords.forEach(c => ctx.lineTo(c.x, c.y));
  ctx.lineTo(coords[coords.length - 1].x, zeroY);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  // Draw Line
  ctx.strokeStyle = isPositive ? "#10b981" : "#ef4444";
  ctx.lineWidth = 2.5;
  ctx.lineJoin = "round";
  ctx.beginPath();
  coords.forEach((c, idx) => {
    if (idx === 0) ctx.moveTo(c.x, c.y);
    else ctx.lineTo(c.x, c.y);
  });
  ctx.stroke();

  // Draw Points
  coords.forEach((c, idx) => {
    if (idx === 0) return;
    ctx.fillStyle = "#ffffff";
    ctx.strokeStyle = c.val >= 0 ? "#10b981" : "#ef4444";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(c.x, c.y, 3.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  });

  // Tag at last point
  const lastC = coords[coords.length - 1];
  ctx.fillStyle = isPositive ? "#059669" : "#dc2626";
  ctx.font = "bold 11px ui-monospace, monospace";
  ctx.textAlign = "left";
  const valSign = lastVal >= 0 ? "+" : "";
  let tagText = ` ${valSign}${lastVal.toFixed(2)} R`;
  if (isMoney) tagText = ` ${valSign}${formatPortMoney(Math.abs(lastVal), curr)}`;
  if (isPercent) tagText = ` ${valSign}${lastVal.toFixed(2)}%`;
  ctx.fillText(tagText, lastC.x + 3, lastC.y - 4);
}

function drawMonthlyRChart(canvasId, monthlyData) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const w = rect.width;
  const h = rect.height;
  ctx.clearRect(0, 0, w, h);

  if (!monthlyData || monthlyData.length === 0) return;

  const isR = (journalMetricMode === "R");
  const isMoney = (journalMetricMode === "MONEY");
  const isPercent = (journalMetricMode === "PERCENT");
  const curr = cachedJournalDashboardData?.portfolio?.currency || "USD";
  const initCap = cachedJournalDashboardData?.portfolio?.initial_capital || 1000.0;

  const padding = { top: 25, right: 20, bottom: 35, left: 45 };
  const plotW = w - padding.left - padding.right;
  const plotH = h - padding.top - padding.bottom;

  // Extract bar values based on mode
  const bars = monthlyData.map(m => {
    let v = m.total_r;
    if (isMoney) v = m.pnl;
    else if (isPercent) v = (m.pnl / initCap) * 100.0;
    return { name: m.name, val: v };
  });

  let minVal = Math.min(...bars.map(m => m.val), -0.5);
  let maxVal = Math.max(...bars.map(m => m.val), 0.5);
  if (minVal === maxVal) { minVal -= 1; maxVal += 1; }

  // Zero Line
  const zeroY = padding.top + plotH - ((0 - minVal) / (maxVal - minVal)) * plotH;
  ctx.strokeStyle = "#cbd5e1";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padding.left, zeroY);
  ctx.lineTo(padding.left + plotW, zeroY);
  ctx.stroke();

  // Label 0
  ctx.fillStyle = "#94a3b8";
  ctx.font = "10px ui-monospace, monospace";
  ctx.textAlign = "right";
  ctx.fillText("0", padding.left - 6, zeroY + 3.5);

  const barCount = bars.length;
  const barSlot = plotW / barCount;
  const barWidth = Math.max(8, barSlot * 0.58);

  bars.forEach((b, idx) => {
    const x = padding.left + idx * barSlot + (barSlot - barWidth) / 2;
    const yVal = padding.top + plotH - ((b.val - minVal) / (maxVal - minVal)) * plotH;
    const barH = Math.abs(yVal - zeroY);
    const topY = b.val >= 0 ? yVal : zeroY;

    // Bar rectangle
    ctx.fillStyle = b.val > 0 ? "#10b981" : (b.val < 0 ? "#ef4444" : "#e2e8f0");
    if (b.val !== 0) {
      ctx.fillRect(x, topY, barWidth, Math.max(barH, 2));
    }

    // Month Label
    ctx.fillStyle = "#64748b";
    ctx.font = "11px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(b.name, x + barWidth / 2, h - 12);

    // Value label
    if (b.val !== 0) {
      ctx.fillStyle = b.val > 0 ? "#059669" : "#dc2626";
      ctx.font = "bold 9px ui-monospace, monospace";
      const lblY = b.val >= 0 ? topY - 4 : topY + barH + 11;
      const sign = b.val > 0 ? "+" : "";
      let lblText = `${sign}${b.val.toFixed(1)}`;
      if (isR) lblText += "R";
      else if (isPercent) lblText += "%";
      ctx.fillText(lblText, x + barWidth / 2, lblY);
    }
  });
}

let userSelectedCalendarMonth = false;
let latestCalendarTargetDate = null;

function onCalendarMonthChanged() {
  userSelectedCalendarMonth = true;
  renderCalendarForSelectedMonth();
}

function getLatestJournalDate() {
  if (!cachedJournalDashboardData) {
    const now = new Date();
    return {
      year: now.getFullYear(),
      month: now.getMonth() + 1,
      day: now.getDate(),
      dateStr: `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
    };
  }

  const calData = cachedJournalDashboardData.calendar_daily || {};
  const datesWithTrades = Object.keys(calData).filter(d => calData[d] && calData[d].trades > 0);

  let targetDateStr = null;
  if (datesWithTrades.length > 0) {
    datesWithTrades.sort();
    targetDateStr = datesWithTrades[datesWithTrades.length - 1];
  } else if (Object.keys(calData).length > 0) {
    const allDates = Object.keys(calData).sort();
    targetDateStr = allDates[allDates.length - 1];
  }

  if (targetDateStr) {
    const parts = targetDateStr.split("-");
    return {
      year: parseInt(parts[0], 10),
      month: parseInt(parts[1], 10),
      day: parseInt(parts[2], 10),
      dateStr: targetDateStr
    };
  }

  const now = new Date();
  return {
    year: now.getFullYear(),
    month: now.getMonth() + 1,
    day: now.getDate(),
    dateStr: `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  };
}

function goToLatestCalendarDate(userTriggered = true) {
  const latest = getLatestJournalDate();
  latestCalendarTargetDate = latest.dateStr;

  const monthSelect = document.getElementById("jp-calendar-month-select");
  if (monthSelect) {
    monthSelect.value = String(latest.month);
  }

  if (userTriggered) {
    userSelectedCalendarMonth = true;
  }

  renderCalendarForSelectedMonth();

  if (userTriggered) {
    setTimeout(() => {
      const el = document.querySelector(".jp-cal-day-cell.is-latest-day");
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    }, 50);
  }
}

function renderCalendarForSelectedMonth() {
  if (!cachedJournalDashboardData) return;
  const monthSelect = document.getElementById("jp-calendar-month-select");
  const selectedMonth = parseInt(monthSelect ? monthSelect.value : "1", 10);
  const container = document.getElementById("jp-calendar-grid");
  if (!container) return;

  const calData = cachedJournalDashboardData.calendar_daily || {};
  const latestInfo = getLatestJournalDate();
  const latestDateStr = latestCalendarTargetDate || latestInfo.dateStr;
  const year = 2026;
  const isR = (journalMetricMode === "R");
  const isMoney = (journalMetricMode === "MONEY");
  const isPercent = (journalMetricMode === "PERCENT");
  const curr = cachedJournalDashboardData?.portfolio?.currency || "USD";
  const initCap = cachedJournalDashboardData?.portfolio?.initial_capital || 1000.0;

  // Header days Mon-Sun
  const dayNames = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];
  let html = dayNames.map(d => `<div class="jp-cal-day-header">${d}</div>`).join("");

  const firstDate = new Date(year, selectedMonth - 1, 1);
  let firstDay = firstDate.getDay();
  firstDay = (firstDay + 6) % 7;

  const daysInMonth = new Date(year, selectedMonth, 0).getDate();

  for (let i = 0; i < firstDay; i++) {
    html += `<div class="jp-cal-day-cell inactive"></div>`;
  }

  let monthTotalR = 0.0;
  let monthTotalPnl = 0.0;

  for (let day = 1; day <= daysInMonth; day++) {
    const dayStr = String(day).padStart(2, '0');
    const mStr = String(selectedMonth).padStart(2, '0');
    const fullDate = `${year}-${mStr}-${dayStr}`;
    const isLatest = (fullDate === latestDateStr);

    const info = calData[fullDate];
    let cellClass = "jp-cal-day-cell";
    if (isLatest) {
      cellClass += " is-latest-day";
    }
    let badgeHtml = "";

    if (info && info.trades > 0) {
      monthTotalR += info.total_r;
      monthTotalPnl += (info.pnl || 0);

      let badgeText = "";
      if (isR) {
        badgeText = `${info.total_r > 0 ? '+' : ''}${info.total_r.toFixed(1)}R`;
      } else if (isMoney) {
        badgeText = `${(info.pnl || 0) > 0 ? '+' : ''}${formatPortMoney(info.pnl, curr)}`;
      } else {
        const dPct = ((info.pnl || 0) / initCap) * 100.0;
        badgeText = `${dPct > 0 ? '+' : ''}${dPct.toFixed(1)}%`;
      }

      if (info.total_r > 0 || (info.pnl || 0) > 0) {
        cellClass += " has-trades-win";
        badgeHtml = `<div class="jp-cal-r-badge" style="color: #15803d;">${badgeText}</div>`;
      } else if (info.total_r < 0 || (info.pnl || 0) < 0) {
        cellClass += " has-trades-loss";
        badgeHtml = `<div class="jp-cal-r-badge" style="color: #b91c1c;">${badgeText}</div>`;
      } else {
        badgeHtml = `<div class="jp-cal-r-badge" style="color: #64748b;">0.0</div>`;
      }
    }

    html += `
      <div class="${cellClass}" id="jp-day-${fullDate}">
        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
          <span class="jp-cal-day-num">${day}${isLatest ? ' <span class="jp-latest-tag">LATEST</span>' : ''}</span>
          ${info && info.trades > 0 ? `<span style="font-size: 9.5px; color: var(--text-muted); font-weight: 700;">${info.trades}t</span>` : ''}
        </div>
        ${badgeHtml}
      </div>
    `;
  }

  container.innerHTML = html;

  const monthPill = document.getElementById("jp-cal-month-total-pill");
  if (monthPill) {
    let pillText = "";
    let isPos = false;
    if (isR) {
      isPos = monthTotalR >= 0;
      pillText = `MONTH: ${isPos ? '+' : ''}${monthTotalR.toFixed(1)} R`;
    } else if (isMoney) {
      isPos = monthTotalPnl >= 0;
      pillText = `MONTH: ${isPos ? '+' : ''}${formatPortMoney(monthTotalPnl, curr)}`;
    } else {
      const mPct = (monthTotalPnl / initCap) * 100.0;
      isPos = mPct >= 0;
      pillText = `MONTH: ${isPos ? '+' : ''}${mPct.toFixed(1)}%`;
    }
    monthPill.textContent = pillText;
    monthPill.style.background = isPos ? "var(--dime-green-bg)" : "var(--dime-red-bg)";
    monthPill.style.color = isPos ? "var(--dime-green)" : "var(--dime-red)";
  }
}

async function loadJournalTrades() {
  if (!activeJournalPortfolioId) return;

  const outcomeFilter = document.getElementById("jp-filter-outcome")?.value || "";
  const symbolFilter = document.getElementById("jp-filter-symbol")?.value || "";

  let url = `/api/portfolios/${activeJournalPortfolioId}/trades?limit=150`;
  if (outcomeFilter) url += `&outcome=${outcomeFilter}`;
  if (symbolFilter) url += `&symbol=${encodeURIComponent(symbolFilter)}`;

  try {
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    renderJournalTradesTable(data.trades || []);
  } catch (err) {
    console.error("Failed to load journal trades:", err);
  }
}

function renderJournalTradesTable(trades) {
  const tbody = document.getElementById("jp-trades-table-body");
  if (!tbody) return;

  if (!trades || trades.length === 0) {
    tbody.innerHTML = `<tr><td colspan="12" style="text-align: center; color: var(--text-muted); padding: 30px;">ไม่มีรายการเทรดตรงตามเงื่อนไขที่เลือก</td></tr>`;
    return;
  }

  tbody.innerHTML = trades.map(t => {
    let outcomeBadge = `<span class="jp-badge-be">BE</span>`;
    if (t.outcome === "W") outcomeBadge = `<span class="jp-badge-w">WIN</span>`;
    if (t.outcome === "L") outcomeBadge = `<span class="jp-badge-l">LOSS</span>`;

    const dirBadge = t.direction === "BUY"
      ? `<span style="color: var(--dime-green); font-weight: 700;">🟢 BUY</span>`
      : `<span style="color: var(--dime-red); font-weight: 700;">🔴 SELL</span>`;

    const pnlSign = t.total_pnl >= 0 ? "+" : "";
    const pnlColor = t.total_pnl >= 0 ? "var(--dime-green)" : "var(--dime-red)";
    const rSign = t.r_multiple >= 0 ? "+" : "";
    const cumSign = t.cumulative_r >= 0 ? "+" : "";

    const tvLink = t.tradingview_url
      ? `<a href="${t.tradingview_url}" target="_blank" style="color: var(--dime-blue); text-decoration: underline; font-size: 11.5px;">ชาร์ต ↗</a>`
      : "";

    const noteText = t.comment ? `<div style="font-size: 11.5px; color: var(--text-secondary); max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${t.comment}">${t.comment}</div>` : "";

    return `
      <tr>
        <td style="font-weight: 700; color: var(--text-muted);">${t.trade_no}</td>
        <td class="jp-num" style="font-size: 11px; color: var(--text-muted); font-weight: 600;">${t.mt5_ticket ? '#' + t.mt5_ticket : '-'}</td>
        <td style="font-size: 12px; color: var(--text-secondary);">${t.trade_date}</td>
        <td style="font-weight: 800; color: var(--text-primary);">${t.symbol}</td>
        <td>${dirBadge}</td>
        <td style="font-size: 12px; font-weight: 600;">${t.setup || '-'}</td>
        <td class="jp-num" style="text-align: right;">${formatPortMoney(t.risk_usd)}</td>
        <td class="jp-num" style="text-align: right; color: ${pnlColor}; font-weight: 700;">${pnlSign}${formatPortMoney(Math.abs(t.total_pnl))}</td>
        <td class="jp-num" style="text-align: right; color: ${pnlColor}; font-weight: 800;">${rSign}${t.r_multiple.toFixed(2)} R</td>
        <td class="jp-num" style="text-align: right; font-weight: 700; color: ${t.cumulative_r >= 0 ? 'var(--dime-green)' : 'var(--dime-red)'};">${cumSign}${t.cumulative_r.toFixed(2)} R</td>
        <td style="text-align: center;">${outcomeBadge}</td>
        <td>
          <div style="display: flex; gap: 6px; align-items: center;">
            ${tvLink}
            ${noteText}
          </div>
        </td>
        <td style="text-align: center;">
          <button class="btn btn-sm btn-danger" style="padding: 2px 6px; font-size: 11px;" onclick="deleteJournalTrade(${t.id})">✕</button>
        </td>
      </tr>
    `;
  }).join("");
}

function openRecordTradeModal() {
  const modal = document.getElementById("modal-record-trade");
  if (!modal) return;
  // Set default date to today
  const today = new Date().toISOString().split("T")[0];
  const dateInput = document.getElementById("trade-in-date");
  if (dateInput) dateInput.value = today;

  // Set default risk from active portfolio
  if (cachedJournalDashboardData && cachedJournalDashboardData.portfolio) {
    const riskInput = document.getElementById("trade-in-risk");
    if (riskInput) riskInput.value = cachedJournalDashboardData.portfolio.risk_amount_per_trade;
  }

  modal.style.display = "flex";
}

function closeRecordTradeModal() {
  const modal = document.getElementById("modal-record-trade");
  if (modal) modal.style.display = "none";
}

async function handleSaveJournalTrade(e) {
  e.preventDefault();
  if (!activeJournalPortfolioId) {
    alert("กรุณาเลือกพอร์ตก่อนบันทึกไม้เทรด");
    return;
  }

  const payload = {
    trade_date: document.getElementById("trade-in-date").value,
    symbol: document.getElementById("trade-in-symbol").value.trim().toUpperCase(),
    direction: document.getElementById("trade-in-direction").value,
    setup: document.getElementById("trade-in-setup").value.trim(),
    risk_usd: parseFloat(document.getElementById("trade-in-risk").value) || 10.0,
    total_pnl: parseFloat(document.getElementById("trade-in-pnl").value) || 0.0,
    r_multiple: document.getElementById("trade-in-r").value ? parseFloat(document.getElementById("trade-in-r").value) : null,
    outcome: document.getElementById("trade-in-outcome").value || null,
    tradingview_url: document.getElementById("trade-in-tv").value.trim() || null,
    comment: document.getElementById("trade-in-comment").value.trim() || null
  };

  try {
    const res = await fetch(`/api/portfolios/${activeJournalPortfolioId}/trades`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      closeRecordTradeModal();
      await loadJournalDashboard(activeJournalPortfolioId);
      await loadJournalTrades();
    } else {
      const err = await res.json();
      alert("บันทึกไม่สำเร็จ: " + (err.detail || JSON.stringify(err)));
    }
  } catch (err) {
    alert("เกิดข้อผิดพลาด: " + err);
  }
}

async function deleteJournalTrade(tradeId) {
  if (!confirm("คุณแน่ใจหรือไม่ว่าต้องการลบรายการเทรดนี้?")) return;
  try {
    const res = await fetch(`/api/portfolios/${activeJournalPortfolioId}/trades/${tradeId}`, {
      method: "DELETE"
    });
    if (res.ok) {
      await loadJournalDashboard(activeJournalPortfolioId);
      await loadJournalTrades();
    }
  } catch (err) {
    alert("ลบไม่สำเร็จ: " + err);
  }
}

function openNewPortfolioModal() {
  const modal = document.getElementById("modal-new-portfolio");
  if (modal) modal.style.display = "flex";
}

function closeNewPortfolioModal() {
  const modal = document.getElementById("modal-new-portfolio");
  if (modal) modal.style.display = "none";
}

async function handleCreatePortfolio(e) {
  e.preventDefault();
  const payload = {
    id: document.getElementById("port-in-id").value.trim(),
    name: document.getElementById("port-in-name").value.trim(),
    initial_capital: parseFloat(document.getElementById("port-in-cap").value) || 1000.0,
    risk_per_trade_percent: parseFloat(document.getElementById("port-in-risk").value) || 1.0,
    currency: document.getElementById("port-in-curr").value,
    account_login: document.getElementById("port-in-acc").value.trim() || null,
    description: document.getElementById("port-in-desc").value.trim() || null
  };

  try {
    const res = await fetch("/api/portfolios", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      closeNewPortfolioModal();
      activeJournalPortfolioId = payload.id;
      await loadJournalPortfolios();
    } else {
      const err = await res.json();
      alert("สร้างพอร์ตไม่สำเร็จ: " + (err.detail || JSON.stringify(err)));
    }
  } catch (err) {
    alert("เกิดข้อผิดพลาด: " + err);
  }
}

async function seedJournalData() {
  if (!activeJournalPortfolioId) return;
  try {
    const res = await fetch(`/api/portfolios/${activeJournalPortfolioId}/seed-sample`, {
      method: "POST"
    });
    const data = await res.json();
    alert(`ผลการ Seed: ${data.status} (${data.message || (data.count + ' trades added')})`);
    await loadJournalDashboard(activeJournalPortfolioId);
    await loadJournalTrades();
  } catch (err) {
    alert("เกิดข้อผิดพลาดในการโหลดข้อมูลตัวอย่าง: " + err);
  }
}

async function syncMT5ToJournal(isAuto = false) {
  if (!activeJournalPortfolioId) return;
  const btn = document.getElementById("btn-sync-mt5");
  if (btn && !isAuto) {
    btn.textContent = "⏳ กำลังซิงก์ MT5...";
    btn.disabled = true;
  }

  try {
    const res = await fetch(`/api/portfolios/${activeJournalPortfolioId}/sync-mt5`, {
      method: "POST"
    });
    const data = await res.json();
    if (res.ok) {
      if (!isAuto) {
        alert(data.message || `ซิงก์สำเร็จ: เพิ่มใหม่ ${data.synced_count} ไม้`);
      }
      await loadJournalDashboard(activeJournalPortfolioId);
      await loadJournalTrades();
    } else {
      if (!isAuto) {
        alert("เกิดข้อผิดพลาดในการซิงก์: " + (data.detail || data.message || "Unknown error"));
      }
    }
  } catch (err) {
    if (!isAuto) {
      alert("ไม่สามารถเชื่อมต่อ MT5 ได้: " + err);
    }
  } finally {
    if (btn) {
      btn.innerHTML = "🔄 ซิงก์จาก MT5 (Sync MT5)";
      btn.disabled = false;
    }
  }
}


