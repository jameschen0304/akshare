let currentJobId = null;
let pollTimer = null;
let lastDetails = [];

const fmtNum = (n) => {
  if (n == null || Number.isNaN(n)) return "—";
  const x = Number(n);
  if (Math.abs(x) >= 1e8) return (x / 1e8).toFixed(2) + "亿";
  if (Math.abs(x) >= 1e4) return (x / 1e4).toFixed(2) + "万";
  return x.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
};

const fmtPct = (v) => {
  if (v == null) return "—";
  if (typeof v === "string" && v.includes("%")) return v;
  return (Number(v) * 100).toFixed(2) + "%";
};

const el = (id) => document.getElementById(id);

function readForm() {
  const f = el("scanForm");
  const fd = new FormData(f);
  return {
    pe_min: Number(fd.get("pe_min")),
    pe_max: Number(fd.get("pe_max")),
    periods: Number(fd.get("periods")),
    limit: Number(fd.get("limit")),
    max_workers: Number(fd.get("max_workers")),
    min_current_ratio: Number(fd.get("min_current_ratio")),
    revenue_growth_years: Number(fd.get("revenue_growth_years")),
    apply_hard_rules: f.querySelector('[name="apply_hard_rules"]').checked,
  };
}

async function startScan() {
  el("btnStart").disabled = true;
  el("btnExport").disabled = true;
  el("progressPanel").hidden = false;
  el("progressFill").style.width = "0%";
  el("progressText").textContent = "正在启动…";
  clearTables();

  try {
    const res = await fetch("/api/scan/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readForm()),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || res.statusText);
    }
    const data = await res.json();
    currentJobId = data.job_id;
    pollTimer = setInterval(pollStatus, 1200);
    pollStatus();
  } catch (e) {
    el("progressText").textContent = "启动失败: " + e.message;
    el("btnStart").disabled = false;
  }
}

async function pollStatus() {
  if (!currentJobId) return;
  try {
    const res = await fetch(`/api/scan/${currentJobId}/status`);
    const st = await res.json();
    el("progressFill").style.width = st.percent + "%";
    el("progressText").textContent = `${st.message} (${st.done}/${st.total}，命中 ${st.passed})`;

    if (st.status === "done" || st.status === "error") {
      clearInterval(pollTimer);
      pollTimer = null;
      el("btnStart").disabled = false;
      if (st.status === "error") {
        el("progressText").textContent = "错误: " + (st.error || "未知");
        return;
      }
      await loadResults();
      el("btnExport").disabled = false;
    } else if (st.status === "running" && st.passed > 0) {
      await loadResults();
    }
  } catch (e) {
    el("progressText").textContent = "轮询失败: " + e.message;
  }
}

async function loadResults() {
  const res = await fetch(`/api/scan/${currentJobId}/results`);
  const data = await res.json();
  lastDetails = data.details || [];
  renderSummary(data.summary || []);
  el("resultCount").textContent = String(data.count || 0);
}

function clearTables() {
  el("summaryTable").querySelector("tbody").innerHTML = "";
  el("detailTable").querySelector("tbody").innerHTML = "";
  el("detailPanel").hidden = true;
  el("resultCount").textContent = "0";
  lastDetails = [];
}

function renderSummary(rows) {
  const tbody = el("summaryTable").querySelector("tbody");
  tbody.innerHTML = rows
    .map(
      (r) => `
    <tr>
      <td class="num">${r.code}</td>
      <td>${r.name}</td>
      <td class="num">${r.pe_ttm}</td>
      <td class="num">${fmtNum(r.market_cap)}</td>
      <td>${r.latest_report_date || "—"}</td>
      <td>${r.latest_gross_margin || "—"}</td>
      <td>${r.latest_net_margin || "—"}</td>
      <td class="num">${r.latest_current_ratio ?? "—"}</td>
      <td title="${r.hard_rules_note || ""}">${r.hard_rules_pass ? "通过" : "—"}</td>
      <td><button type="button" class="link-btn" data-code="${r.code}">明细</button></td>
    </tr>`
    )
    .join("");

  tbody.querySelectorAll(".link-btn").forEach((btn) => {
    btn.addEventListener("click", () => showDetail(btn.dataset.code));
  });
}

function showDetail(code) {
  const stock = lastDetails.find((s) => s.code === code);
  if (!stock) return;
  el("detailPanel").hidden = false;
  el("detailTitle").textContent = `${stock.name} (${stock.code}) · PE ${stock.pe_ttm}`;

  const tbody = el("detailTable").querySelector("tbody");
  tbody.innerHTML = (stock.periods || [])
    .map(
      (p) => `
    <tr>
      <td>${p.report_date}</td>
      <td>${p.report_type || "—"}</td>
      <td class="num">${fmtNum(p.revenue)}</td>
      <td class="num">${fmtNum(p.operate_cost)}</td>
      <td class="num">${fmtNum(p.deduct_net_parent)}</td>
      <td class="num">${fmtNum(p.gross_profit)}</td>
      <td>${fmtPct(p.gross_margin)}</td>
      <td>${fmtPct(p.net_margin)}</td>
      <td class="num">${fmtNum(p.current_assets)}</td>
      <td class="num">${fmtNum(p.current_liab)}</td>
      <td class="num">${p.current_ratio != null ? Number(p.current_ratio).toFixed(3) : "—"}</td>
    </tr>`
    )
    .join("");
  el("detailPanel").scrollIntoView({ behavior: "smooth", block: "start" });
}

function exportCsv() {
  if (!currentJobId) return;
  window.location.href = `/api/scan/${currentJobId}/export`;
}

el("btnStart").addEventListener("click", startScan);
el("btnExport").addEventListener("click", exportCsv);
