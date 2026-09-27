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
  4. Regenera Home y todas las páginas de categoría (su contenido cambia
     cada corrida). Para las páginas de nota individual, en cambio, SOLO
     genera las que todavía no existen -- una página de nota, una vez
     publicada, no se vuelve a tocar nunca (ni su carrusel de "Más de
     <categoría>", que queda fijo con las notas que existían en ese
     momento). Esto es deliberado: antes, publicar 10 notas nuevas
     implicaba reescribir ~90 páginas viejas solo para refrescar ese
     carrusel, lo cual es carísimo de transmitir por este pipeline. El
     costo es que el carrusel de una nota vieja puede quedar desactualizado
     con el tiempo; el beneficio es que cada publicación semanal solo toca
     los archivos que realmente son nuevos. Excepción: --rebuild-notes
     regenera también las notas ya publicadas, para cuando un cambio de
     plantilla tiene que llegar a todas (como el rediseño 2026-09-27).
  5. Escribe (una sola vez por corrida, siempre igual) el CSS compartido en
     assets/styles.css, el sprite de íconos en assets/icons.svg y el
     header/footer en assets/partials.js, y hace que todas las páginas lo referencien con
     <link> en vez de repetirlo inline en cada <style> -- así el CSS se
     actualiza en un solo lugar y cada página pesa una fracción de lo que
     pesaba antes.
  6. Actualiza published_urls.json para que la fase 1 (búsqueda) sepa qué
     ya se publicó y no lo repita.

Este script solo RENDERIZA -- no busca fotos (eso lo hace attach_photos.py
en GitHub Actions, ver ese script) ni decide qué es una buena noticia (eso
ya se decidió en las fases 2 y 3). Si una nota no tiene "image_url"
todavía, se muestra con un respaldo ilustrado por categoría en vez de un
hueco vacío o una imagen rota.
"""

import argparse
import html
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import urllib.parse

RETENTION_DAYS = 120

# Cuántas notas entran en el bloque "Destacadas de hoy" del Home, y cómo
# se eligen: por ahora, simplemente las más recientes de todo el sitio sin
# importar categoría. Este es un criterio PROVISIONAL -- quedó pendiente
# que el usuario defina el criterio real (ver documento de propuesta de
# estructura, sección 7, "Próximos pasos"). Cambiar esto es tan fácil como
# editar la función choose_featured() más abajo.
FEATURED_COUNT = 3

CATEGORY_ORDER = ["Deportes", "Economía", "Ciencia y Salud", "Medio Ambiente", "Sociedad", "Tecnología", "Cultura", "IA", "Otros"]

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


MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def fecha_larga_es(dt=None):
    """Formatea una fecha como '24 de agosto de 2026', en español, sin
    depender del locale del sistema operativo (strftime("%B") depende del
    locale activo y en muchos entornos -- como los runners de GitHub
    Actions -- ese locale es en_US, lo que producia fechas como
    '24 de August de 2026'). Este helper evita ese problema por completo."""
    dt = dt or datetime.now()
    return f"{dt.strftime('%d')} de {MESES_ES[dt.month - 1]} de {dt.year}"


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
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    text = re.sub(r"-{2,}", "-", text)
    text = text[:max_len].rstrip("-")
    return text or "nota"


def unique_slug(base, used_slugs):
    slug = base
    n = 2
    while slug in used_slugs:
        slug = f"{base}-{n}"
        n += 1
    used_slugs.add(slug)
    return slug


def category_slug(cat):
    return CATEGORY_SLUGS.get(cat, slugify(cat))


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


def remove_articles(existing, urls_to_remove, site_dir):
    """Quita del histórico las notas cuya URL esté en urls_to_remove, y borra
    del disco la página permalink de cada una (cat_dir/slug/index.html, y la
    carpeta si queda vacía). Pensado para correcciones y pruebas -- borrar
    del listado sin esto dejaría la página permalink huérfana para siempre,
    ya que build_site() nunca reescribe una página de nota que ya existe."""
    urls_to_remove = set(urls_to_remove)
    if not urls_to_remove:
        return existing, 0
    site_dir = Path(site_dir)
    kept = []
    removed = 0
    for a in existing:
        if a.get("url") in urls_to_remove:
            removed += 1
            slug = a.get("slug")
            if slug:
                note_dir = site_dir / category_slug(a.get("category", "Otros")) / slug
                note_file = note_dir / "index.html"
                if note_file.exists():
                    note_file.unlink()
                try:
                    note_dir.rmdir()
                except OSError:
                    pass  # no estaba vacía o no existía; no es un error
            continue
        kept.append(a)
    return kept, removed


def prune_old(articles, retention_days=RETENTION_DAYS):
    cutoff = datetime.now() - timedelta(days=retention_days)
    kept = []
    for a in articles:
        try:
            d = datetime.strptime(a.get("published_date", a.get("date_added", "1970-01-01")), "%Y-%m-%d")
        except ValueError:
            d = datetime.now()
        if d >= cutoff:
            kept.append(a)
    return kept


def choose_featured(articles, count=FEATURED_COUNT):
    ordered = sorted(articles, key=lambda a: a.get("published_date", ""), reverse=True)
    return ordered[:count]

# ---------------------------------------------------------------------------
# Diseño (rediseño 2026-09-27). Todo lo de aquí para abajo es presentación:
# CSS, íconos, header/footer compartidos y las tres plantillas (home,
# categoría, nota). La lógica de datos de arriba no depende de nada de esto.
# ---------------------------------------------------------------------------

# Ícono (id dentro de assets/icons.svg) y frase de cada categoría.
CATEGORY_ICONS = {
    "Deportes": "i-trophy",
    "Economía": "i-trend",
    "Ciencia y Salud": "i-flask",
    "Medio Ambiente": "i-leaf",
    "Sociedad": "i-users",
    "Tecnología": "i-cpu",
    "Cultura": "i-palette",
    "IA": "i-spark",
    "Otros": "i-news",
}
CATEGORY_DESC = {
    "Deportes": "Hazañas, primeras veces y atletas que ponen en alto a todo el continente.",
    "Economía": "Empleos, emprendimientos y cifras que mejoran la vida de la gente.",
    "Ciencia y Salud": "Avances médicos, descubrimientos y ciencia hecha en América que ya están cambiando vidas.",
    "Medio Ambiente": "Especies que regresan, bosques que se recuperan y comunidades que cuidan su entorno.",
    "Sociedad": "Personas y comunidades que se organizan para ayudar a otros.",
    "Tecnología": "Inventos e innovación con un beneficio concreto para las personas.",
    "Cultura": "Arte, música, libros y tradiciones que nos conectan.",
    "IA": "Inteligencia artificial con un beneficio humano directo y verificable.",
    "Otros": "Buenas noticias que no caben en una sola categoría.",
}

MESES_CORTOS_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def fecha_corta_es(iso):
    """'2026-09-25' -> '25 sep 2026' (sin depender del locale, igual que
    fecha_larga_es). Si la fecha viene en otro formato, la deja tal cual."""
    try:
        d = datetime.strptime(iso, "%Y-%m-%d")
    except (TypeError, ValueError):
        return iso or ""
    return f"{d.day} {MESES_CORTOS_ES[d.month - 1]} {d.year}"


def esc(text):
    return html.escape(str(text or ""), quote=True)


FONT_LINKS = """<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400..700;1,6..72,400..600&family=Public+Sans:wght@400;500;600;700&family=Caveat+Brush&display=swap" rel="stylesheet">"""


