#!/usr/bin/env python3
"""
Genera la página de estado del pipeline "Buenas Noticias" (estado/index.html)
a partir de la bitácora data/pipeline_log.json.

Cada corrida de los 4 triggers (Fase A, Fase B, Vigía Fase A, Vigía Fase B)
agrega un registro a la bitácora y vuelve a correr este script para
regenerar la página, igual que build_site.py regenera el sitio a partir de
site_data.json. No modifica site_data.json ni ningún HTML del sitio de
noticias -- solo lee/escribe data/pipeline_log.json y escribe estado/index.html.

Uso:
    python3 scripts/build_status_page.py --log data/pipeline_log.json --site-dir .

Registro esperado en la bitácora (un objeto por corrida):
{
  "timestamp_utc": "2026-09-11T14:20:41Z",   # ISO 8601 UTC, momento en que terminó la corrida
  "trigger": "fase_a" | "fase_b" | "vigia_fase_a" | "vigia_fase_b",
  "status": "ok" | "warning" | "error",
  "summary": "texto breve de una línea",
  "link": "https://... (opcional, ej. un commit o una corrida de GitHub Actions)"
}
"""
import argparse
import json
import os
from html import escape

MAX_ENTRIES_SHOWN = 60

TRIGGER_LABELS = {
    "fase_a": "Fase A — búsqueda + borrador",
    "fase_b": "Fase B — aprobación + publicación",
    "vigia_fase_a": "Vigía Fase A",
    "vigia_fase_b": "Vigía Fase B",
}

STATUS_META = {
    "ok": {"label": "OK", "color": "#3f4a37", "bg": "#eef1ea"},
    "warning": {"label": "Aviso", "color": "#8a6d1d", "bg": "#faf1d9"},
    "error": {"label": "Error", "color": "#9b3b32", "bg": "#f8e6e3"},
}

SHARED_CSS = """
  :root {
    color-scheme: light;
    --bg: #faf8f4; --bg-alt: #f2efe7; --ink: #201f1c; --ink-soft: #6b675e;
    --line: #e5e0d5; --accent: #6b7a5e; --accent-deep: #3f4a37; --card-bg: #ffffff;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; background: var(--bg); color: var(--ink); font-family: 'Inter', -apple-system, sans-serif; line-height: 1.6; font-size: 16px; -webkit-font-smoothing: antialiased; }
  a { color: inherit; text-decoration: none; }
  header.site-header { background: var(--bg); border-bottom: 1px solid var(--line); }
  .header-inner { max-width: 1000px; margin: 0 auto; padding: 22px 32px; display: flex; align-items: center; justify-content: space-between; gap: 20px; flex-wrap: wrap; }
  .logo { font-family: 'Fraunces', Georgia, serif; font-weight: 500; font-size: 1.4rem; color: var(--ink); letter-spacing: -0.01em; }
  .back-link { font-size: 0.82rem; font-weight: 600; color: var(--ink-soft); text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid transparent; }
  .back-link:hover { color: var(--ink); border-color: var(--accent); }
  main { max-width: 1000px; margin: 0 auto; padding: 40px 32px 80px; }
  h1 { font-family: 'Fraunces', Georgia, serif; font-weight: 500; font-size: 2rem; margin: 0 0 10px; }
  p.sub { color: var(--ink-soft); font-size: 0.95rem; margin: 0 0 40px; max-width: 640px; }
  .run { display: grid; grid-template-columns: 190px 210px 90px 1fr; gap: 18px; align-items: start; padding: 18px 0; border-bottom: 1px solid var(--line); }
  .run .ts { color: var(--ink-soft); font-size: 0.85rem; white-space: nowrap; }
  .run .trig { font-weight: 600; font-size: 0.92rem; }
  .run .status-pill { display: inline-block; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; padding: 4px 11px; border-radius: 999px; width: fit-content; }
  .run .summary { font-size: 0.92rem; color: var(--ink); }
  .run .summary a { text-decoration: underline; text-underline-offset: 2px; font-weight: 600; }
  .empty { color: var(--ink-soft); padding: 40px 0; }
  footer { border-top: 1px solid var(--line); padding: 40px 32px; text-align: center; color: var(--ink-soft); font-size: 0.8rem; }
  @media (max-width: 720px) {
    .run { grid-template-columns: 1fr; gap: 6px; padding: 20px 0; }
  }
"""

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>Estado del pipeline -- Buenas Noticias</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;0,9..144,600;1,9..144,400;1,9..144,500&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{css}</style>
</head>
<body>
<header class="site-header">
  <div class="header-inner">
    <span class="logo">Estado del pipeline</span>
    <a href="../" class="back-link">&larr; Volver al inicio</a>
  </div>
