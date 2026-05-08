/* The Rest of the Record — client-side search with lazy-loaded source shards */
(async () => {
  const PAGE_SIZE = 25;
  const PRELOAD_THRESHOLD_BYTES = 800_000; // shards under this load on demand without warning
  let meta = {};
  let mini = null;
  let docsBySource = {};       // src -> array of records (loaded on demand)
  let allDocs = [];            // flat union of loaded docs
  let byId = new Map();
  let labelByKey = {};
  let page = 0;
  let lastResults = [];
  let searchEnabled = false;
  let totalLoaded = 0;

  const $ = (s) => document.querySelector(s);
  const results = $("#results");
  const pager = $("#pager");
  const qEl = $("#q");
  const srcSel = $("#source-filter");
  const dateSel = $("#date-filter");
  const metaEl = $("#meta");

  // 1. Load meta (small, fast).
  try {
    meta = await fetch("index/meta.json").then(r => r.json());
  } catch (e) {
    results.innerHTML = `<p>Couldn't load index. (${e.message})</p>`;
    return;
  }

  meta.sources.forEach(s => { labelByKey[s.key] = s.label; });

  // Source filter
  for (const s of meta.sources) {
    if (s.count === 0) continue;
    const opt = document.createElement("option");
    opt.value = s.key;
    opt.textContent = `${s.label} (${s.count.toLocaleString()})`;
    srcSel.appendChild(opt);
  }

  // Sources footer
  const sourceList = $("#source-list");
  for (const s of meta.sources) {
    const li = document.createElement("li");
    li.innerHTML = `<span>${s.label}</span><span class="count">${s.count.toLocaleString()}</span>`;
    sourceList.appendChild(li);
  }
  $("#updated").textContent = (meta.updated_at || "").replace("T", " ").replace("Z", " UTC");

  // Build empty MiniSearch index — we'll add shards as they load.
  mini = new MiniSearch({
    fields: ["title", "summary", "full_text", "agency", "respondent", "outcome"],
    storeFields: ["id"],
    searchOptions: {
      boost: { title: 3, agency: 2, respondent: 2 },
      prefix: true,
      fuzzy: 0.15,
      combineWith: "AND",
    },
  });

  async function loadShard(key) {
    if (docsBySource[key]) return docsBySource[key];
    const r = await fetch(`index/sources/${key}.json`);
    const docs = await r.json();
    docsBySource[key] = docs;
    for (const d of docs) byId.set(d.id, d);
    allDocs = allDocs.concat(docs);
    mini.addAll(docs);
    totalLoaded += docs.length;
    return docs;
  }

  function formatBytes(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${Math.round(n/1024)} KB`;
    return `${(n/1024/1024).toFixed(1)} MB`;
  }

  async function ensureLoaded(forFilter) {
    // forFilter is the selected source key (or "" for all).
    const needed = forFilter
      ? [forFilter]
      : meta.sources.map(s => s.key);
    const toLoad = needed.filter(k => !docsBySource[k]);
    if (toLoad.length === 0) return;

    // Show loading state with byte estimate
    const totalBytes = toLoad.reduce((sum, k) => {
      const m = meta.sources.find(s => s.key === k);
      return sum + (m?.shard_bytes || 0);
    }, 0);
    metaEl.textContent = `Loading ${toLoad.length} source${toLoad.length === 1 ? "" : "s"} (${formatBytes(totalBytes)})…`;
    await Promise.all(toLoad.map(loadShard));
  }

  // Initial state from URL
  const params = new URLSearchParams(location.search);
  qEl.value = params.get("q") || "";
  if (params.get("source")) srcSel.value = params.get("source");
  if (params.get("days")) dateSel.value = params.get("days");

  function filterAndRank() {
    const q = qEl.value.trim();
    const src = srcSel.value;
    const days = parseInt(dateSel.value || "0", 10);
    let candidates;
    if (q) {
      const hits = mini.search(q);
      candidates = hits.map(h => ({...byId.get(h.id), _score: h.score})).filter(d => d.id);
    } else {
      candidates = (src ? (docsBySource[src] || []) : allDocs).slice();
      candidates.sort((a, b) => (b.decision_date || "").localeCompare(a.decision_date || ""));
    }
    if (src) candidates = candidates.filter(d => d.source === src);
    if (days) {
      const cutoff = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
      candidates = candidates.filter(d => (d.decision_date || "") >= cutoff);
    }
    return candidates;
  }

  function renderPage() {
    const start = page * PAGE_SIZE;
    const slice = lastResults.slice(start, start + PAGE_SIZE);
    if (!lastResults.length) {
      results.innerHTML = `<p style="margin-top:1rem">No matches.</p>`;
      pager.innerHTML = "";
      return;
    }
    const q = qEl.value.trim().toLowerCase();
    results.innerHTML = slice.map(d => {
      const label = labelByKey[d.source] || d.source;
      const link = d.doc_url || d.source_url || "#";
      const meta = [
        d.decision_date,
        d.agency,
        d.respondent,
        d.outcome,
        d.penalty,
      ].filter(Boolean).map(x => `<span>${esc(x)}</span>`).join("");
      const snippetSrc = (d.summary || d.full_text || "").slice(0, 320);
      return `
        <article class="result">
          <h3><span class="badge">${esc(label)}</span><a href="${esc(link)}" target="_blank" rel="noopener">${highlight(esc(d.title), q)}</a></h3>
          <div class="meta-line">${meta}</div>
          <p class="snippet">${highlight(esc(snippetSrc), q)}</p>
        </article>
      `;
    }).join("");

    const total = lastResults.length;
    const totalPages = Math.ceil(total / PAGE_SIZE);
    pager.innerHTML = `
      <button ${page === 0 ? "disabled" : ""} id="prev">‹ Prev</button>
      <span style="align-self:center;font-size:0.9rem;color:#5d6470">
        Page ${page + 1} of ${totalPages} — ${total.toLocaleString()} results
      </span>
      <button ${page >= totalPages - 1 ? "disabled" : ""} id="next">Next ›</button>
    `;
    $("#prev").onclick = () => { page--; renderPage(); window.scrollTo(0, 0); };
    $("#next").onclick = () => { page++; renderPage(); window.scrollTo(0, 0); };
  }

  async function update() {
    page = 0;
    const q = qEl.value.trim();
    const src = srcSel.value;
    // Decide what to load:
    // - if a source filter is active, only that source
    // - if there's a query, load everything (so the query searches all sources)
    // - if neither, load nothing yet (just show empty state)
    const needSource = src && !docsBySource[src];
    const needAll = !src && q && totalLoaded < meta.total;
    if (needSource || needAll) {
      await ensureLoaded(src);
    }

    lastResults = filterAndRank();
    metaEl.textContent =
      `${lastResults.length.toLocaleString()} of ${meta.total.toLocaleString()} records` +
      (totalLoaded < meta.total && !src && !q ? ` — pick a source or type to search` : "");

    // Update RSS link
    $("#rss-link").href = src ? `feeds/${src}.xml` : "feeds/all.xml";
    // Update URL
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (src) p.set("source", src);
    if (dateSel.value) p.set("days", dateSel.value);
    const qs = p.toString();
    history.replaceState(null, "", qs ? "?" + qs : location.pathname);
    renderPage();
  }

  let debounce;
  qEl.addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(update, 200); });
  srcSel.addEventListener("change", update);
  dateSel.addEventListener("change", update);

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function highlight(text, q) {
    if (!q) return text;
    const terms = q.split(/\s+/).filter(t => t.length > 1).map(escRe).join("|");
    if (!terms) return text;
    return text.replace(new RegExp(`(${terms})`, "gi"), "<mark>$1</mark>");
  }
  function escRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

  // Render initial state. If the URL had a query or source, kick off load.
  if (qEl.value.trim() || srcSel.value) {
    await update();
  } else {
    metaEl.textContent = `${meta.total.toLocaleString()} records across ${meta.sources.length} sources — pick a source or type to search`;
  }
})();
