#!/usr/bin/env python3
"""
Paso de "ilustración" del pipeline "Buenas Noticias" -- busca una foto real
en Pexels para cada nota que todavía no tenga una, y regenera el HTML del
sitio con esas fotos.

POR QUÉ ESTE SCRIPT VIVE EN GITHUB ACTIONS Y NO EN UNA SKILL DE CLAUDE:
La API de Pexels exige el header HTTP "Authorization: <API_KEY>" en cada
petición (está documentado así, no acepta la clave como parámetro de
URL). El entorno donde corren las skills de Claude en este proyecto no
tiene salida de red directa a dominios arbitrarios -- solo a través de
herramientas específicas que no permiten mandar headers personalizados.
GitHub Actions sí tiene salida de red normal, así que aquí es donde se
hace la llamada real a la API, de la forma en que Pexels la documenta.

Este script NO decide qué buscar -- esa decisión (las palabras clave en
inglés, campo "image_query") ya la tomó la fase 3 (reescribir) del
pipeline, porque ahí es donde Claude tiene el contexto completo de la
nota para elegir bien qué imagen la representa. Este script solo hace la
llamada mecánica a la API y actualiza los datos.

Uso (pensado para correr dentro del workflow de GitHub Actions, no a mano):
    PEXELS_API_KEY=... python3 attach_photos.py --site-dir ./site

Qué hace:
  1. Lee site_data.json.
  2. Para cada nota con "image_query" pero sin "image_url" todavía (y que
     no se haya intentado ya, para no gastar cuota de la API en algo que
     ya sabemos que no tiene buen resultado), busca en Pexels.
  3. Si encuentra una foto en orientación horizontal, guarda su URL, el
     nombre del fotógrafo, y el link a la foto en Pexels (para dar
     crédito). Si no encuentra nada razonable, deja image_url en null --
     build_site.py ya sabe mostrar el respaldo ilustrado en ese caso.
  4. Marca cada nota como "image_attempted": true para no reintentar en
     cada corrida (Pexels es gratis pero no hay razón para golpear la API
     de más).
  5. Regenera TODAS las páginas del sitio (home, categorías y permalinks)
     reutilizando exactamente las mismas funciones build_site()/
     build_home_html()/etc. que usa el script de la fase de publicación,
     para que el sitio se vea idéntico sea cual sea el script que lo
     generó por última vez.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"

# Reutiliza la lógica de renderizado del script de publicación -- ambos
# scripts deben vivir en el mismo repo (scripts/build_site.py y
# .github/scripts/attach_photos.py) para que este import funcione.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
try:
    from build_site import build_site, load_json, save_json  # noqa: E402
except ImportError:
    print(
        "ERROR: no se encontró scripts/build_site.py en la raíz del repo. "
        "Este script asume la estructura: scripts/build_site.py + "
        ".github/scripts/attach_photos.py",
        file=sys.stderr,
    )
    raise


def search_pexels(query, api_key, timeout=15):
    """Devuelve (url, photographer, source_url) o None si no hay un buen resultado."""
    url = f"{PEXELS_SEARCH_URL}?query={urllib.parse.quote(query)}&per_page=5&orientation=landscape"
    # Pexels (como muchas APIs detras de un WAF/Cloudflare) puede rechazar
    # con 403 peticiones que traen el User-Agent generico por defecto de
    # urllib ("Python-urllib/3.x"). Se manda un User-Agent de navegador
    # real para evitar ese bloqueo -- la clave sigue yendo en el header
    # Authorization tal como lo documenta Pexels.
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": api_key,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        print(f"  Pexels devolvió HTTP {e.code} para '{query}': {e.reason} | body={body}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Error de red buscando '{query}': {e}", file=sys.stderr)
        return None

    photos = data.get("photos") or []
    if not photos:
        return None

    p = photos[0]
    # "large" es un buen tamaño para tarjetas de portal (~940px de ancho).
    image_url = p.get("src", {}).get("large") or p.get("src", {}).get("original")
    photographer = p.get("photographer", "Pexels")
    source_url = p.get("url", "https://www.pexels.com")
    if not image_url:
        return None
    return image_url, photographer, source_url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-dir", default=".")
    args = ap.parse_args()

    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        print(
            "ERROR: falta la variable de entorno PEXELS_API_KEY. "
            "En GitHub Actions esto se configura como Secret del repositorio "
            "y se pasa al paso del workflow con `env:`.",
            file=sys.stderr,
        )
        sys.exit(1)

    site_dir = Path(args.site_dir)
    site_data_path = site_dir / "data" / "site_data.json"

    articles = load_json(site_data_path, [])
    if not articles:
        print("No hay site_data.json (o está vacío) -- nada que ilustrar todavía.")
        return

    pending = [
        a for a in articles
        if a.get("image_query") and not a.get("image_attempted")
    ]
    if not pending:
        print("Todas las notas ya tienen foto asignada o ya se intentó buscarla. Nada que hacer.")
        return

    print(f"Buscando foto para {len(pending)} nota(s) nueva(s)...")
    found, not_found = 0, 0
    for a in pending:
        query = a["image_query"]
        result = search_pexels(query, api_key)
        a["image_attempted"] = True
        if result:
            image_url, photographer, source_url = result
            a["image_url"] = image_url
            a["image_photographer"] = photographer
            a["image_source_url"] = source_url
            found += 1
            print(f"  ✓ '{query}' -> foto de {photographer}")
        else:
            not_found += 1
            print(f"  · '{query}' -> sin resultado, se usará el respaldo ilustrado")
        time.sleep(0.3)  # cortesía con la API, muy por debajo del límite gratuito (200/hora)

    save_json(site_data_path, articles)

    # Regenera todas las páginas del sitio (home, categorías y permalinks)
    # con las fotos ya asignadas.
    from datetime import datetime
    today_str = datetime.now().strftime("%d de %B de %Y")
    pages_written = build_site(articles, site_dir, today_str)

    print(f"\nListo: {found} foto(s) encontradas, {not_found} sin resultado (usan respaldo ilustrado).")
    print(f"Sitio regenerado en {site_dir}/ ({pages_written} páginas).")


if __name__ == "__main__":
    main()