def icons_svg():
    """Sprite de íconos (trazos estilo Lucide) que todas las páginas usan con
    <svg><use href=".../assets/icons.svg#i-..."></svg>. Reemplaza a los
    emojis de categoría del diseño anterior."""
    return """<svg xmlns="http://www.w3.org/2000/svg">
  <symbol id="i-flask" viewBox="0 0 24 24"><path d="M9 3h6M10 3v6L4.5 19a1.5 1.5 0 0 0 1.3 2h12.4a1.5 1.5 0 0 0 1.3-2L14 9V3M7 15h10"/></symbol>
  <symbol id="i-leaf" viewBox="0 0 24 24"><path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.5 19 2c1 2 2 4.2 2 8 0 5.5-4.8 10-10 10Z"/><path d="M2 21c0-3 1.9-5.4 5.1-6"/></symbol>
  <symbol id="i-trend" viewBox="0 0 24 24"><path d="m22 7-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/></symbol>
  <symbol id="i-trophy" viewBox="0 0 24 24"><path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6M18 9h1.5a2.5 2.5 0 0 0 0-5H18M4 22h16M10 14.7V17c0 .6-.5 1-1 1.2C7.8 18.8 7 20.2 7 22M14 14.7V17c0 .6.5 1 1 1.2 1.2.6 2 2 2 3.8M18 2H6v7a6 6 0 0 0 12 0V2Z"/></symbol>
  <symbol id="i-users" viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/></symbol>
  <symbol id="i-cpu" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M15 2v2M15 20v2M2 15h2M2 9h2M20 15h2M20 9h2M9 2v2M9 20v2"/></symbol>
  <symbol id="i-palette" viewBox="0 0 24 24"><circle cx="13.5" cy="6.5" r=".5"/><circle cx="17.5" cy="10.5" r=".5"/><circle cx="8.5" cy="7.5" r=".5"/><circle cx="6.5" cy="12.5" r=".5"/><path d="M12 2a10 10 0 0 0 0 20c.9 0 1.7-.8 1.7-1.7 0-.4-.2-.8-.4-1.1-.3-.3-.4-.7-.4-1.1 0-.9.7-1.7 1.7-1.7h2A5.6 5.6 0 0 0 22 11c0-5-4.5-9-10-9Z"/></symbol>
  <symbol id="i-spark" viewBox="0 0 24 24"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/></symbol>
  <symbol id="i-news" viewBox="0 0 24 24"><path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8M15 18h-5M10 6h8v4h-8Z"/></symbol>
  <symbol id="i-arrow" viewBox="0 0 24 24"><path d="M5 12h14M12 5l7 7-7 7"/></symbol>
  <symbol id="i-check" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></symbol>
  <symbol id="i-shield" viewBox="0 0 24 24"><path d="M20 13c0 5-3.5 7.5-7.7 9a1 1 0 0 1-.7 0C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.2-2.7a1.2 1.2 0 0 1 1.5 0C14.5 3.8 17 5 19 5a1 1 0 0 1 1 1Z"/><path d="m9 12 2 2 4-4"/></symbol>
  <symbol id="i-link" viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.8 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/></symbol>
  <symbol id="i-moon" viewBox="0 0 24 24"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></symbol>
  <symbol id="i-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4"/></symbol>
  <symbol id="i-grid" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/></symbol>
  <symbol id="i-menu" viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h16"/></symbol>
</svg>
"""


