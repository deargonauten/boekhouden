// Review screen: shows the original PDF on the left (pdf.js, text layer) and
// highlights the passage a line was read from when the user focuses that line.
import * as pdfjsLib from "/static/vendor/pdfjs/pdf.min.mjs";

const view = document.getElementById("pdf-view");
const status = document.getElementById("source-status");
const rows = document.getElementById("review-line-rows");
const textLayers = []; // one div.textLayer per rendered page

const say = (text) => { if (status) status.textContent = text; };
const normalize = (s) => s.toLowerCase().replace(/\s+/g, " ").trim();

async function renderPdf() {
  pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs/pdf.worker.min.mjs";
  const pdf = await pdfjsLib.getDocument(view.dataset.src).promise;
  const width = view.clientWidth - 2;
  for (let n = 1; n <= pdf.numPages; n++) {
    const page = await pdf.getPage(n);
    const base = page.getViewport({ scale: 1 });
    const viewport = page.getViewport({ scale: width / base.width });
    const wrap = document.createElement("div");
    wrap.className = "pdf-page";
    wrap.style.width = `${viewport.width}px`;
    wrap.style.height = `${viewport.height}px`;
    wrap.style.setProperty("--scale-factor", viewport.scale);
    const ratio = window.devicePixelRatio || 1;
    const canvas = document.createElement("canvas");
    canvas.width = Math.floor(viewport.width * ratio);
    canvas.height = Math.floor(viewport.height * ratio);
    canvas.style.width = `${viewport.width}px`;
    canvas.style.height = `${viewport.height}px`;
    const layer = document.createElement("div");
    layer.className = "textLayer";
    wrap.append(canvas, layer);
    view.append(wrap);
    await page.render({
      canvasContext: canvas.getContext("2d"),
      viewport,
      transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0],
    }).promise;
    await new pdfjsLib.TextLayer({
      textContentSource: page.streamTextContent(),
      container: layer,
      viewport,
    }).render();
    textLayers.push(layer);
  }
}

// Haystack = span texts joined by spaces, normalized, with a map back to span indexes.
function index(layer) {
  const spans = [...layer.querySelectorAll("span[role=presentation], span:not([class])")];
  let text = "";
  const owner = [];
  spans.forEach((span, i) => {
    const t = span.textContent.toLowerCase().replace(/\s+/g, " ");
    for (const ch of t) { text += ch; owner.push(i); }
    text += " "; owner.push(-1);
  });
  return { spans, text, owner };
}

function find(needle) {
  // Full passage first, then shorter prefixes, so a slightly off excerpt still lands near the line.
  const words = needle.split(" ");
  for (let len = words.length; len >= 2 || (len === 1 && words[0].length >= 4); len--) {
    const part = words.slice(0, len).join(" ");
    for (const layer of textLayers) {
      const idx = index(layer);
      const at = idx.text.indexOf(part);
      if (at >= 0) {
        const hit = new Set(idx.owner.slice(at, at + part.length).filter((i) => i >= 0));
        return [...hit].map((i) => idx.spans[i]);
      }
    }
  }
  return [];
}

function highlight(source) {
  document.querySelectorAll(".src-hit").forEach((el) => el.classList.remove("src-hit"));
  if (!view) return say("Van dit bestand kan ik niet aanwijzen waar de regel staat.");
  const needle = normalize(source || "");
  if (!needle) return say("Voor deze regel is geen plek in het origineel bekend.");
  const hits = find(needle);
  if (!hits.length) return say("Deze regel staat niet als tekst in het origineel. Zoek hem zelf op het document.");
  hits.forEach((el) => el.classList.add("src-hit"));
  hits[0].scrollIntoView({ block: "center", behavior: "smooth" });
  say("De gemarkeerde tekst links is waar deze regel vandaan komt.");
}

if (rows) {
  let active = null;
  const onRow = (event) => {
    const row = event.target.closest("tr.line-row");
    if (!row || row === active) return;
    active = row;
    rows.querySelectorAll("tr.line-row.is-active").forEach((r) => r.classList.remove("is-active"));
    row.classList.add("is-active");
    highlight(row.querySelector("input[name=line_source_text]")?.value);
  };
  rows.addEventListener("focusin", onRow);
  rows.addEventListener("click", onRow);
}

if (view) {
  renderPdf().catch(() => {
    view.innerHTML = '<iframe class="file-view" src="' + view.dataset.src + '" title="Origineel bestand"></iframe>';
    say("Het origineel kan hier niet gemarkeerd worden; je ziet het gewone bestand.");
  });
}
