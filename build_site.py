#!/usr/bin/env python3
"""
Fase 4 del pipeline "Buenas Noticias" -- construye el sitio estático
MULTI-PÁGINA a partir de las notas reescritas (fase 3) y mantiene el
archivo histórico del portal.

Uso:
    python3 build_site.py --reescritos reescritos.json --site-dir ./site

Qué genera dentro de <site-dir>/ (sigue el sitemap del documento de
propuesta de estructura, sección 1 y 2):
  - index.html                      Home: destacadas + un bloque por categoría
  - <categoria>/index.html          Una página por categoría, feed completo
  - <categoria>/<slug-de-la-nota>/index.html   Una página permalink por nota
  - data/site_data.json             Archivo histórico completo (fuente de verdad)
  - data/published_urls.json        Solo las URLs, para que la fase 1 no repita historias

Qué hace, paso a paso:
  1. Lee data/site_data.json (el archivo acumulado de todo lo publicado
     hasta ahora) si existe; si es la primera corrida, empieza de cero.
  2. Le agrega las notas nuevas de reescritos.json, evitando duplicados
     por URL, y les asigna un "slug" (parte de la URL) la primera vez que
     se agregan -- ese slug ya NUNCA cambia para esa nota, para que su
     permalink sea de verdad permanente.
  3. Descarta del ARCHIVO DE DATOS las notas más viejas que RETENTION_DAYS,
     para que el Home y las páginas de categoría no crezcan sin límite.
     Importante: esto solo las saca de los listados -- si esa nota ya
     tenía una página de permalink generada en una corrida anterior, ese
     archivo HTML no se borra (este script nunca borra archivos), así que
     el link que alguien haya compartido sigue funcionando. Es el mismo
     comportamiento de un blog: la nota "envejece" y sale de portada, pero
     su URL propia no muere.
  4. Regenera Home, todas las páginas de categoría, y todas las páginas de
     nota individual de lo que quedó vigente después de la poda.
  5. Actualiza published_urls.json para que la fase 1 (búsqueda) sepa qué
     ya se publicó y no lo repita.

Este script solo RENDERIZA -- no busca fotos (eso lo hace attach_photos.py
en GitHub Actions, ver ese script) ni decide qué es una buena noticia (eso
ya se decidió en las fases 2 y 3). Si una nota no tiene "image_url"
todavía, se muestra con un respaldo ilustrado por categoría en vez de un
hueco vacío o una imagen rota.
"""

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

RETENTION_DAYS = 14

# Cuántas notas entran en el bloque "Destacadas de hoy" del Home, y cómo
# se eligen: por ahora, simplemente las más recientes de todo el sitio sin
# importar categoría. Este es un criterio PROVISIONAL -- quedó pendiente
# que el usuario defina el criterio real (ver documento de propuesta de
# estructura, sección 7, "Próximos pasos"). Cambiar esto es tan fácil como
# editar la función choose_featured() más abajo.
FEATURED_COUNT = 3

CATEGORY_ORDER = ["Deportes", "Economía", "Ciencia y Salud", "Medio Ambiente", "Sociedad", "Tecnología", "Cultura", "IA", "Otros"]

# Slugs fijos (no autogenerados) para que la URL de cada categoría sea
# predecible y coincida exactamente con el documento de propuesta de
# estructura, sección 3.
CATEGORY_SLUGS = {
    "Deportes": "deportes",
    "Economía": "economia",
    "Ciencia y Salud": "ciencia-y-salud",
    "Medio Ambiente": "medio-ambiente",
    "Sociedad": "sociedad",
    "Tecnología": "tecnologia",
    "Cultura": "cultura",
    "IA": "ia",
    "Otros": "otros",
}
CATEGORY_COLORS = {
    "Deportes": "#1d6f42",
    "Economía": "#0f5fa6",
    "Ciencia y Salud": "#7a3fa0",
    "Medio Ambiente": "#2e8b57",
    "Sociedad": "#c26b1f",
    "Tecnología": "#1f6f78",
    "Cultura": "#9c3b5e",
    "IA": "#5b4fa0",
    "Otros": "#555555",
}
# Emoji de respaldo para cuando una nota no tiene foto real todavía (ver
# attach_photos.py -- ese script, que corre en GitHub Actions y no aquí,
# es el que rellena image_url llamando a la API de Pexels con el header
# Authorization correcto; este script solo sabe RENDERIZAR lo que ya
# exista, nunca llama a la API él mismo).
CATEGORY_EMOJI = {
    "Deportes": "🏆",
    "Economía": "📈",
    "Ciencia y Salud": "🔬",
    "Medio Ambiente": "🌱",
    "Sociedad": "🤝",
    "Tecnología": "💻",
    "Cultura": "🎨",
    "IA": "✨",
    "Otros": "📰",
}