def shared_css():
    return """:root{
  --bg:#FBF8F1; --surface:#FFFFFF; --ink:#14231A; --muted:#55645B; --line:#E7E1D2;
  --primary:#15803D; --primary-ink:#FFFFFF; --primary-soft:#E6F4EA;
  --sun:#F59E0B; --sun-soft:#FEF3C7; --ring:#15803D;
  --radius:20px; --shadow:0 1px 2px rgba(20,35,26,.05),0 8px 24px -12px rgba(20,35,26,.18);
  --serif:"Newsreader",Georgia,serif; --sans:"Public Sans",system-ui,sans-serif;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0E1511; --surface:#16201A; --ink:#EEF3EE; --muted:#A3B2A8; --line:#26332B;
  --primary:#4ADE80; --primary-ink:#0B1A10; --primary-soft:#173222; --sun:#FBBF24; --sun-soft:#3A2E0E; --ring:#4ADE80;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 8px 24px -12px rgba(0,0,0,.6);
}}
:root[data-theme="dark"]{
  --bg:#0E1511; --surface:#16201A; --ink:#EEF3EE; --muted:#A3B2A8; --line:#26332B;
  --primary:#4ADE80; --primary-ink:#0B1A10; --primary-soft:#173222; --sun:#FBBF24; --sun-soft:#3A2E0E; --ring:#4ADE80;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 8px 24px -12px rgba(0,0,0,.6);
}
*{box-sizing:border-box;margin:0}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--ink);font:400 16px/1.6 var(--sans);-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
img{display:block;max-width:100%}
:focus-visible{outline:2px solid var(--ring);outline-offset:3px;border-radius:8px}
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.wrap{max-width:1200px;margin:0 auto;padding:0 16px}
@media(min-width:768px){.wrap{padding:0 32px}}
svg.i{width:18px;height:18px;flex:none;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}

/* ---------- header ---------- */
header.site-header{position:sticky;top:0;z-index:50;backdrop-filter:saturate(1.6) blur(14px);-webkit-backdrop-filter:saturate(1.6) blur(14px);background:color-mix(in srgb,var(--bg) 78%,transparent);border-bottom:1px solid var(--line)}
.bar{display:flex;align-items:center;gap:16px;min-height:64px;flex-wrap:wrap}
.brand{display:flex;align-items:center;color:var(--ink)}
.brand .wm{display:flex;flex-direction:column;line-height:1}
.brand .wm b{font:400 28px/.9 "Caveat Brush",cursive;letter-spacing:.005em}
.brand .dot{display:inline-block;width:.24em;height:.24em;border-radius:50%;background:var(--sun);margin-left:.08em;box-shadow:0 0 0 .07em color-mix(in srgb,var(--sun) 25%,transparent)}
.brand .wm small{font:400 9.5px/1 var(--serif);letter-spacing:.36em;color:var(--muted);text-transform:uppercase;margin-top:5px;padding-left:2px}
.bar nav{display:none;order:3;flex-basis:100%;flex-direction:column;gap:2px;padding:4px 0 12px}
.bar nav.open{display:flex}
.bar nav a{white-space:nowrap;padding:10px 12px;border-radius:999px;font-size:14px;font-weight:500;color:var(--muted);transition:background .2s,color .2s}
.bar nav a:hover{background:var(--primary-soft);color:var(--ink)}
.bar nav a[aria-current="page"]{background:var(--primary-soft);color:var(--primary)}
.actions{margin-left:auto;display:flex;gap:8px}
.iconbtn{display:grid;place-items:center;width:44px;height:44px;border-radius:12px;border:1px solid var(--line);background:var(--surface);color:var(--ink);cursor:pointer;transition:border-color .2s}
.iconbtn:hover{border-color:var(--primary)}
@media(min-width:1180px){.bar{flex-wrap:nowrap}.bar nav,.bar nav.open{display:flex;order:0;flex-basis:auto;flex-direction:row;gap:4px;padding:0;margin-left:auto}.bar nav a{padding:8px 12px}.actions{margin-left:8px}#menu{display:none}}

/* ---------- hero (home) ---------- */
.hero{position:relative;overflow:hidden;padding:40px 0 8px;text-align:center}
.aurora{position:absolute;inset:-20% -10% auto;height:520px;z-index:-1;filter:blur(60px);opacity:.55;pointer-events:none}
.aurora span{position:absolute;border-radius:50%;animation:float 18s ease-in-out infinite}
.aurora span:nth-child(1){width:420px;height:420px;left:10%;top:10%;background:radial-gradient(circle,#FDE68A,transparent 70%)}
.aurora span:nth-child(2){width:380px;height:380px;right:12%;top:0;background:radial-gradient(circle,#86EFAC,transparent 70%);animation-delay:-6s}
.aurora span:nth-child(3){width:300px;height:300px;left:42%;top:30%;background:radial-gradient(circle,#FDBA74,transparent 70%);animation-delay:-12s}
@keyframes float{50%{transform:translate(40px,-30px) scale(1.1)}}
.eyebrow{display:inline-flex;align-items:center;gap:8px;padding:6px 14px;border-radius:999px;background:var(--surface);border:1px solid var(--line);font-size:13px;font-weight:600;color:var(--muted);box-shadow:var(--shadow)}
.eyebrow .live{width:8px;height:8px;border-radius:50%;background:var(--primary);box-shadow:0 0 0 0 var(--primary);animation:ping 2s infinite}
@keyframes ping{70%{box-shadow:0 0 0 8px transparent}100%{box-shadow:0 0 0 0 transparent}}
.hero h1{font:500 clamp(26px,5.2vw,56px)/1.08 var(--serif);letter-spacing:-.025em;margin:18px auto 0}
.hero h1 .l1{white-space:nowrap}
.rot{position:relative;display:inline-block;color:var(--primary);font-style:italic}
.rot span{position:absolute;left:0;white-space:nowrap;opacity:0;transform:translateY(.4em);transition:opacity .5s,transform .5s}
.rot span.on{position:relative;opacity:1;transform:none}
.hero p.lead{max-width:60ch;margin:14px auto 0;font-size:clamp(16px,1.6vw,17px);color:var(--muted);text-wrap:pretty}
.ctas{display:flex;flex-wrap:wrap;justify-content:center;gap:10px;margin-top:20px}
.ctas svg.i{width:16px;height:16px}
.btn{display:inline-flex;align-items:center;gap:6px;min-height:40px;padding:0 16px;border-radius:999px;font:600 14px var(--sans);cursor:pointer;border:1px solid transparent;transition:transform .15s,box-shadow .2s,background .2s}
.btn:active{transform:scale(.97)}
.btn.primary{background:var(--primary);color:var(--primary-ink);box-shadow:0 8px 20px -8px color-mix(in srgb,var(--primary) 70%,transparent)}
.btn.primary:hover{box-shadow:0 12px 28px -8px color-mix(in srgb,var(--primary) 80%,transparent)}
.btn.ghost{background:var(--surface);border-color:var(--line);color:var(--ink)}
.btn.ghost:hover{border-color:var(--primary)}
.stats{display:flex;flex-wrap:wrap;justify-content:center;gap:4px 14px;margin:18px auto 0;font-size:13px;color:var(--muted)}
.stats b{font-weight:600;color:var(--ink)}
.stats span+span::before{content:"·";margin-right:14px;opacity:.6}
@media(max-width:560px){.stats span+span::before{display:none}}

/* ---------- section heads ---------- */
section.block{padding:72px 0 0}
#hoy{padding-top:40px}
.head{display:flex;align-items:end;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:28px}
.head h2{font:500 clamp(30px,4vw,44px)/1.05 var(--serif);letter-spacing:-.02em}
.head p{color:var(--muted);max-width:48ch}
.more{display:inline-flex;align-items:center;gap:6px;font-weight:600;font-size:14px;color:var(--primary);min-height:44px}
.more:hover svg{transform:translateX(3px)}
.more svg{transition:transform .2s}

/* ---------- cards ---------- */
.bento{display:grid;gap:16px;grid-template-columns:1fr}
@media(min-width:900px){.bento{grid-template-columns:1.5fr 1fr;grid-template-rows:1fr 1fr}.bento .card:first-child{grid-row:span 2}}
.card{position:relative;display:flex;flex-direction:column;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;box-shadow:var(--shadow);transition:transform .25s,border-color .25s;isolation:isolate}
.card:hover{transform:translateY(-3px);border-color:color-mix(in srgb,var(--primary) 40%,var(--line))}
.card::after{content:"";position:absolute;inset:0;z-index:2;pointer-events:none;opacity:0;transition:opacity .3s;background:radial-gradient(420px circle at var(--x,50%) var(--y,50%),color-mix(in srgb,var(--sun) 16%,transparent),transparent 45%)}
.card:hover::after{opacity:1}
.media{position:relative;aspect-ratio:16/10;overflow:hidden;background:var(--line)}
.media img{width:100%;height:100%;object-fit:cover;transition:transform .6s}
.card:hover .media img{transform:scale(1.04)}
.media.fallback,.cover-fallback{display:grid;place-items:center;background:var(--primary-soft);color:var(--primary)}
.media.fallback svg.i{width:44px;height:44px;stroke-width:1.5}
.bento .card.feature{justify-content:flex-end;min-height:420px}
.bento .card.feature .media{position:absolute;inset:0;aspect-ratio:auto}
.bento .card.feature .media::after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,transparent 30%,rgba(8,16,11,.88))}
.bento .card.feature .media.fallback::after{background:none}
.bento .card.feature .body{flex:0 0 auto;position:relative;z-index:1;color:#fff}
.bento .card.feature.no-photo .body{color:var(--ink)}
.bento .card.feature .meta,.bento .card.feature .excerpt{color:rgba(255,255,255,.82)}
.bento .card.feature.no-photo .meta,.bento .card.feature.no-photo .excerpt{color:var(--muted)}
.body{display:flex;flex-direction:column;gap:10px;padding:20px 22px 22px;flex:1}
.tag{display:inline-flex;align-items:center;gap:6px;align-self:flex-start;padding:4px 10px;border-radius:999px;font-size:12px;font-weight:600;letter-spacing:.02em;background:var(--primary-soft);color:var(--primary)}
.feature:not(.no-photo) .tag{background:rgba(255,255,255,.16);color:#fff;backdrop-filter:blur(8px)}
.tag svg.i{width:14px;height:14px}
.card h3{font:600 21px/1.2 var(--serif);letter-spacing:-.01em;text-wrap:balance}
.feature h3{font-size:clamp(26px,3vw,36px);line-height:1.1}
.excerpt{color:var(--muted);font-size:15px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.meta{margin-top:auto;display:flex;align-items:center;gap:8px;font-size:13px;color:var(--muted)}
.meta .src{display:inline-grid;place-items:center;width:26px;height:26px;border-radius:50%;background:var(--sun-soft);color:var(--ink);font-size:10px;font-weight:700;flex:none}
.feature:not(.no-photo) .meta .src{background:rgba(255,255,255,.2);color:#fff}
.card > a.stretch{position:absolute;inset:0;z-index:3}

/* ---------- tabs + grid ---------- */
.tabs{display:flex;gap:8px;overflow-x:auto;padding-bottom:4px;margin-bottom:24px;scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tabs button{display:inline-flex;align-items:center;gap:8px;min-height:44px;padding:0 16px;border-radius:999px;border:1px solid var(--line);background:var(--surface);color:var(--muted);font:600 14px var(--sans);white-space:nowrap;cursor:pointer;transition:all .2s}
.tabs button:hover{color:var(--ink);border-color:var(--primary)}
.tabs button[aria-selected="true"]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr))}
.grid .card{animation:in .4s both}
@keyframes in{from{opacity:0;transform:translateY(8px)}}
.grid-foot{display:flex;justify-content:center;margin-top:20px}

/* ---------- trust strip ---------- */
.trust{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr))}
.trust div{padding:24px;border-radius:var(--radius);background:var(--surface);border:1px solid var(--line)}
.trust .ico{display:grid;place-items:center;width:44px;height:44px;border-radius:12px;background:var(--primary-soft);color:var(--primary);margin-bottom:14px}
.trust h4{font:600 19px var(--serif);margin-bottom:4px}
.trust p{color:var(--muted);font-size:15px}

/* ---------- breadcrumbs ---------- */
.crumbs{display:flex;align-items:center;flex-wrap:wrap;gap:8px;font-size:13px;color:var(--muted);padding-top:28px}
.crumbs a{color:var(--muted);min-height:32px;display:inline-flex;align-items:center}
.crumbs a:hover{color:var(--primary)}
.crumbs svg.i{width:14px;height:14px;opacity:.6}

/* ---------- category landing ---------- */
.cat-hero{position:relative;overflow:hidden;padding:0 0 8px}
.cat-hero .aurora{height:360px;opacity:.4}
.cat-title{display:flex;align-items:center;gap:16px;margin-top:12px}
.cat-ico{display:grid;place-items:center;width:56px;height:56px;border-radius:16px;background:var(--primary-soft);color:var(--primary);flex:none}
.cat-ico svg.i{width:26px;height:26px}
.cat-hero h1{font:500 clamp(34px,5vw,52px)/1.05 var(--serif);letter-spacing:-.025em}
.cat-hero p.desc{color:var(--muted);max-width:60ch;margin-top:12px;font-size:17px}
.cat-hero .count{margin-top:6px;font-size:13px;color:var(--muted)}
.cat-hero .count b{color:var(--ink)}
.switch{margin:24px 0 0}
.switch a{display:inline-flex;align-items:center;gap:8px;min-height:40px;padding:0 14px;border-radius:999px;border:1px solid var(--line);background:var(--surface);color:var(--muted);font:600 13px var(--sans);white-space:nowrap;transition:all .2s}
.switch a:hover{color:var(--ink);border-color:var(--primary)}
.switch a[aria-current="page"]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.switch svg.i{width:15px;height:15px}
.lead-card{display:grid;grid-template-columns:1fr}
@media(min-width:820px){.lead-card{grid-template-columns:1.25fr 1fr}.lead-card .media{aspect-ratio:auto;min-height:340px}}
.lead-card .body{padding:28px;justify-content:center;gap:14px}
.lead-card h3{font-size:clamp(24px,2.6vw,32px);line-height:1.12}
.lead-card .excerpt{-webkit-line-clamp:4;font-size:16px}
.lead-card .meta{margin-top:8px}
.list-head{display:flex;align-items:baseline;justify-content:space-between;margin:48px 0 20px;gap:12px}
.list-head h2{font:500 26px/1.1 var(--serif);letter-spacing:-.015em}
.list-head span{font-size:13px;color:var(--muted)}
.empty-note{color:var(--muted);padding:32px 0}

/* ---------- note page ---------- */
.article{width:100%}
.art-head{text-align:center}
.art-head .crumbs{justify-content:center}
.art-head .tag{margin-top:20px}
.art-head h1{font:500 clamp(26px,3.4vw,38px)/1.15 var(--serif);letter-spacing:-.02em;margin:14px auto 0;max-width:30ch;text-wrap:balance}
.byline{display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:6px 14px;margin-top:18px;font-size:14px;color:var(--muted)}
.byline .who{display:inline-flex;align-items:center;gap:8px;color:var(--ink);font-weight:600}
.byline .src{display:inline-grid;place-items:center;width:30px;height:30px;border-radius:50%;background:var(--sun-soft);color:var(--ink);font-size:11px;font-weight:700}
.byline .sep::before{content:"·";opacity:.6}
@media(max-width:560px){.byline .sep{display:none}}
.cover{margin:28px 0 0}
.cover img,.cover-fallback{width:100%;aspect-ratio:16/9;max-height:520px;object-fit:cover;border-radius:var(--radius);background:var(--line)}
.cover-fallback svg.i{width:72px;height:72px;stroke-width:1.3}
.cover figcaption{font-size:12px;color:var(--muted);margin-top:8px}
.art-body{display:grid;gap:32px;margin-top:36px}
@media(min-width:960px){.art-body{grid-template-columns:minmax(0,1fr) 340px;gap:56px}.art-side{position:sticky;top:88px;align-self:start}}
.art-side{display:grid;gap:16px}
.prose{max-width:68ch}
.prose p{font-size:clamp(17px,1.9vw,19px);line-height:1.75;margin-bottom:1.1em;text-wrap:pretty}
.prose p:first-child::first-letter{float:left;font:600 3.4em/.85 var(--serif);color:var(--primary);margin:.08em .1em 0 0}
.source-box{display:grid;gap:14px;padding:24px;border-radius:var(--radius);background:var(--primary-soft);border:1px solid color-mix(in srgb,var(--primary) 25%,transparent)}
.source-box p{font-size:15px;color:var(--ink)}
.source-box p span{color:var(--muted)}
.source-box .btn{justify-self:start}
.share{display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:20px 24px;border:1px solid var(--line);border-radius:var(--radius);background:var(--surface);font-size:14px;color:var(--muted)}
.share > span{flex-basis:100%}
.more-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin:64px 0 20px;padding-top:32px;border-top:1px solid var(--line)}
.more-head h2{font:500 28px/1.1 var(--serif);letter-spacing:-.015em}

/* ---------- footer ---------- */
footer.site-footer .wrap{margin-top:72px;border-top:1px solid var(--line);padding-top:48px;padding-bottom:32px;color:var(--muted);font-size:14px;text-align:center}
footer .flogo{display:inline-flex;margin-bottom:20px;text-align:left}
footer .note{max-width:62ch;margin:0 auto;display:grid;gap:10px;line-height:1.65;text-wrap:pretty}
footer .note strong{color:var(--ink);font-weight:600}
footer .legal{display:flex;flex-wrap:wrap;gap:6px 16px;justify-content:center;margin-top:28px;font-size:13px}
footer .legal span+span::before{content:"·";margin-right:16px;opacity:.6}

@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
"""