</header>
<main>
  <h1>Buenas Noticias -- estado del pipeline</h1>
  <p class="sub">Historial de las corridas de Fase A, Fase B y sus dos vigías. Página de uso interno (no aparece en el menú del sitio ni se indexa en buscadores). Generada automáticamente en cada corrida -- última actualización: {generated_at} UTC.</p>
  {rows}
</main>
<footer>Buenas Noticias -- panel interno de monitoreo del pipeline editorial.</footer>
</body>
</html>
"""


def render_row(entry):
    trigger_key = entry.get("trigger", "")
    trigger_label = TRIGGER_LABELS.get(trigger_key, escape(trigger_key or "?"))
    status_key = entry.get("status", "ok")
    meta = STATUS_META.get(status_key, STATUS_META["ok"])
    ts = escape(entry.get("timestamp_utc", "?"))
    summary = escape(entry.get("summary", ""))
    link = entry.get("link")
    if link:
        summary += f' <a href="{escape(link)}" target="_blank" rel="noopener">(ver detalle)</a>'
    return f"""
  <div class="run">
    <div class="ts">{ts}</div>
    <div class="trig">{trigger_label}</div>
    <div><span class="status-pill" style="color:{meta['color']}; background:{meta['bg']}">{meta['label']}</span></div>
    <div class="summary">{summary}</div>
  </div>"""


def build_status_page(log_path, site_dir):
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            entries = json.load(f)
    else:
        entries = []

    # más reciente primero
    entries_sorted = sorted(entries, key=lambda e: e.get("timestamp_utc", ""), reverse=True)
    shown = entries_sorted[:MAX_ENTRIES_SHOWN]

    if shown:
        rows_html = "\n".join(render_row(e) for e in shown)
    else:
        rows_html = '<p class="empty">Todavía no hay registros en la bitácora.</p>'

    generated_at = entries_sorted[0]["timestamp_utc"] if entries_sorted else "-"
    page = PAGE_TEMPLATE.format(css=SHARED_CSS, rows=rows_html, generated_at=generated_at)

    out_dir = os.path.join(site_dir, "estado")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)

    print(f"Bitácora: {len(entries)} registros totales, mostrando los últimos {len(shown)}.")
    print(f"Página escrita en: {out_path}")
    return out_path


def append_entry(log_path, entry, max_keep=200):
    """Utilidad opcional: agrega un registro nuevo a la bitácora y la trunca
    a los últimos `max_keep` registros (por si algún trigger prefiere usar
    esta función en vez de armar el JSON a mano)."""
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            entries = json.load(f)
    else:
        entries = []
    entries.append(entry)
    entries_sorted = sorted(entries, key=lambda e: e.get("timestamp_utc", ""))
    entries_trimmed = entries_sorted[-max_keep:]
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(entries_trimmed, f, ensure_ascii=False, indent=2)
    return entries_trimmed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", default="data/pipeline_log.json")
    parser.add_argument("--site-dir", default=".")
    args = parser.parse_args()
    build_status_page(args.log, args.site_dir)


if __name__ == "__main__":
    main()