# ---------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------

def load_json(path, default):
    p = Path(path)
    if not p.exists():
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def slugify(text, max_len=70):
    """Convierte un titular en la parte de URL de su permalink.
    'Celeste Espino atajó el penal decisivo' -> 'celeste-espino-atajo-el-penal-decisivo'
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    text = re.sub(r"-{2,}", "-", text)
    text = text[:max_len].rstrip("-")
    return text or "nota"


def unique_slug(base, used_slugs):
    """Evita choques cuando dos titulares distintos generan el mismo slug
    (ej. dos notas tituladas casi igual en días distintos)."""
    slug = base
    n = 2
    while slug in used_slugs:
        slug = f"{base}-{n}"
        n += 1
    used_slugs.add(slug)
    return slug


def category_slug(cat):
    return CATEGORY_SLUGS.get(cat, slugify(cat))


# ---------------------------------------------------------------------
# Datos: fusionar lo nuevo, asignar slugs, podar lo viejo
# ---------------------------------------------------------------------

def merge_articles(existing, new_articles):
    by_url = {a["url"]: a for a in existing}
    used_slugs = {a["slug"] for a in existing if a.get("slug")}
    added, skipped = 0, 0
    for a in new_articles:
        if a["url"] in by_url:
            skipped += 1
            continue
        a = dict(a)
        a.setdefault("date_added", datetime.now().strftime("%Y-%m-%d"))
        if not a.get("slug"):
            base = slugify(a["title"])
            a["slug"] = unique_slug(base, used_slugs)
        by_url[a["url"]] = a
        added += 1
    return list(by_url.values()), added, skipped


def prune_old(articles, retention_days=RETENTION_DAYS):
    cutoff = datetime.now() - timedelta(days=retention_days)
    kept = []
    for a in articles:
        try:
            d = datetime.strptime(a.get("published_date", a.get("date_added", "1970-01-01")), "%Y-%m-%d")
        except ValueError:
            d = datetime.now()  # si la fecha viene mal formada, no la tires por eso
        if d >= cutoff:
            kept.append(a)
    return kept


def choose_featured(articles, count=FEATURED_COUNT):
    ordered = sorted(articles, key=lambda a: a.get("published_date", ""), reverse=True)
    return ordered[:count]


# ---------------------------------------------------------------------
# CSS compartido por las tres plantillas (Home, categoría, nota)
# ---------------------------------------------------------------------

def shared_css():
    return """
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    margin: 0; background: #fafaf7; color: #1a1a1a; line-height: 1.5;
  }
  a { color: inherit; }
  header.site-header {
    background: linear-gradient(135deg, #f4b400, #f47b20);
    color: white; padding: 28px 24px; text-align: center;
  }
  header.site-header .logo { font-size: 1.5rem; font-weight: 700; text-decoration: none; color: white; }
  header.site-header .tagline { margin: 6px 0 0; opacity: 0.95; font-size: 0.95rem; }
  nav.site-nav {
    display: flex; flex-wrap: wrap; justify-content: center; gap: 4px 14px;
    max-width: 1000px; margin: 16px auto 0; font-size: 0.85rem;
  }
  nav.site-nav a { text-decoration: none; color: white; opacity: 0.9; font-weight: 600; padding: 4px 2px; border-bottom: 2px solid transparent; }
  nav.site-nav a:hover, nav.site-nav a.active { opacity: 1; border-color: white; }
  .breadcrumb { max-width: 960px; margin: 18px auto 0; padding: 0 24px; font-size: 0.85rem; color: #888; }
  .breadcrumb a { text-decoration: none; color: #b5560d; }
  .breadcrumb a:hover { text-decoration: underline; }
  .stats { max-width: 900px; margin: 16px auto 0; background: white; border-radius: 12px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.08); padding: 16px 24px; text-align: center;
    font-size: 0.95rem; color: #444; }
  main { max-width: 960px; margin: 0 auto; padding: 24px 24px 80px; }
  h1.page-title { font-size: 1.9rem; margin: 8px 0 6px; display: flex; align-items: center; gap: 10px; }
  p.page-desc { color: #666; margin: 0 0 28px; font-size: 0.98rem; }
  .category { margin-bottom: 48px; }
  .category-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
  .category h2, .category-head h2 {
    display: flex; align-items: center; gap: 10px; font-size: 1.4rem; margin: 0;
    border-left: 6px solid; padding-left: 12px;
  }
  .category h2 span.dot, .category-head h2 span.dot { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }
  .ver-todas { font-size: 0.85rem; font-weight: 700; text-decoration: none; color: #b5560d; white-space: nowrap; }
  .ver-todas:hover { text-decoration: underline; }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 18px; }
  .card {
    background: white; border-radius: 10px; overflow: hidden;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06); display: flex; flex-direction: column;
  }
  .card-photo { position: relative; aspect-ratio: 16/10; background: #eee; overflow: hidden; }
  .card-photo img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .card-photo.fallback { display: flex; align-items: center; justify-content: center; }
  .card-photo.fallback .emoji { font-size: 2.4rem; filter: drop-shadow(0 2px 6px rgba(0,0,0,0.15)); }
  .photo-credit { position: absolute; bottom: 6px; right: 8px; font-size: 0.62rem; color: rgba(255,255,255,0.9);
    background: rgba(0,0,0,0.4); padding: 2px 7px; border-radius: 999px; }
  .card-body { padding: 20px; display: flex; flex-direction: column; flex-grow: 1; }
  .card h3, .card h3 a { margin: 0 0 10px; font-size: 1.05rem; line-height: 1.35; text-decoration: none; color: #1a1a1a; }
  .card h3 a:hover { text-decoration: underline; }
  .card .summary { font-size: 0.92rem; color: #333; flex-grow: 1; margin: 0 0 14px; }
  .meta { display: flex; flex-direction: column; gap: 6px; font-size: 0.8rem; color: #777; }
  .readmore { color: #b5560d; font-weight: 600; text-decoration: none; }
  .readmore:hover { text-decoration: underline; }
  /* --- página de nota individual (permalink) --- */
  .note-photo { aspect-ratio: 16/9; border-radius: 12px; overflow: hidden; margin-bottom: 24px; background: #eee; position: relative; }
  .note-photo img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .note-photo.fallback { display: flex; align-items: center; justify-content: center; }
  .note-photo.fallback .emoji { font-size: 4rem; }
  .note-cat-badge { display: inline-block; font-size: 0.75rem; font-weight: 700; color: white; padding: 4px 12px; border-radius: 999px; margin-bottom: 14px; }
  .note-summary { font-size: 1.08rem; line-height: 1.7; color: #222; margin: 0 0 24px; }
  .note-meta { font-size: 0.88rem; color: #777; margin-bottom: 28px; }
  .cta-source {
    display: inline-block; background: #b5560d; color: white; text-decoration: none;
    font-weight: 700; padding: 14px 26px; border-radius: 10px; font-size: 1rem; margin-bottom: 44px;
  }
  .cta-source:hover { background: #96470a; }
  .related-head { font-size: 1.1rem; margin: 0 0 16px; border-top: 1px solid #eee; padding-top: 28px; }
  footer.site-footer { text-align: center; padding: 32px 24px; color: #888; font-size: 0.85rem; border-top: 1px solid #eee; }
"""


def site_nav_html(base_prefix, active_category=None):
    links = []
    for cat in CATEGORY_ORDER:
        if cat == "Otros":
            continue
        slug = category_slug(cat)
        cls = ' class="active"' if cat == active_category else ""
        links.append(f'<a href="{base_prefix}{slug}/"{cls}>{cat}</a>')
    return f'<nav class="site-nav">{"".join(links)}</nav>'


def page_shell(*, title, base_prefix, body_html, active_category=None, breadcrumb_html=""):
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} · Buenas Noticias</title>
<style>{shared_css()}</style>
</head>
<body>
<header class="site-header">
  <a class="logo" href="{base_prefix}">🌤️ Buenas Noticias</a>
  <p class="tagline">Solo noticias positivas de América, todos los días</p>
  {site_nav_html(base_prefix, active_category)}
</header>
{breadcrumb_html}
<main>
{body_html}
</main>
<footer class="site-footer">
  Cada resumen es una redacción original a partir de la nota fuente; el titular y el enlace remiten siempre al medio que hizo el reportaje.
</footer>
</body>
</html>"""


# ---------------------------------------------------------------------
# Tarjeta reutilizable (Home y páginas de categoría)
# ---------------------------------------------------------------------

def card_html(a, base_prefix, big=False):
    cat = a.get("category", "Otros")
    color = CATEGORY_COLORS.get(cat, "#555")
    emoji = CATEGORY_EMOJI.get(cat, "📰")
    note_url = f"{base_prefix}{category_slug(cat)}/{a['slug']}/"

    image_url = a.get("image_url")
    if image_url:
        photographer = a.get("image_photographer", "Pexels")
        photo_html = f"""
          <div class="card-photo">
            <img src="{image_url}" alt="" loading="lazy">
            <span class="photo-credit">Foto: {photographer} / Pexels</span>
          </div>"""
    else:
        photo_html = f"""
          <div class="card-photo fallback" style="background:{color}">
            <span class="emoji">{emoji}</span>
          </div>"""

    return f"""
        <article class="card">{photo_html}
          <div class="card-body">
            <h3><a href="{note_url}">{a['title']}</a></h3>
            <p class="summary">{a['summary']}</p>
            <div class="meta">
              <span class="source">Fuente: {a['source']} · {a['published_date']}</span>
              <a class="readmore" href="{note_url}">Leer más &rarr;</a>
            </div>
          </div>
        </article>"""


# ---------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------

def build_home_html(articles, today_str):
    base_prefix = ""
    by_category = defaultdict(list)
    for a in articles:
        by_category[a.get("category", "Otros")].append(a)
    for cat in by_category:
        by_category[cat].sort(key=lambda a: a.get("published_date", ""), reverse=True)

    featured = choose_featured(articles)
    featured_urls = {a["url"] for a in featured}

    sections = []
    if featured:
        cards = "".join(card_html(a, base_prefix) for a in featured)
        sections.append(f"""
      <section class="category">
        <div class="category-head"><h2 style="border-color:#f47b20"><span class="dot" style="background:#f47b20"></span>Destacadas de hoy</h2></div>
        <div class="cards">{cards}</div>
      </section>""")

    for cat in CATEGORY_ORDER:
        arts = by_category.get(cat)
        if not arts:
            continue
        color = CATEGORY_COLORS.get(cat, "#555")
        recent = [a for a in arts if a["url"] not in featured_urls][:6]
        if not recent:
            continue
        cards = "".join(card_html(a, base_prefix) for a in recent)
        sections.append(f"""
      <section class="category">
        <div class="category-head">
          <h2 style="border-color:{color}"><span class="dot" style="background:{color}"></span>{cat}</h2>
          <a class="ver-todas" href="{base_prefix}{category_slug(cat)}/">Ver todas &rarr;</a>
        </div>
        <div class="cards">{cards}</div>
      </section>""")

    total = len(articles)
    body = f'<div class="stats">{total} notas publicadas de los últimos {RETENTION_DAYS} días · actualizado {today_str}</div>' + "".join(sections)
    return page_shell(title="Inicio", base_prefix=base_prefix, body_html=body)


# ---------------------------------------------------------------------
# Página de categoría
# ---------------------------------------------------------------------

def build_category_html(cat, arts, today_str):
    base_prefix = "../"
    color = CATEGORY_COLORS.get(cat, "#555")
    arts_sorted = sorted(arts, key=lambda a: a.get("published_date", ""), reverse=True)

    if arts_sorted:
        cards_html = f'<div class="cards">{"".join(card_html(a, base_prefix) for a in arts_sorted)}</div>'
        desc = f"{len(arts_sorted)} nota(s) de los últimos {RETENTION_DAYS} días."
    else:
        # Sin notas vigentes ahora mismo (todas las anteriores salieron por
        # antigüedad). Regeneramos igual esta página -- si no lo hiciéramos,
        # se quedaría mostrando para siempre la última nota que tuvo, ya
        # retirada de los datos, lo cual sería información obsoleta.
        cards_html = '<p class="page-desc">Todavía no hay notas recientes en esta categoría. Vuelve pronto.</p>'
        desc = "0 notas de los últimos " + f"{RETENTION_DAYS} días."

    breadcrumb = f'<div class="breadcrumb"><a href="{base_prefix}">Inicio</a> / {cat}</div>'
    body = f"""
    <h1 class="page-title" style="color:{color}">{CATEGORY_EMOJI.get(cat, "📰")} {cat}</h1>
    <p class="page-desc">{desc}</p>
    {cards_html}"""
    return page_shell(title=cat, base_prefix=base_prefix, body_html=body, active_category=cat, breadcrumb_html=breadcrumb)


# ---------------------------------------------------------------------
# Página de nota individual (permalink)
# ---------------------------------------------------------------------

def build_note_html(a, related, today_str):
    base_prefix = "../../"
    cat = a.get("category", "Otros")
    color = CATEGORY_COLORS.get(cat, "#555")
    emoji = CATEGORY_EMOJI.get(cat, "📰")

    image_url = a.get("image_url")
    if image_url:
        photographer = a.get("image_photographer", "Pexels")
        photo_html = f"""
    <div class="note-photo">
      <img src="{image_url}" alt="">
      <span class="photo-credit">Foto: {photographer} / Pexels</span>
    </div>"""
    else:
        photo_html = f"""
    <div class="note-photo fallback" style="background:{color}">
      <span class="emoji">{emoji}</span>
    </div>"""

    related_html = ""
    if related:
        related_cards = "".join(card_html(r, base_prefix) for r in related[:3])
        related_html = f"""
    <h2 class="related-head">Más de {cat}</h2>
    <div class="cards">{related_cards}</div>"""

    breadcrumb = (
        f'<div class="breadcrumb"><a href="{base_prefix}">Inicio</a> / '
        f'<a href="{base_prefix}{category_slug(cat)}/">{cat}</a> / {a["title"]}</div>'
    )
    body = f"""
{photo_html}
    <span class="note-cat-badge" style="background:{color}">{cat}</span>
    <h1 class="page-title">{a['title']}</h1>
    <p class="note-summary">{a['summary']}</p>
    <p class="note-meta">Fuente: {a['source']} · {a['published_date']}</p>
    <a class="cta-source" href="{a['url']}" target="_blank" rel="noopener noreferrer">Leer la nota completa en {a['source']} &rarr;</a>
{related_html}"""
    return page_shell(title=a["title"], base_prefix=base_prefix, body_html=body, active_category=cat, breadcrumb_html=breadcrumb)


# ---------------------------------------------------------------------
# Orquestación: genera TODAS las páginas a partir de la lista vigente
# ---------------------------------------------------------------------

def build_site(articles, site_dir, today_str):
    """Escribe index.html, <categoria>/index.html y
    <categoria>/<slug>/index.html para cada nota vigente. No borra nada
    -- solo escribe/sobreescribe lo que corresponde a `articles`."""
    site_dir = Path(site_dir)

    by_category = defaultdict(list)
    for a in articles:
        by_category[a.get("category", "Otros")].append(a)

    pages_written = 0

    (site_dir / "index.html").write_text(build_home_html(articles, today_str), encoding="utf-8")
    pages_written += 1

    # Recorremos TODAS las categorías conocidas (no solo las que tienen
    # notas vigentes ahora mismo) para que la página de una categoría que
    # se quedó momentáneamente sin notas se regenere igual -- si solo
    # recorriéramos by_category, esa página se quedaría congelada
    # mostrando para siempre la última nota que tuvo, ya retirada de los
    # datos por antigüedad.
    all_categories = list(CATEGORY_ORDER)
    for cat in by_category:
        if cat not in all_categories:
            all_categories.append(cat)

    for cat in all_categories:
        arts = by_category.get(cat, [])
        cat_dir = site_dir / category_slug(cat)
        cat_dir.mkdir(parents=True, exist_ok=True)
        (cat_dir / "index.html").write_text(build_category_html(cat, arts, today_str), encoding="utf-8")
        pages_written += 1

        arts_sorted = sorted(arts, key=lambda a: a.get("published_date", ""), reverse=True)
        for a in arts_sorted:
            related = [r for r in arts_sorted if r["url"] != a["url"]]
            note_dir = cat_dir / a["slug"]
            note_dir.mkdir(parents=True, exist_ok=True)
            (note_dir / "index.html").write_text(build_note_html(a, related, today_str), encoding="utf-8")
            pages_written += 1

    return pages_written


# ---------------------------------------------------------------------
# main
# ---------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reescritos", default="reescritos.json")
    ap.add_argument("--site-dir", default=".")
    args = ap.parse_args()

    site_dir = Path(args.site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    data_dir = site_dir / "data"
    site_data_path = data_dir / "site_data.json"
    published_urls_path = data_dir / "published_urls.json"

    new_articles = load_json(args.reescritos, [])
    existing = load_json(site_data_path, [])

    merged, added, skipped = merge_articles(existing, new_articles)
    merged = prune_old(merged)

    today_str = datetime.now().strftime("%d de %B de %Y")
    pages_written = build_site(merged, site_dir, today_str)

    save_json(site_data_path, merged)
    save_json(published_urls_path, sorted(a["url"] for a in merged))

    n_categories = len({a.get("category", "Otros") for a in merged})
    print(f"Listo: {added} notas nuevas agregadas, {skipped} ya existían (duplicadas por URL).")
    print(f"Total vigente en el sitio: {len(merged)} notas de los últimos {RETENTION_DAYS} días, en {n_categories} categorías.")
    print(f"Páginas generadas: {pages_written} (1 home + páginas de categoría + 1 permalink por nota).")
    print(f"Archivos escritos en {site_dir}/: index.html, <categoria>/, data/site_data.json, data/published_urls.json")


if __name__ == "__main__":
    main()