def category_nav_items():
    """Lista [(nombre, slug), ...] de categorias para el menu, en el orden
    oficial, excluyendo "Otros" -- la fuente de verdad que partials_js()
    serializa dentro de assets/partials.js (ver Fase 2 mas abajo)."""
    return [(cat, category_slug(cat)) for cat in CATEGORY_ORDER if cat != "Otros"]


_PARTIALS_JS_TEMPLATE = """(function () {
  var ROOT = "/good-news/";
  var CATEGORIES = __CATEGORIES_JSON__;
  var ICONS = ROOT + "assets/icons.svg#";
  var YEAR = new Date().getFullYear();

  function icon(id) { return '<svg class="i" aria-hidden="true"><use href="' + ICONS + id + '"/></svg>'; }
  var WORDMARK = '<span class="wm"><b>buenas noticias<span class="dot" aria-hidden="true"></span></b><small>Always positive</small></span>';

  function navLinksHtml(activeCategory) {
    return CATEGORIES.map(function (item) {
      var name = item[0], slug = item[1];
      var cur = (name === activeCategory) ? ' aria-current="page"' : '';
      return '<a href="' + ROOT + slug + '/"' + cur + '>' + name + '</a>';
    }).join('');
  }

  function headerInnerHtml(activeCategory) {
    return '<div class="wrap bar">' +
      '<a class="brand" href="' + ROOT + '" aria-label="Buenas Noticias, inicio">' + WORDMARK + '</a>' +
      '<nav id="site-nav" aria-label="Categorías">' + navLinksHtml(activeCategory) + '</nav>' +
      '<div class="actions">' +
        '<button class="iconbtn" id="menu" type="button" aria-label="Abrir menú de categorías" aria-expanded="false" aria-controls="site-nav">' + icon('i-menu') + '</button>' +
        '<button class="iconbtn" id="theme" type="button" aria-label="Cambiar tema claro/oscuro">' + icon('i-moon') + '</button>' +
      '</div></div>';
  }

  function footerInnerHtml() {
    return '<div class="wrap">' +
      '<a class="flogo brand" href="' + ROOT + '" aria-label="Buenas Noticias, inicio">' + WORDMARK + '</a>' +
      '<div class="note">' +
        '<p><strong>Buenas Noticias no aloja el contenido completo de las notas; siempre enlazamos a la fuente original.</strong></p>' +
        '<p>Cada resumen es una redacción original a partir de la nota fuente, nunca una copia. Los avatares muestran las iniciales del medio, no fotos de periodistas. Este portal no tiene reporteros propios, solo selecciona y resume buenas noticias ya publicadas por medios reales.</p>' +
      '</div>' +
      '<div class="legal"><span>© ' + YEAR + ' Buenas Noticias · Always positive</span><span>Fotos: Pexels</span></div>' +
      '</div>';
  }

  var headerMount = document.getElementById('site-header-mount');
  if (headerMount) {
    headerMount.innerHTML = headerInnerHtml(document.body.getAttribute('data-active-category') || '');
  }
  var footerMount = document.getElementById('site-footer-mount');
  if (footerMount) {
    footerMount.innerHTML = footerInnerHtml();
  }

  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Tema claro/oscuro: respeta la preferencia del sistema; el botón la
  // sobrescribe y se recuerda por visitante (localStorage puede fallar en
  // modo privado, por eso el try/catch).
  var root = document.documentElement;
  var themeBtn = document.getElementById('theme');
  function isDark() { return root.dataset.theme ? root.dataset.theme === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches; }
  function syncThemeIcon() { if (themeBtn) themeBtn.querySelector('use').setAttribute('href', ICONS + (isDark() ? 'i-sun' : 'i-moon')); }
  try { var saved = localStorage.getItem('bn-theme'); if (saved) root.dataset.theme = saved; } catch (e) {}
  syncThemeIcon();
  if (themeBtn) themeBtn.addEventListener('click', function () {
    root.dataset.theme = isDark() ? 'light' : 'dark';
    try { localStorage.setItem('bn-theme', root.dataset.theme); } catch (e) {}
    syncThemeIcon();
  });

  // Menú de categorías en pantallas angostas.
  var menuBtn = document.getElementById('menu'), nav = document.getElementById('site-nav');
  if (menuBtn && nav) menuBtn.addEventListener('click', function () {
    var open = nav.classList.toggle('open');
    menuBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
  });

  // Brillo que sigue al cursor sobre las tarjetas.
  document.addEventListener('pointermove', function (e) {
    var c = e.target.closest && e.target.closest('.card'); if (!c) return;
    var r = c.getBoundingClientRect();
    c.style.setProperty('--x', (e.clientX - r.left) + 'px');
    c.style.setProperty('--y', (e.clientY - r.top) + 'px');
  });

  // Palabra que rota en el titular del home.
  var words = document.querySelectorAll('.rot span');
  if (words.length && !reduce) {
    var w = 0;
    setInterval(function () { words[w].classList.remove('on'); w = (w + 1) % words.length; words[w].classList.add('on'); }, 2600);
  }

  // Contadores del home.
  document.querySelectorAll('[data-count]').forEach(function (el) {
    var to = +el.getAttribute('data-count');
    if (reduce) { el.textContent = to; return; }
    var t0 = performance.now();
    (function tick(t) {
      var p = Math.min((t - t0) / 1200, 1);
      el.textContent = Math.round(to * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(tick);
    })(t0);
  });

  // Pestañas de "Explora por tema": "Todas" muestra las más recientes; cada
  // categoría muestra sus notas más recientes y un enlace a su página.
  var tabs = document.getElementById('tabs'), grid = document.getElementById('grid'), catMore = document.getElementById('cat-more');
  if (tabs && grid) tabs.addEventListener('click', function (e) {
    var b = e.target.closest('button'); if (!b) return;
    var k = b.getAttribute('data-k');
    tabs.querySelectorAll('button').forEach(function (x) { x.setAttribute('aria-selected', x === b ? 'true' : 'false'); });
    grid.querySelectorAll('.card').forEach(function (c) {
      c.hidden = k === 'all' ? !c.hasAttribute('data-all') : !(c.getAttribute('data-cat') === k && c.hasAttribute('data-top'));
    });
    if (catMore) {
      catMore.hidden = k === 'all';
      if (k !== 'all') { catMore.href = ROOT + k + '/'; catMore.querySelector('span').textContent = 'Ver todas las de ' + b.textContent.trim(); }
    }
  });

  // Copiar enlace en la página de nota.
  var copyBtn = document.getElementById('copy');
  if (copyBtn) copyBtn.addEventListener('click', function () {
    var label = copyBtn.querySelector('span');
    if (!navigator.clipboard) { label.textContent = ' No se pudo copiar'; return; }
    navigator.clipboard.writeText(location.href).then(
      function () { label.textContent = ' ¡Enlace copiado!'; },
      function () { label.textContent = ' No se pudo copiar'; });
  });
})();
"""


