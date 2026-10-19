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
  3. Si encuentra una foto en orientación horizontal cuyo contenido no
     contradice el género/demografía que pide la búsqueda (ver
     "_detect_gender_hint" / "_alt_contradicts_hint" más abajo), guarda su
     URL, el nombre del fotógrafo, y el link a la foto en Pexels (para dar
     crédito). Si no encuentra nada razonable, deja image_url en null --
     build_site.py ya sabe mostrar el respaldo ilustrado en ese caso.
  4. Marca cada nota como "image_attempted": true para no reintentar en
     cada corrida (Pexels es gratis pero no hay razón para golpear la API
     de más).
  5. Para cada nota que SÍ consiguió foto en esta corrida, borra su propia
     página permalink antes de regenerar el sitio (ver paso 6) -- necesario
     porque build_site() nunca reescribe una página de nota que ya existe
     (política "Fase 3(b)", pensada para no tocar notas ya publicadas), y
     esa página siempre existe ya en este punto (build_site.py la creó, sin
     foto, en la corrida de publicación que siempre corre antes que este
     script). Sin este borrado puntual, la nota queda con foto en el home y
     en su categoría, pero con el respaldo ilustrado para siempre en su
     propia página -- exactamente donde el lector cae al hacer clic. Es un
     borrado de un solo uso: una vez que la nota queda marcada
     "image_attempted": true, este script nunca la vuelve a tocar, así que
     su página no se vuelve a borrar/regenerar después de esta vez.
  6. Regenera TODAS las páginas del sitio (home, categorías, y las páginas
     de nota borradas en el paso 5) reutilizando exactamente las mismas
     funciones build_site()/build_home_html()/etc. que usa el script de la
     fase de publicación, para que el sitio se vea idéntico sea cual sea el
     script que lo generó por última vez.

SOBRE EL FILTRO DE GÉNERO/DEMOGRAFÍA (agregado 2026-10-19):
Antes, este script tomaba siempre el primer resultado que devolvía Pexels
(photos[0]) sin verificar nada más. Eso causó al menos dos casos reales de
foto equivocada: una nota sobre una poeta (mujer) terminó con la foto de un
hombre durmiendo, y una nota sobre la primera campeona nacional de lucha
femenina de la NCAA terminó con una foto de "boys training in sumo
wrestling" -- a pesar de que la búsqueda ya decía "women's wrestling
championship celebration". El problema no era solo la palabra clave: es
que la relevancia de texto de Pexels no es perfecta, y el script nunca
miraba más allá del primer resultado.

