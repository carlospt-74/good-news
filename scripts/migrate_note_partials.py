#!/usr/bin/env python3
"""
Migracion de una sola vez (backfill de la Fase 2): reemplaza el header y el
footer inline de las paginas de nota ya publicadas (congeladas por la
politica Fase 3(b), ver build_site.py) por el patron nuevo de header/footer
compartido via assets/partials.js (ver build_site.py, page_shell() y
partials_js()).

Por que existe como script aparte y no como parte de build_site.py:
build_site.py nunca reescribe una pagina de nota que ya existe (a proposito,
ver Fase 3(b)) -- este script es la excepcion deliberada y unica, pensada
para correrse una sola vez (o las veces que haga falta: es idempotente,
salta las paginas que ya esten migradas).

Uso:
    python3 scripts/migrate_note_partials.py --site-dir .

Que hace, por cada nota registrada en data/site_data.json:
  1. Ubica su pagina en <categoria>/<slug>/index.html.
  2. Si ya tiene id="site-header-mount" (ya migrada), la salta.
  3. Si el HTML no calza con el patron viejo esperado (<header
     class="site-header">...</header> y <footer>...</footer> sin id), la
     deja intacta y la reporta -- nunca fuerza un reemplazo a ciegas sobre
     una forma que no reconoce.
  4. Si calza, reemplaza ambos bloques por el patron nuevo (mismo HTML que
     genera page_shell() para paginas nuevas), agrega
     data-active-category="<Categoria>" al <body>, e inserta
     <script defer src="../../assets/partials.js"></script> antes de
     </body>.
  5. Escribe el archivo de vuelta SOLO si el contenido cambio.

No toca site_data.json, published_urls.json, ni el contenido propio de la
nota (titulo, resumen, imagen, carrusel de relacionadas) -- unicamente el
header y el footer compartidos.
"""
import argparse
import json
import re
from pathlib import Path

from build_site import category_slug

HEADER_RE = re.compile(r'<header class="site-header">.*?</header>\n', re.DOTALL)
FOOTER_RE = re.compile(r'<footer>.*?</footer>\n', re.DOTALL)


def new_header_html(base_prefix):
    return (
        f'<header class="site-header" id="site-header-mount">\n'
        f'  <noscript><div class="header-inner"><a href="{base_prefix}" class="logo">'
        f'<img src="{base_prefix}assets/logo.png" alt="Buenas Noticias" class="logo-img"></a></div></noscript>\n'
        f'</header>\n'
    )


def new_footer_html(base_prefix):
    return (
        f'<footer id="site-footer-mount">\n'
        f'  <noscript>\n'
        f'    <div class="foot-inner">\n'
        f'      <a href="{base_prefix}" class="logo"><img src="{base_prefix}assets/logo.png" alt="Buenas Noticias" class="logo-img"></a>\n'
        f'      <p class="legal">Buenas Noticias no aloja el contenido completo de las notas; siempre enlazamos a la fuente original.</p>\n'
        f'    </div>\n'
        f'  </noscript>\n'
        f'</footer>\n'
    )


def migrate_file(path, category, base_prefix="../../"):
    """Devuelve True si migro el archivo, False si ya estaba migrado, o
    una cadena con el motivo si no pudo migrarlo (forma inesperada)."""
    html = path.read_text(encoding="utf-8")

    if 'id="site-header-mount"' in html:
        return False  # ya migrada, nada que hacer

    if not HEADER_RE.search(html):
        return 'no se encontro el bloque <header class="site-header">...</header> esperado'
    if not FOOTER_RE.search(html):
        return 'no se encontro el bloque <footer>...</footer> esperado'
    if "<body>" not in html:
        return "no se encontro <body> sin atributos"
    if "</body>" not in html:
        return "no se encontro </body>"

    updated = HEADER_RE.sub(new_header_html(base_prefix), html, count=1)
    updated = FOOTER_RE.sub(new_footer_html(base_prefix), updated, count=1)
    updated = updated.replace("<body>", f'<body data-active-category="{category}">', 1)
    updated = updated.replace(
        "</body>",
        f'<script defer src="{base_prefix}assets/partials.js"></script>\n</body>',
        1,
    )

    if updated == html:
        return "el reemplazo no cambio nada (inesperado)"

    path.write_text(updated, encoding="utf-8")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-dir", default=".")
    args = ap.parse_args()

    site_dir = Path(args.site_dir)
    site_data_path = site_dir / "data" / "site_data.json"
    articles = json.loads(site_data_path.read_text(encoding="utf-8"))

    migrated, already_ok, missing_file, failed = 0, 0, [], []

    for a in articles:
        cat = a.get("category", "Otros")
        slug = a.get("slug")
        note_file = site_dir / category_slug(cat) / slug / "index.html"
        if not note_file.exists():
            missing_file.append(str(note_file))
            continue
        result = migrate_file(note_file, cat)
        if result is True:
            migrated += 1
        elif result is False:
            already_ok += 1
        else:
            failed.append((str(note_file), result))

    print(f"Migradas: {migrated}")
    print(f"Ya estaban al dia: {already_ok}")
    print(f"Archivo de nota no encontrado en disco: {len(missing_file)}")
    print(f"No se pudieron migrar (forma inesperada): {len(failed)}")
    for path, reason in failed:
        print(f"  - {path}: {reason}")
    for path in missing_file:
        print(f"  - (faltante) {path}")


if __name__ == "__main__":
    main()