def partials_js():
    """Fase 2 de la optimizacion de tokens: header y footer viven en este
    unico archivo compartido (assets/partials.js) -- ya no van inlineados
    en cada pagina HTML generada. page_shell() solo deja un
    <header id="site-header-mount"> y un <footer id="site-footer-mount">
    vacios (con un <noscript> de respaldo) y un <script defer> apuntando
    aqui; este script rellena ambos al cargar la pagina. Desde el rediseño
    2026-09-27 tambien lleva los comportamientos compartidos del sitio
    (tema claro/oscuro, menu movil, pestañas del home, copiar enlace), cada
    uno activo solo si su elemento existe en la pagina.

    ROOT esta hardcodeado a "/good-news/" porque GitHub Pages sirve este
    repo como project page en ese subpath, no en la raiz del dominio. Si el
    sitio algun dia se muda a un dominio propio, este valor es lo unico que
    hay que actualizar."""
    items_json = json.dumps(category_nav_items(), ensure_ascii=False)
    return _PARTIALS_JS_TEMPLATE.replace("__CATEGORIES_JSON__", items_json)


def get_avatar_initials(source):
    name = source.split("(")[0].strip()
    words = [w for w in re.split(r"\s+", name) if w]
    if not words:
        return "??"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def icon_html(base_prefix, icon_id):
    return f'<svg class="i" aria-hidden="true"><use href="{base_prefix}assets/icons.svg#{icon_id}"/></svg>'


