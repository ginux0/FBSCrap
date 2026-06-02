"""
HTML Intelligence Report generator.
Produces a self-contained HTML file with charts, TOP-N table, and recovery plan.
"""
from __future__ import annotations
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


class Reporter:

    def __init__(self, out_dir: Path | str):
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        posts:   list[dict],
        top_n:   int    = 30,
        query:   str    = "",
        filename: str   = "report.html",
    ) -> Path:
        out  = self.out / filename
        html = self._build_html(posts, top_n, query)
        out.write_text(html, encoding="utf-8")
        print(f"  [REPORT] HTML  → {out}")
        return out

    # ── Data helpers ──────────────────────────────────────────────────────────

    def _stats(self, posts: list[dict]) -> dict:
        total   = len(posts)
        labels  = [p.get("sentiment", {}).get("label", "NEUTRAL") for p in posts]
        neg     = labels.count("NEGATIVO")
        pos     = labels.count("POSITIVO")
        neu     = labels.count("NEUTRAL")
        by_src  = Counter(p.get("source", "?") for p in posts)
        eng_sum = sum(p.get("engagement_total", 0) for p in posts)
        top_eng = sorted(posts, key=lambda p: p.get("engagement_total", 0), reverse=True)[:3]
        return {
            "total":    total,
            "neg":      neg,
            "pos":      pos,
            "neu":      neu,
            "neg_pct":  round(neg / max(total, 1) * 100, 1),
            "pos_pct":  round(pos / max(total, 1) * 100, 1),
            "neu_pct":  round(neu / max(total, 1) * 100, 1),
            "by_src":   by_src.most_common(10),
            "eng_sum":  eng_sum,
            "top_eng":  top_eng,
        }

    def _word_cloud_data(self, posts: list[dict]) -> list[tuple[str, int]]:
        freq: Counter = Counter()
        for p in posts:
            triggers = p.get("sentiment", {}).get("top_triggers", [])
            freq.update(triggers)
        return freq.most_common(30)

    # ── HTML builder ──────────────────────────────────────────────────────────

    def _build_html(self, posts: list[dict], top_n: int, query: str) -> str:
        s    = self._stats(posts)
        top  = posts[:top_n]
        wc   = self._word_cloud_data(posts)
        now  = datetime.now().strftime("%Y-%m-%d %H:%M")

        src_labels = json.dumps([x[0] for x in s["by_src"]])
        src_values = json.dumps([x[1] for x in s["by_src"]])

        sentiment_labels = json.dumps(["NEGATIVO", "POSITIVO", "NEUTRAL"])
        sentiment_values = json.dumps([s["neg"], s["pos"], s["neu"]])

        rows_html = self._build_rows(top)
        wc_html   = self._build_word_cloud(wc)
        recovery  = self._recovery_plan(s)

        return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FBSCRAP Intelligence Report — {query or "Facebook"}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg:#0a0a0f; --card:#111118; --border:#1e1e2e; --accent:#00ff88;
    --red:#ff4466; --blue:#4488ff; --yellow:#ffcc00; --text:#c8c8d4;
    --text2:#7a7a99; --font:'Courier New',monospace;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:var(--font);font-size:13px;padding:20px}}
  h1{{color:var(--accent);font-size:22px;letter-spacing:2px;margin-bottom:4px}}
  h2{{color:var(--accent);font-size:14px;letter-spacing:1px;margin:24px 0 10px;text-transform:uppercase}}
  .meta{{color:var(--text2);font-size:11px;margin-bottom:20px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:24px}}
  .card{{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:14px;text-align:center}}
  .card .val{{font-size:28px;font-weight:bold;margin:6px 0}}
  .card .lbl{{color:var(--text2);font-size:11px;text-transform:uppercase;letter-spacing:1px}}
  .neg{{color:var(--red)}} .pos{{color:var(--accent)}} .neu{{color:var(--yellow)}}
  .charts{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px}}
  .chart-box{{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:16px}}
  canvas{{max-height:240px}}
  table{{width:100%;border-collapse:collapse;margin-bottom:24px;font-size:12px}}
  th{{background:#0d0d1a;color:var(--accent);padding:8px 6px;text-align:left;border-bottom:1px solid var(--border);font-size:11px;text-transform:uppercase;letter-spacing:1px}}
  td{{padding:7px 6px;border-bottom:1px solid var(--border);vertical-align:top}}
  tr:hover td{{background:#111122}}
  .badge{{display:inline-block;padding:2px 7px;border-radius:3px;font-size:10px;font-weight:bold}}
  .badge-neg{{background:#3d0a14;color:var(--red);border:1px solid var(--red)}}
  .badge-pos{{background:#0a2d1e;color:var(--accent);border:1px solid var(--accent)}}
  .badge-neu{{background:#2d2a00;color:var(--yellow);border:1px solid var(--yellow)}}
  a{{color:#5599ff;text-decoration:none;word-break:break-all}}
  a:hover{{text-decoration:underline}}
  .wc{{display:flex;flex-wrap:wrap;gap:8px;padding:16px;background:var(--card);border:1px solid var(--border);border-radius:6px;margin-bottom:24px}}
  .wc span{{color:var(--red);cursor:default}}
  .recovery{{background:var(--card);border:1px solid var(--accent);border-radius:6px;padding:16px;margin-bottom:24px}}
  .recovery h3{{color:var(--accent);font-size:13px;margin-bottom:10px}}
  .recovery ul{{list-style:none;padding:0}}
  .recovery li{{padding:4px 0;border-bottom:1px solid var(--border);color:var(--text)}}
  .recovery li::before{{content:"▶ ";color:var(--accent)}}
  .bar{{background:#1a1a2e;border-radius:3px;height:6px;margin-top:4px;overflow:hidden}}
  .bar-fill{{height:100%;background:var(--red);border-radius:3px}}
  .trunc{{max-width:380px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
  .num{{color:var(--yellow);font-weight:bold}}
  @media(max-width:700px){{.charts{{grid-template-columns:1fr}}}}
</style>
</head>
<body>

<h1>⚡ FBSCRAP INTELLIGENCE REPORT</h1>
<div class="meta">
  Query: <strong>{query or "multi-target"}</strong> &nbsp;|&nbsp;
  Generated: <strong>{now}</strong> &nbsp;|&nbsp;
  Posts analyzed: <strong>{s["total"]}</strong> &nbsp;|&nbsp;
  Total engagement: <strong>{s["eng_sum"]:,}</strong>
</div>

<div class="grid">
  <div class="card"><div class="val">{s["total"]}</div><div class="lbl">Posts Totales</div></div>
  <div class="card"><div class="val neg">{s["neg_pct"]}%</div><div class="lbl">Negativo</div></div>
  <div class="card"><div class="val pos">{s["pos_pct"]}%</div><div class="lbl">Positivo</div></div>
  <div class="card"><div class="val neu">{s["neu_pct"]}%</div><div class="lbl">Neutral</div></div>
  <div class="card"><div class="val">{s["eng_sum"]:,}</div><div class="lbl">Engagement Total</div></div>
</div>

<div class="charts">
  <div class="chart-box">
    <h2>Distribución de Sentimiento</h2>
    <canvas id="chartSentiment"></canvas>
  </div>
  <div class="chart-box">
    <h2>Posts por Fuente (Top 10)</h2>
    <canvas id="chartSource"></canvas>
  </div>
</div>

<h2>🔴 Términos de Ataque más Frecuentes</h2>
<div class="wc">{wc_html}</div>

<h2>⚡ TOP {top_n} Posts por Negatividad + Engagement</h2>
<table>
<thead>
<tr>
  <th>#</th><th>Sentimiento</th><th>Fuente</th><th>Engagement</th>
  <th>Texto (preview)</th><th>Fecha</th><th>Liga Facebook</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>

<h2>🛡️ Plan de Recuperación de Imagen</h2>
<div class="recovery">
{recovery}
</div>

<script>
const chartColors = {{
  neg: '#ff4466', pos: '#00ff88', neu: '#ffcc00',
  blue: '#4488ff', purple: '#aa44ff', teal: '#00ccaa'
}};

new Chart(document.getElementById('chartSentiment'), {{
  type: 'doughnut',
  data: {{
    labels: {sentiment_labels},
    datasets: [{{
      data: {sentiment_values},
      backgroundColor: [chartColors.neg, chartColors.pos, chartColors.neu],
      borderColor: '#0a0a0f', borderWidth: 2
    }}]
  }},
  options: {{
    plugins: {{
      legend: {{ labels: {{ color: '#c8c8d4', font: {{ family: 'Courier New' }} }} }}
    }}
  }}
}});

new Chart(document.getElementById('chartSource'), {{
  type: 'bar',
  data: {{
    labels: {src_labels},
    datasets: [{{
      label: 'Posts',
      data: {src_values},
      backgroundColor: '#4488ff88',
      borderColor: '#4488ff',
      borderWidth: 1
    }}]
  }},
  options: {{
    indexAxis: 'y',
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#7a7a99' }}, grid: {{ color: '#1e1e2e' }} }},
      y: {{ ticks: {{ color: '#c8c8d4', font: {{ size: 10 }} }}, grid: {{ color: '#1e1e2e' }} }}
    }}
  }}
}});
</script>
</body>
</html>"""

    def _build_rows(self, posts: list[dict]) -> str:
        rows = []
        for i, p in enumerate(posts, 1):
            sent    = p.get("sentiment", {})
            label   = sent.get("label", "NEUTRAL")
            neg_s   = sent.get("negative_score", 0)
            badge_cls = {"NEGATIVO": "badge-neg", "POSITIVO": "badge-pos"}.get(label, "badge-neu")
            text    = (p.get("text") or "")[:120].replace("<", "&lt;").replace(">", "&gt;")
            ts      = (p.get("timestamp") or "")[:10]
            url     = p.get("url", "#")
            source  = (p.get("source") or "?")[:30]
            eng     = p.get("engagement_total", 0)
            bar_w   = min(int(neg_s * 100), 100)
            rows.append(
                f'<tr>'
                f'<td class="num">{i}</td>'
                f'<td>'
                f'  <span class="badge {badge_cls}">{label}</span>'
                f'  <div class="bar"><div class="bar-fill" style="width:{bar_w}%"></div></div>'
                f'</td>'
                f'<td>{source}</td>'
                f'<td class="num">{eng:,}</td>'
                f'<td class="trunc" title="{text}">{text}</td>'
                f'<td>{ts}</td>'
                f'<td><a href="{url}" target="_blank">→ Abrir</a></td>'
                f'</tr>'
            )
        return "\n".join(rows)

    def _build_word_cloud(self, wc: list[tuple[str, int]]) -> str:
        if not wc:
            return "<span style='color:#666'>Sin datos suficientes</span>"
        max_count = wc[0][1] if wc else 1
        parts = []
        for word, count in wc:
            size = 12 + int((count / max_count) * 24)
            parts.append(f'<span style="font-size:{size}px" title="{count} menciones">{word}</span>')
        return " ".join(parts)

    def _recovery_plan(self, s: dict) -> str:
        pct  = s["neg_pct"]
        need = max(0, 80 - (100 - pct))
        actions = [
            f"Current negativity: <span class='neg'>{pct}%</span> → Target: reduce to <span class='pos'>20%</span> (80% positive)",
            f"Negative posts to address: <span class='num'>{s['neg']}</span> of {s['total']} total",
            "PHASE 1 — Rebuttal: infographics 'What was said vs. What actually happened' (week 1)",
            "PHASE 2 — Reframing: chronological timeline of documented context (week 1-2)",
            "PHASE 3 — Organic containment: supporter network comments on TOP 30 identified posts (ongoing)",
            "PHASE 4 — Positive construction: real achievements + citizen testimonials (week 2-3)",
            "PHASE 5 — Amplification: strengthen the most effective counter-narrative as the central axis",
            "PHASE 6 — 24/7 monitoring: re-run fbscrap daily to measure recovery delta",
        ]
        li = "".join(f"<li>{a}</li>" for a in actions)
        return f"<h3>RUTA AL 80% POSITIVO</h3><ul>{li}</ul>"
