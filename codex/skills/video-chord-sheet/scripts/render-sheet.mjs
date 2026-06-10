import fs from "node:fs";
import path from "node:path";

const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) {
  console.error("Usage: node render-sheet.mjs spec.json output.html");
  process.exit(1);
}

const spec = JSON.parse(fs.readFileSync(specPath, "utf8").replace(/^\uFEFF/, ""));
const esc = value => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;");

const diagramHtml = (spec.diagrams || []).map(d =>
  `<div class="diagram"><img src="${esc(d.src)}" alt="${esc(d.name)}"></div>`
).join("\n");

const introRows = spec.intro?.rows || [];
const introHtml = introRows.length ? `
  <section class="intro">
    <div class="section">${esc(spec.intro?.label || "Intro")}</div>
    ${introRows.map(row => `
      <div class="intro-row">
        <span class="bar-label">${esc(row.label)}</span>
        ${(row.chords || []).map(ch => `<span class="intro-chord">${esc(ch)}</span>`).join("")}
      </div>`).join("\n")}
  </section>` : "";

const sectionsHtml = (spec.sections || []).map(section => `
  <div class="section">${esc(section.title)}</div>
  ${(section.lines || []).map(line => `
    <p class="lyric-line">
      ${line.map(p => `<span class="phrase"><span class="ch">${esc(p.chord)}</span><span class="txt">${esc(p.text)}</span></span>`).join("")}
    </p>`).join("\n")}
`).join("\n");

const html = `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${esc(spec.title)} - 和弦谱</title>
  <style>
    :root { --paper:#fffdf9; --ink:#20242a; --muted:#71717a; --chord:#e23b3b; --line:#333; }
    * { box-sizing: border-box; }
    body { margin:0; background:#e8e8e8; color:var(--ink); font-family:"Microsoft YaHei","PingFang SC",Arial,sans-serif; }
    main { width:960px; margin:0 auto; padding:32px 46px 56px; background:var(--paper); }
    h1 { margin:0 0 4px; font-size:30px; letter-spacing:0; }
    .meta { margin-bottom:24px; color:var(--muted); font-size:14px; }
    .diagram-grid { display:grid; grid-template-columns:repeat(7,1fr); gap:18px 14px; padding-bottom:24px; margin-bottom:26px; border-bottom:1px solid #e5e7eb; }
    .diagram { display:flex; justify-content:center; align-items:flex-start; min-height:122px; }
    .diagram img { width:100px; max-height:122px; object-fit:contain; mix-blend-mode:multiply; }
    .section { margin:22px 0 8px; color:var(--muted); font-size:15px; font-weight:700; }
    .intro { margin:4px 0 26px; font-size:22px; line-height:2.15; }
    .intro-row { display:grid; grid-template-columns:70px repeat(4,120px); column-gap:20px; align-items:center; }
    .bar-label { color:var(--muted); font-size:15px; }
    .intro-chord { color:var(--chord); text-align:center; }
    .song { font-size:25px; line-height:2.55; }
    .lyric-line { margin:14px 0; white-space:nowrap; }
    .phrase { position:relative; display:inline-block; padding-top:23px; margin-right:8px; vertical-align:baseline; }
    .ch { position:absolute; top:-1px; left:50%; transform:translateX(-50%); color:var(--chord); font-size:22px; line-height:1; white-space:nowrap; }
    .txt { display:inline-block; border-bottom:1px solid var(--line); line-height:1.12; }
    @media print {
      body { background:#fff; }
      main { width:auto; padding:16mm 14mm; }
      .diagram-grid { gap:12px 8px; }
      .diagram img { width:88px; }
      .song { font-size:22px; }
      .ch { font-size:19px; }
    }
  </style>
</head>
<body>
<main>
  <h1>${esc(spec.title)}</h1>
  <div class="meta">${esc(spec.meta)}</div>
  <section class="diagram-grid">${diagramHtml}</section>
  ${introHtml}
  <section class="song">${sectionsHtml}</section>
</main>
</body>
</html>`;

fs.mkdirSync(path.dirname(path.resolve(outPath)), { recursive: true });
fs.writeFileSync(outPath, html, "utf8");
console.log(outPath);