def page_shell(*, title, base_prefix, body_html, active_category=None, description=None, image=None):
    active_attr = f' data-active-category="{esc(active_category)}"' if active_category else ""
    meta = ""
    if description:
        meta += f'\n<meta name="description" content="{esc(description)}">'
        meta += f'\n<meta property="og:title" content="{esc(title)}">\n<meta property="og:description" content="{esc(description)}">'
        meta += '\n<meta property="og:site_name" content="Buenas Noticias">\n<meta property="og:locale" content="es_LA">'
    if image:
        meta += f'\n<meta property="og:image" content="{esc(image)}">\n<meta name="twitter:card" content="summary_large_image">'
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)} · Buenas Noticias</title>{meta}
{FONT_LINKS}
<link rel="icon" type="image/png" href="{base_prefix}assets/favicon.png">
<link rel="stylesheet" href="{base_prefix}assets/styles.css">
</head>
<body{active_attr}>
<header class="site-header" id="site-header-mount">
  <noscript><div class="wrap bar"><a class="brand" href="{base_prefix}"><span class="wm"><b>buenas noticias</b><small>Always positive</small></span></a></div></noscript>
</header>
<main>
{body_html}
</main>
<footer class="site-footer" id="site-footer-mount">
  <noscript><div class="wrap"><div class="note"><p><strong>Buenas Noticias no aloja el contenido completo de las notas; siempre enlazamos a la fuente original.</strong></p></div></div></noscript>
