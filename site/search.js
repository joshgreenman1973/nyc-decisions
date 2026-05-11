/* The Rest of the Record — client-side search with lazy-loaded source shards */
(async () => {
  const PAGE_SIZE = 25;
  let meta = {};
  let mini = null;
  let docsBySource = {};       // src -> array of records (loaded on demand)
  let allDocs = [];            // flat union of loaded shards
  let byId = new Map();
  let labelByKey = {};
  let page = 0;
  let lastResults = [];
  let totalLoaded = 0;
  let highlightMode = true;    // showing the landing-page recents until user acts

  const $ = (s) => document.querySelector(s);
  const results = $("#results");
  const pager = $("#pager");
  const qEl = $("#q");
  const srcSel = $("#source-filter");
  const dateSel = $("#date-filter");
  const sortSel = $("#sort-filter");
  const metaEl = $("#meta");
  const loadingBar = $("#loading-bar");
  const loadingFill = loadingBar.querySelector(".loading-bar-fill");
  const loadingLabel = loadingBar.querySelector(".loading-bar-label");

  // 1. Load meta + highlights in parallel.
  let highlights = [];
  try {
    [meta, highlights] = await Promise.all([
      fetch("index/meta.json").then(r => r.json()),
      fetch("index/highlights.json").then(r => r.json()),
    ]);
  } catch (e) {
    results.innerHTML = `<p>Couldn't load index. (${e.message})</p>`;
    return;
  }

  meta.sources.forEach(s => { labelByKey[s.key] = s.label; });

  // Source filter dropdown
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

  // Index highlights so they're searchable even before full shards load.
  for (const d of highlights) byId.set(d.id, d);
  mini.addAll(highlights);

  function showLoading(label) {
    loadingBar.hidden = false;
    loadingFill.style.right = "100%";
    loadingLabel.textContent = label;
  }
  function updateLoading(done, total, label) {
    loadingFill.style.right = `${100 * (1 - done / total)}%`;
    loadingLabel.textContent = label;
  }
  function hideLoading() {
    loadingBar.hidden = true;
  }

  async function loadShard(key) {
    if (docsBySource[key]) return docsBySource[key];
    const r = await fetch(`index/sources/${key}.json`);
    const docs = await r.json();
    docsBySource[key] = docs;
    // Replace any highlight stubs with full records
    for (const d of docs) {
      if (byId.has(d.id) && highlights.length) {
        // already indexed via highlights; don't re-add to mini
      } else {
        byId.set(d.id, d);
        mini.add(d);
      }
    }
    // Make sure all docs are in byId (even ones already indexed)
    for (const d of docs) byId.set(d.id, d);
    allDocs = allDocs.concat(docs);
    totalLoaded += docs.length;
    return docs;
  }

  function formatBytes(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${Math.round(n/1024)} KB`;
    return `${(n/1024/1024).toFixed(1)} MB`;
  }

  async function ensureLoaded(forFilter) {
    const needed = forFilter
      ? [forFilter]
      : meta.sources.map(s => s.key);
    const toLoad = needed.filter(k => !docsBySource[k]);
    if (toLoad.length === 0) return;

    const totalBytes = toLoad.reduce((sum, k) => {
      const m = meta.sources.find(s => s.key === k);
      return sum + (m?.shard_bytes || 0);
    }, 0);

    showLoading(`Loading ${toLoad.length} source${toLoad.length === 1 ? "" : "s"} (${formatBytes(totalBytes)})…`);
    let done = 0;
    await Promise.all(toLoad.map(async (k) => {
      await loadShard(k);
      done++;
      const m = meta.sources.find(s => s.key === k);
      updateLoading(done, toLoad.length, `Loaded ${labelByKey[k] || k} (${done} of ${toLoad.length})`);
    }));
    hideLoading();
  }

  // Initial state from URL
  const params = new URLSearchParams(location.search);
  qEl.value = params.get("q") || "";
  if (params.get("source")) srcSel.value = params.get("source");
  if (params.get("days")) dateSel.value = params.get("days");
  if (params.get("sort")) sortSel.value = params.get("sort");

  // Split a raw query into bare terms and quoted phrases.
  //   police "use of force" misconduct
  //   -> { bare: 'police misconduct', phrases: ['use of force'] }
  function parseQuery(raw) {
    const phrases = [];
    const bare = raw.replace(/"([^"]+)"/g, (_, p) => {
      const t = p.trim();
      if (t) phrases.push(t.toLowerCase());
      return " ";
    }).replace(/\s+/g, " ").trim();
    return { bare, phrases };
  }

  // Quoted-phrase filter: every phrase must appear, case-insensitively, in
  // the document's title/summary/full_text/agency/respondent/outcome.
  function matchesPhrases(d, phrases) {
    if (!phrases.length) return true;
    const hay = [
      d.title, d.summary, d.full_text, d.agency, d.respondent, d.outcome,
    ].join(" ").toLowerCase();
    return phrases.every(p => hay.includes(p));
  }

  function filterAndRank() {
    const raw = qEl.value.trim();
    const src = srcSel.value;
    const days = parseInt(dateSel.value || "0", 10);
    const sort = sortSel.value || "relevance";
    const { bare, phrases } = parseQuery(raw);

    let candidates;
    if (bare || phrases.length) {
      // If there are bare terms, run MiniSearch on them; otherwise (pure
      // phrase query) start from the full candidate pool.
      if (bare) {
        const hits = mini.search(bare);
        candidates = hits.map(h => ({...byId.get(h.id), _score: h.score})).filter(d => d.id);
      } else {
        candidates = (src ? (docsBySource[src] || []) : allDocs).map(d => ({...d, _score: 0}));
      }
      // Phrase filter
      if (phrases.length) {
        candidates = candidates.filter(d => matchesPhrases(d, phrases));
      }
    } else if (highlightMode && !src) {
      candidates = highlights.slice();
    } else {
      candidates = (src ? (docsBySource[src] || []) : allDocs).slice();
    }

    if (src) candidates = candidates.filter(d => d.source === src);
    if (days) {
      const cutoff = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
      candidates = candidates.filter(d => (d.decision_date || "") >= cutoff);
    }

    // Sort
    if (sort === "newest") {
      candidates.sort((a, b) => (b.decision_date || "").localeCompare(a.decision_date || ""));
    } else if (sort === "oldest") {
      candidates.sort((a, b) => (a.decision_date || "9999").localeCompare(b.decision_date || "9999"));
    } else if (sort === "source") {
      candidates.sort((a, b) => {
        const A = (labelByKey[a.source] || a.source || "").toLowerCase();
        const B = (labelByKey[b.source] || b.source || "").toLowerCase();
        if (A !== B) return A.localeCompare(B);
        return (b.decision_date || "").localeCompare(a.decision_date || "");
      });
    } else {
      // relevance: keep MiniSearch score order if we have one, else newest
      if (raw) {
        candidates.sort((a, b) => (b._score || 0) - (a._score || 0));
      } else {
        candidates.sort((a, b) => (b.decision_date || "").localeCompare(a.decision_date || ""));
      }
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

    // First user action breaks us out of highlight mode.
    if (q || src) highlightMode = false;

    const needSource = src && !docsBySource[src];
    const needAll = !src && q && totalLoaded < meta.total;
    if (needSource || needAll) {
      await ensureLoaded(src);
    }

    lastResults = filterAndRank();

    if (highlightMode && !q && !src) {
      metaEl.textContent = `Showing ${lastResults.length} most-recent records across all sources — type to search ${meta.total.toLocaleString()} or pick a source`;
    } else {
      metaEl.textContent = `${lastResults.length.toLocaleString()} of ${meta.total.toLocaleString()} records`;
    }

    $("#rss-link").href = src ? `feeds/${src}.xml` : "feeds/all.xml";
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (src) p.set("source", src);
    if (dateSel.value) p.set("days", dateSel.value);
    if (sortSel.value && sortSel.value !== "relevance") p.set("sort", sortSel.value);
    const qs = p.toString();
    history.replaceState(null, "", qs ? "?" + qs : location.pathname);
    renderPage();
  }

  let debounce;
  qEl.addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(update, 200); });
  srcSel.addEventListener("change", update);
  dateSel.addEventListener("change", update);
  sortSel.addEventListener("change", update);

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function highlight(text, q) {
    if (!q) return text;
    const { bare, phrases } = parseQuery(q);
    const tokens = [];
    for (const ph of phrases) tokens.push(escRe(ph));
    for (const t of bare.split(/\s+/)) {
      if (t.length > 1) tokens.push(escRe(t));
    }
    if (!tokens.length) return text;
    return text.replace(new RegExp(`(${tokens.join("|")})`, "gi"), "<mark>$1</mark>");
  }
  function escRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

  // Initial render: highlights, or jump straight to filtered results if URL has params.
  await update();
})();