La corrección no es solo pedir mejores palabras clave (eso ya lo intenta
la fase 3, ver buenas-noticias-reescribir): es dejar de confiar a ciegas
en el primer resultado. Ahora, cuando la búsqueda menciona explícitamente
un género ("woman", "female", "man", "boy", etc.), se piden varios
candidatos (ya se pedían 5) y se descarta cualquiera cuyo texto
alternativo (el campo "alt" que la propia API de Pexels manda con cada
foto) contradiga ese género sin también mencionarlo -- por ejemplo, una
foto cuyo "alt" diga "Boys Training in Sumo Wrestling" se descarta para
una búsqueda de "female wrestler match". Si ninguno de los candidatos pasa
el filtro, se prefiere no poner foto (se usa el respaldo ilustrado por
categoría) antes que mostrar una claramente equivocada.
"""

import argparse
import json
import os
import re
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
    from build_site import build_site, load_json, save_json, fecha_larga_es, category_slug  # noqa: E402
except ImportError:
    print(
        "ERROR: no se encontró scripts/build_site.py en la raíz del repo. "
        "Este script asume la estructura: scripts/build_site.py + "
        ".github/scripts/attach_photos.py",
        file=sys.stderr,
    )
    raise


# Palabras que señalan explícitamente el género/demografía de la escena
# que se está buscando. Se usan tanto para leer la intención de la query
# (campo "image_query" que escribió la fase 3) como para leer el texto
# alternativo ("alt") que Pexels manda con cada foto candidata.
GENDER_HINT_WORDS = {
    "female": ["woman", "women", "female", "girl", "girls", "lady", "ladies"],
    "male": ["man", "men", "male", "boy", "boys", "guy", "guys"],
}


def _detect_gender_hint(query):
    """Si la query (en inglés, como las escribe la fase 3) menciona
    explícitamente un género, devuelve 'female' o 'male'. Si no, devuelve
    None -- no hay nada que validar y se mantiene el comportamiento de
    siempre (primer resultado razonable)."""
    q = (query or "").lower()
    for gender, words in GENDER_HINT_WORDS.items():
        for w in words:
            if re.search(rf"\b{re.escape(w)}\b", q):
                return gender
    return None


def _alt_contradicts_hint(alt_text, hint):
    """True si el texto alternativo de la foto apunta claramente al género
    opuesto al que pide la búsqueda, sin mencionar también el género
    buscado (si menciona ambos -- por ejemplo una foto de un equipo mixto
    -- se asume que no es un caso de foto equivocada y no se descarta)."""
    if not hint or not alt_text:
        return False
    alt = alt_text.lower()
    opposite = "male" if hint == "female" else "female"
    has_hint_words = any(re.search(rf"\b{re.escape(w)}\b", alt) for w in GENDER_HINT_WORDS[hint])
    has_opposite_words = any(re.search(rf"\b{re.escape(w)}\b", alt) for w in GENDER_HINT_WORDS[opposite])
    return has_opposite_words and not has_hint_words


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

    # Antes se tomaba siempre photos[0]. Ahora, si la query menciona un
    # género explícito, se recorren los candidatos (Pexels ya manda hasta
    # 5, ver per_page arriba) y se descarta cualquiera cuyo "alt" contradiga
    # ese género -- ver docstring del módulo para el caso real que motivó
    # esto (lucha femenina de la NCAA -> foto de niños haciendo sumo).
    hint = _detect_gender_hint(query)
    chosen = None
    for p in photos:
        alt_text = p.get("alt") or ""
        if _alt_contradicts_hint(alt_text, hint):
            print(f"  descartada por no calzar el género de la búsqueda ('{query}'): alt='{alt_text}'", file=sys.stderr)
            continue
        chosen = p
        break

    if chosen is None:
        # Todos los candidatos que llegaron contradicen el género buscado:
        # mejor no poner foto (el sitio usa el respaldo ilustrado por
        # categoría) que poner una claramente equivocada.
        return None

    # "large" es un buen tamaño para tarjetas de portal (~940px de ancho).
    image_url = chosen.get("src", {}).get("large") or chosen.get("src", {}).get("original")
    photographer = chosen.get("photographer", "Pexels")
    source_url = chosen.get("url", "https://www.pexels.com")
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
    newly_illustrated = []
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
            newly_illustrated.append(a)
            print(f"  ✓ '{query}' -> foto de {photographer}")
        else:
            not_found += 1
            print(f"  · '{query}' -> sin resultado, se usará el respaldo ilustrado")
        time.sleep(0.3)  # cortesía con la API, muy por debajo del límite gratuito (200/hora)

    save_json(site_data_path, articles)

    # Borrado de un solo uso: deja que build_site() regenere, esta vez con
    # foto, la página permalink de cada nota que la acaba de conseguir (ver
    # punto 5 del docstring). Si el archivo no existe por algún motivo, no
    # pasa nada -- build_site() la crea igual.
    for a in newly_illustrated:
        slug = a.get("slug")
        if not slug:
            continue
        note_file = site_dir / category_slug(a.get("category", "Otros")) / slug / "index.html"
        if note_file.exists():
            note_file.unlink()

    # Regenera todas las páginas del sitio (home, categorías, y las páginas
    # de nota borradas arriba) con las fotos ya asignadas.
    today_str = fecha_larga_es()
    pages_written = build_site(articles, site_dir, today_str)

    print(f"\nListo: {found} foto(s) encontradas, {not_found} sin resultado (usan respaldo ilustrado).")
    print(f"Sitio regenerado en {site_dir}/ ({pages_written} páginas).")


if __name__ == "__main__":
    main()