</footer>
<script defer src="{base_prefix}assets/partials.js"></script>
</body>
</html>"""


def note_url(a, base_prefix):
    return f"{base_prefix}{category_slug(a.get('category', 'Otros'))}/{a['slug']}/"


def card_html(a, base_prefix, cls="card", attrs=""):
    cat = a.get("category", "Otros")
    icon_id = CATEGORY_ICONS.get(cat, "i-news")
    image_url = a.get("image_url")
    if image_url:
        media = f'<div class="media"><img src="{esc(image_url)}" alt="" loading="lazy" width="940" height="650"></div>'
    else:
        media = f'<div class="media fallback">{icon_html(base_prefix, icon_id)}</div>'
        cls += " no-photo"
    return f"""
    <article class="{cls}"{attrs}>
      {media}
      <div class="body">
        <span class="tag">{icon_html(base_prefix, icon_id)}{esc(cat)}</span>
        <h3>{esc(a['title'])}</h3>
        <p class="excerpt">{esc(a['summary'])}</p>
        <div class="meta"><span class="src" aria-hidden="true">{esc(get_avatar_initials(a['source']))}</span>{esc(a['source'])} · {fecha_corta_es(a.get('published_date'))}</div>
      </div>
      <a class="stretch" href="{note_url(a, base_prefix)}" aria-label="Leer: {esc(a['title'])}"></a>
    </article>"""


CURRENT = ' aria-current="page"'
HOME_RECENT = 12       # tarjetas en la pestaña "Todas" de "Explora por tema"
HOME_PER_CATEGORY = 6  # tarjetas por categoría en esa misma sección


def build_home_html(articles, today_str):
    bp = ""
    ordered = sorted(articles, key=lambda a: a.get("published_date", ""), reverse=True)
    featured = choose_featured(articles)
    featured_urls = {a["url"] for a in featured}
    rest = [a for a in ordered if a["url"] not in featured_urls]

    bento = "".join(card_html(a, bp, "card feature" if i == 0 else "card") for i, a in enumerate(featured))

    # "Explora por tema": cada tarjeta se renderiza una sola vez. data-all =
    # entra en "Todas" (las más recientes); data-top = entra en la pestaña de
    # su categoría. Sin JavaScript se ve "Todas" y el resto queda oculto.
    recent_urls = {a["url"] for a in rest[:HOME_RECENT]}
    per_cat = defaultdict(int)
    cats_present = []
    cards = []
    for a in rest:
        cat = a.get("category", "Otros")
        top = per_cat[cat] < HOME_PER_CATEGORY
        per_cat[cat] += 1
        if cat not in cats_present:
            cats_present.append(cat)
        is_recent = a["url"] in recent_urls
        if not (top or is_recent):
            continue
        attrs = f' data-cat="{category_slug(cat)}"' + (" data-all" if is_recent else "") + (" data-top" if top else "") + ("" if is_recent else " hidden")
        cards.append(card_html(a, bp, attrs=attrs))
    cats_present.sort(key=lambda c: CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else len(CATEGORY_ORDER))
    tabs = '<button role="tab" aria-selected="true" data-k="all">Todas</button>' + "".join(
        f'<button role="tab" aria-selected="false" data-k="{category_slug(c)}">{icon_html(bp, CATEGORY_ICONS.get(c, "i-news"))}{esc(c)}</button>'
        for c in cats_present)

    total = len(articles)
    num_categories = len({a.get("category", "Otros") for a in articles})
    arrow = icon_html(bp, "i-arrow")
    body = f"""
  <section class="hero">
    <div class="aurora" aria-hidden="true"><span></span><span></span><span></span></div>
    <div class="wrap">
      <span class="eyebrow"><span class="live" aria-hidden="true"></span>{today_str} · América</span>
      <h1><span class="l1">Todo lo que va <span class="sr-only">bien</span><span class="rot" aria-hidden="true"><span class="on">bien</span><span>mejorando</span><span>creciendo</span><span>sanando</span></span>,</span><br>en un solo lugar.</h1>
      <p class="lead">¿Cansado de que las noticias solo te dejen un nudo en el estómago? Reunimos avances reales de todo el continente, verificados y con enlace directo a la fuente, para que informarte no te cueste la calma.</p>
      <div class="ctas">
        <a class="btn primary" href="#hoy">Leer las de hoy {arrow}</a>
        <a class="btn ghost" href="#explorar">{icon_html(bp, "i-grid")} Explorar categorías</a>
      </div>
      <p class="stats"><span><b data-count="{total}">{total}</b> notas verificadas</span><span><b data-count="{num_categories}">{num_categories}</b> categorías</span><span><b data-count="{RETENTION_DAYS}">{RETENTION_DAYS}</b> días de archivo</span></p>
    </div>
  </section>

  <section class="block" id="hoy">
    <div class="wrap">
      <div class="head"><div><h2>Lo mejor de hoy</h2><p>Tres historias que vale la pena leer con un café.</p></div></div>
      <div class="bento">{bento}</div>
    </div>
  </section>

  <section class="block" id="explorar">
    <div class="wrap">
      <div class="head"><div><h2>Explora por tema</h2><p>Elige lo que te interesa; siempre con la fuente a un clic.</p></div></div>
      <div class="tabs" role="tablist" aria-label="Filtrar por categoría" id="tabs">{tabs}</div>
      <div class="grid" id="grid" role="tabpanel">{"".join(cards)}</div>
      <div class="grid-foot"><a class="btn ghost" id="cat-more" href="#" hidden><span>Ver todas</span> {arrow}</a></div>
    </div>
  </section>

  <section class="block">
    <div class="wrap trust">
      <div><span class="ico">{icon_html(bp, "i-shield")}</span><h4>Fuentes verificadas</h4><p>Cada nota pasa un filtro editorial: medio creíble, dato comprobable.</p></div>
      <div><span class="ico">{icon_html(bp, "i-check")}</span><h4>Cero ruido político</h4><p>Nada de polémicas ni titulares diseñados para enojarte.</p></div>
      <div><span class="ico">{icon_html(bp, "i-link")}</span><h4>Enlace a la original</h4><p>Resumimos con nuestras palabras y te llevamos a la nota completa.</p></div>
    </div>
  </section>"""
    return page_shell(title="Inicio", base_prefix=bp, body_html=body,
                      description="Buenas noticias reales y verificadas de todo el continente americano, con enlace directo a la fuente original.")


def build_category_html(cat, arts, today_str):
    bp = "../"
    icon_id = CATEGORY_ICONS.get(cat, "i-news")
    arts_sorted = sorted(arts, key=lambda a: a.get("published_date", ""), reverse=True)
    chev = icon_html(bp, "i-arrow")
    switch = "".join(
        f'<a href="{bp}{slug}/"{CURRENT if name == cat else ""}>{icon_html(bp, CATEGORY_ICONS.get(name, "i-news"))}{esc(name)}</a>'
        for name, slug in category_nav_items())

    if arts_sorted:
        listing = card_html(arts_sorted[0], bp, "card lead-card")
        if len(arts_sorted) > 1:
            listing += f"""
    <div class="list-head"><h2>Más recientes</h2><span>Ordenadas por fecha</span></div>
    <div class="grid">{"".join(card_html(a, bp) for a in arts_sorted[1:])}</div>"""
        count = f"<b>{len(arts_sorted)}</b> {'nota' if len(arts_sorted) == 1 else 'notas'} de los últimos {RETENTION_DAYS} días"
    else:
        listing = '<p class="empty-note">Todavía no hay notas recientes en esta categoría. Vuelve pronto.</p>'
        count = f"<b>0</b> notas de los últimos {RETENTION_DAYS} días"

    body = f"""
  <section class="cat-hero">
    <div class="aurora" aria-hidden="true"><span></span><span></span><span></span></div>
    <div class="wrap">
      <nav class="crumbs" aria-label="Ruta"><a href="{bp}">Inicio</a>{chev}<span aria-current="page">{esc(cat)}</span></nav>
      <div class="cat-title"><span class="cat-ico">{icon_html(bp, icon_id)}</span><h1>{esc(cat)}</h1></div>
      <p class="desc">{esc(CATEGORY_DESC.get(cat, ""))}</p>
      <p class="count">{count}</p>
      <nav class="tabs switch" aria-label="Otras categorías">{switch}</nav>
    </div>
  </section>

  <section class="wrap" style="padding-top:28px">
    {listing}
  </section>"""
    return page_shell(title=cat, base_prefix=bp, body_html=body, active_category=cat,
                      description=CATEGORY_DESC.get(cat))


def build_note_html(a, related, today_str):
    bp = "../../"
    cat = a.get("category", "Otros")
    icon_id = CATEGORY_ICONS.get(cat, "i-news")
    chev = icon_html(bp, "i-arrow")
    image_url = a.get("image_url")
    if image_url:
        photographer = a.get("image_photographer") or "Pexels"
        cover = f'<figure class="cover"><img src="{esc(image_url)}" alt="" width="940" height="650"><figcaption>Foto: {esc(photographer)} / Pexels</figcaption></figure>'
    else:
        cover = f'<figure class="cover"><div class="cover-fallback">{icon_html(bp, icon_id)}</div></figure>'

    minutes = max(1, round(len(a["summary"].split()) / 200))
    public_url = f"https://carlospt-74.github.io/good-news/{category_slug(cat)}/{a['slug']}/"
    wa = urllib.parse.quote(f"{a['title']} {public_url}")

    related_html = ""
    if related:
        related_html = f"""
    <div class="more-head"><h2>Más de {esc(cat)}</h2><a class="more" href="{bp}{category_slug(cat)}/">Ver todas {chev}</a></div>
    <div class="grid">{"".join(card_html(r, bp) for r in related[:3])}</div>"""

    body = f"""
  <article class="wrap">
    <div class="article">
      <div class="art-head">
        <nav class="crumbs" aria-label="Ruta"><a href="{bp}">Inicio</a>{chev}<a href="{bp}{category_slug(cat)}/">{esc(cat)}</a></nav>
        <span class="tag">{icon_html(bp, icon_id)}{esc(cat)}</span>
        <h1>{esc(a['title'])}</h1>
        <div class="byline">
          <span class="who"><span class="src" aria-hidden="true">{esc(get_avatar_initials(a['source']))}</span>{esc(a['source'])}</span>
          <span class="sep"></span><time datetime="{esc(a.get('published_date'))}">{fecha_corta_es(a.get('published_date'))}</time>
          <span class="sep"></span><span>{minutes} min de lectura</span>
        </div>
      </div>
      {cover}
      <div class="art-body">
        <div class="prose"><p>{esc(a['summary'])}</p></div>
        <aside class="art-side" aria-label="Fuente y compartir">
          <div class="source-box">
            <p><span>Este resumen es una redacción original de Buenas Noticias. La nota completa, con todos los detalles, está en</span> <strong>{esc(a['source'])}</strong>.</p>
            <a class="btn primary" href="{esc(a['url'])}" target="_blank" rel="noopener noreferrer">Leer la nota completa {chev}</a>
          </div>
          <div class="share">
            <span>Compartir esta buena noticia:</span>
            <a class="btn ghost" href="https://wa.me/?text={wa}" target="_blank" rel="noopener noreferrer">WhatsApp</a>
            <button class="btn ghost" id="copy" type="button">{icon_html(bp, "i-link")}<span> Copiar enlace</span></button>
          </div>
        </aside>
      </div>
    </div>
{related_html}
  </article>"""
    return page_shell(title=a["title"], base_prefix=bp, body_html=body, active_category=cat,
                      description=a["summary"][:200], image=image_url)


def write_shared_assets(site_dir):
    """Escribe los archivos compartidos por todo el sitio una sola vez por
    corrida (Fase 1 de la optimización de tokens): el CSS en
    assets/styles.css y el sprite de íconos en assets/icons.svg. Todas las
    páginas los referencian con <link>/<use> en vez de repetirlos."""
    assets_dir = Path(site_dir) / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "styles.css").write_text(shared_css(), encoding="utf-8")
    (assets_dir / "icons.svg").write_text(icons_svg(), encoding="utf-8")


def write_shared_partials(site_dir):
    """Escribe el header/footer compartidos una sola vez en
    assets/partials.js (Fase 2 de la optimizacion de tokens, ver
    partials_js() mas arriba) -- mismo patron que write_shared_assets()."""
    assets_dir = Path(site_dir) / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "partials.js").write_text(partials_js(), encoding="utf-8")


def build_site(articles, site_dir, today_str, rebuild_notes=False):
    """rebuild_notes=True regenera TODAS las páginas de nota, incluso las ya
    publicadas (que normalmente quedan congeladas, política Fase 3(b)). Es
    para un cambio de plantilla que tiene que llegar a todas las notas, como
    el rediseño 2026-09-27; en la operación semanal normal va en False."""
    site_dir = Path(site_dir)

    write_shared_assets(site_dir)
    write_shared_partials(site_dir)

    by_category = defaultdict(list)
    for a in articles:
        by_category[a.get("category", "Otros")].append(a)

    pages_written = 0

    (site_dir / "index.html").write_text(build_home_html(articles, today_str), encoding="utf-8")
    pages_written += 1

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
            note_dir = cat_dir / a["slug"]
            note_file = note_dir / "index.html"
            if note_file.exists() and not rebuild_notes:
                # Fase 3(b): una página de nota ya publicada NUNCA se
                # regenera en la operación normal (antes, cada corrida
                # reescribía todas las notas de una categoría solo para
                # refrescar su carrusel de "Más de <categoría>"). El home y
                # las categorías sí se regeneran siempre. La única excepción
                # es --rebuild-notes, para cambios de plantilla.
                continue
            related = [r for r in arts_sorted if r["url"] != a["url"]]
            note_dir.mkdir(parents=True, exist_ok=True)
            note_file.write_text(build_note_html(a, related, today_str), encoding="utf-8")
            pages_written += 1

    return pages_written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reescritos", default="reescritos.json")
    ap.add_argument("--site-dir", default=".")
    ap.add_argument("--eliminar", default=None, help="Ruta a un JSON con una lista de URLs a quitar del histórico (correcciones/pruebas), antes de fusionar lo nuevo.")
    ap.add_argument("--rebuild-notes", action="store_true", help="Regenera también las páginas de nota ya publicadas (solo para cambios de plantilla; ver build_site()).")
    args = ap.parse_args()

    site_dir = Path(args.site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    data_dir = site_dir / "data"
    site_data_path = data_dir / "site_data.json"
    published_urls_path = data_dir / "published_urls.json"

    new_articles = load_json(args.reescritos, [])
    existing = load_json(site_data_path, [])

    removed = 0
    if args.eliminar:
        urls_to_remove = load_json(args.eliminar, [])
        existing, removed = remove_articles(existing, urls_to_remove, site_dir)

    merged, added, skipped = merge_articles(existing, new_articles)
    merged = prune_old(merged)

    today_str = fecha_larga_es()
    pages_written = build_site(merged, site_dir, today_str, rebuild_notes=args.rebuild_notes)

    save_json(site_data_path, merged)
    save_json(published_urls_path, sorted(a["url"] for a in merged))

    n_categories = len({a.get("category", "Otros") for a in merged})
    if removed:
        print(f"Eliminadas: {removed} notas quitadas del historico (--eliminar).")
    print(f"Listo: {added} notas nuevas agregadas, {skipped} ya existían (duplicadas por URL).")
    print(f"Total vigente en el sitio: {len(merged)} notas de los últimos {RETENTION_DAYS} días, en {n_categories} categorías.")
    print(f"Páginas generadas: {pages_written} (1 home + páginas de categoría + 1 permalink por nota).")
    if args.rebuild_notes:
        print("Modo --rebuild-notes: se regeneraron también las páginas de nota ya publicadas.")
    print(f"Archivos escritos en {site_dir}/: index.html, <categoria>/, data/site_data.json, data/published_urls.json")


if __name__ == "__main__":
    main()
