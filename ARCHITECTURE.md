# Buenas Noticias — arquitectura técnica

Este documento explica **cómo** está construido el pipeline. El **qué y por qué** editorial está en `PROJECT_CONTEXT.md`. La cronología de cambios está en `CHANGELOG.md`.

## Regla de diseño rectora

**El trabajo pesado (generar/regenerar HTML, fusionar `site_data.json`) siempre corre dentro de un GitHub Action, nunca dentro de una sesión de Claude.** Una sesión de Claude (programada o manual) solo hace lecturas, decisiones de juicio (aprobar/objetar, criterio editorial) y escrituras pequeñas (un archivo JSON de unos pocos KB). Disparar el Action es una sola llamada barata; el Action hace el resto con red y cómputo propios, sin que ese contenido pase por el contexto de ningún modelo. Esto existe por el incidente de costo del 25-26 de sept de 2026 (ver `CHANGELOG.md`) — no es una preferencia de estilo, es la razón de ser de todo este diseño.

## Estructura del repositorio

```
scripts/
  build_site.py          # el generador del sitio (ver abajo)
  build_status_page.py   # regenera estado/index.html a partir de pipeline_log.json
.github/
  workflows/
    build-site.yml        # reconstruye el sitio (fusiona notas nuevas, poda, borra)
    attach-photos.yml      # busca fotos en Pexels para notas sin foto
  scripts/
    attach_photos.py       # lógica de attach-photos.yml
data/
  site_data.json          # el archivo histórico completo -- la fuente de verdad
  published_urls.json     # solo URLs, para que Fase A no repita historias
  pipeline_log.json       # bitácora mecánica de cada corrida (ver "Bitácora" abajo)
  pending/
    pendiente_<fecha>.json   # lote de notas nuevas aprobado, esperando publicarse
    eliminar_<fecha>.json    # lista de URLs a quitar del histórico (correcciones/pruebas)
assets/
  styles.css              # CSS compartido por todo el sitio (Fase 1, ver Changelog)
  icons.svg               # sprite de íconos SVG compartido (rediseño 2026-09-27)
  partials.js             # header/footer compartidos + comportamientos del sitio, inyectados en runtime (Fase 2, ver Changelog)
scripts/
  migrate_note_partials.py   # migración de una sola vez: backfill de Fase 2 en notas viejas (ver Changelog)
.github/workflows/
  migrate-note-partials.yml  # workflow de una sola vez para correr la migración de arriba
index.html, <categoria>/index.html, <categoria>/<slug>/index.html   # el sitio generado
estado/index.html         # panel de estado del pipeline, legible por humanos
```

## `scripts/build_site.py` — el generador

Se invoca como `python3 scripts/build_site.py --reescritos <archivo.json> [--eliminar <archivo.json>] --site-dir .`

Paso a paso:
1. Lee `data/site_data.json` (el histórico) y, si se pasó `--eliminar`, primero quita de ahí las notas cuya URL esté en ese archivo, **y borra del disco su página permalink** (`remove_articles()`). Sin este paso, una nota "eliminada" del listado seguiría teniendo su página huérfana viva para siempre, porque el paso 4 nunca regenera páginas de nota existentes.
2. Fusiona las notas de `--reescritos` con lo que quedó, evitando duplicados por URL (`merge_articles()`), asignando a cada nota nueva un `slug` permanente.
3. Poda del histórico las notas con más de `RETENTION_DAYS` (120 días) de antigüedad (`prune_old()`) — esto solo las saca de los listados; su página permalink, si ya existía, no se borra.
4. Regenera `index.html` y **todas** las páginas de categoría (su contenido cambia cada corrida). Para páginas de nota individual, **solo genera las que todavía no existen** — una nota publicada nunca se vuelve a tocar (política "Fase 3(b)", ver Changelog). Esto es lo que evita que agregar unas pocas notas obligue a reescribir cientos de páginas viejas. **Única excepción: `--rebuild-notes`** regenera también las notas ya publicadas; existe para cambios de plantilla que tienen que llegar a todas las notas (se usó para el rediseño 2026-09-27) y nunca va en la operación semanal.
   El `summary` de una nota puede traer varios párrafos separados por una línea en blanco (formato de la Fase 3 desde 2026-09-28): `parrafos()` los divide; la página de la nota los muestra todos y las tarjetas y `og:description` solo el primero.
5. Escribe (idéntico cada corrida) el CSS compartido en `assets/styles.css` (Fase 1, ver Changelog) y el sprite de íconos en `assets/icons.svg` — las páginas los referencian con `<link>` / `<use>`, no los repiten inline.
6. Escribe (idéntico cada corrida) el JS compartido de header/footer en `assets/partials.js` (`write_shared_partials()`, Fase 2, ver Changelog). `page_shell()` ya no emite `<header>`/`<footer>` inline: deja mount points vacíos (`id="site-header-mount"` / `id="site-footer-mount"`, con un `<noscript>` de respaldo) y este script los llena en tiempo de carga, usando rutas ancladas a `/` (el sitio vive en https://buenasnoticias.charlymx.com/ desde 2026-10-04) (no `base_prefix`, que es relativo y varía según la profundidad de la página -- este archivo es uno solo compartido por páginas a cualquier profundidad). Como el paso 4 nunca reescribe una página de nota ya publicada, este patrón solo aplica de forma nativa a páginas nuevas o regeneradas de aquí en más; ver más abajo el backfill que lo llevó también a las páginas viejas.
7. Guarda `data/site_data.json` y `data/published_urls.json` actualizados.

Es determinístico e idempotente: correrlo con `--reescritos` apuntando a `[]` sobre datos existentes simplemente re-renderiza home y categorías sin duplicar ni perder nada — es la forma segura de aplicar un cambio de plantilla/CSS a todo el sitio.

## `.github/workflows/build-site.yml` — el Action que publica

- **Disparo: SOLO `workflow_dispatch`** (manual, o programático vía `GITHUB_CREATE_A_WORKFLOW_DISPATCH_EVENT`). **A propósito NO tiene disparo automático por push** a `data/pending/pendiente_*.json` — Fase A sube ese archivo horas antes de que Charly tenga oportunidad de aprobar u objetar; si el Action se disparara con ese push, publicaría sin aprobación. La decisión de cuándo publicar es siempre de una sesión de Claude (Fase B, tras confirmar aprobación) o de un humano.
- Input opcional `rebuild_notes` (booleano, falso por defecto): pasa `--rebuild-notes` a `build_site.py`. Solo para publicar un cambio de plantilla; Fase B dispara sin inputs, así que no lo activa nunca.
- Al correr: detecta `data/pending/pendiente_*.json` (si existe, lo usa; si no, reconstrucción de mantenimiento con 0 notas nuevas) y `data/pending/eliminar_*.json` (si existe, lo pasa como `--eliminar`), corre `build_site.py`, actualiza `data/pipeline_log.json` y `estado/index.html`, borra los archivos de `pending/` ya procesados, y hace su propio commit como `buenas-noticias-build-bot`.
- **Último paso — dispara `attach-photos.yml` explícitamente si se agregaron notas nuevas.** Esto existe por una trampa real de GitHub: el `git push` de este mismo Action usa el `GITHUB_TOKEN` por defecto, y GitHub bloquea a propósito que un push hecho con ese token dispare otros workflows (protección anti-loop de la plataforma) — así que el trigger de push de `attach-photos.yml` nunca se activa solo desde aquí, aunque esté bien configurado. La solución es este paso final, que llama a la API (`gh workflow run attach-photos.yml`) directamente — eso sí funciona con `GITHUB_TOKEN`. Si algún día se quita este paso "para simplificar", las notas nuevas se van a quedar sin foto en silencio.
- Su propio commit **no** lleva `[skip ci]` a propósito (esa convención cancelaría también el intento de disparo de `attach-photos.yml` del paso siguiente, y en general cancela TODOS los workflows de ese push, no solo el propio).

## `.github/workflows/attach-photos.yml` — fotos

- Disparo: push a `data/site_data.json` (funciona normal si el push lo hace una sesión de Claude vía Composio, o un humano — solo falla el encadenamiento cuando el push lo hace `build-site.yml` con `GITHUB_TOKEN`, ver arriba) + `workflow_dispatch` manual.
- Busca en Pexels una foto para cada nota sin `image_url`, la agrega, regenera el HTML afectado, y hace commit como `github-actions[bot]` con `[skip ci]` (aquí sí es correcto: no hay ningún tercer workflow que dependa de este push).
- **Dependencia con Vigía Fase B:** el vigía detecta notas sin foto buscando la cadena literal "photo fallback" en el HTML (home, categoría y página de la nota). Por eso el respaldo ilustrado de `build_site.py` siempre lleva las clases `photo fallback` (en `card_html()` y `build_note_html()`); si una plantilla futura las quita, hay que actualizar también el prompt del vigía.
- Es asíncrono. Puede terminar "a medias" (datos de `image_url` completos pero no todo el HTML regenerado) — verificar esto explícitamente es parte del protocolo de la skill `buenas-noticias-intervencion-manual`.
- **Borrado de un solo uso para desbloquear la página de la nota.** `attach_photos.py` llama a `build_site()` para regenerar el sitio, pero esa función nunca reescribe una página de nota que ya existe (política Fase 3(b)) — y esa página *siempre* existe ya, porque `build_site.py` la creó (sin foto) en la corrida de publicación que corre justo antes. Sin más, la nota quedaría con foto en el home y su categoría, pero con el respaldo ilustrado para siempre en su propia página permalink (donde el lector realmente cae). Por eso, antes de llamar a `build_site()`, `attach_photos.py` borra del disco la página permalink de cada nota que consiguió foto en esa corrida — build_site() la detecta como "no existe" y la regenera, esta vez con foto. Como una nota solo pasa por este script una vez (queda marcada `image_attempted: true`), su página nunca se vuelve a borrar/regenerar después de esa primera vez -- sigue congelada de ahí en adelante, igual que cualquier otra. (Bug real encontrado y corregido el 2026-09-26 — ver `CHANGELOG.md`.)

## `scripts/migrate_note_partials.py` — backfill de una sola vez (no es parte del pipeline regular)

Script idempotente que existe fuera del ciclo normal de Fase A/B: aplica retroactivamente el patrón de header/footer de la Fase 2 (mount points + `assets/partials.js`) a páginas de nota que ya estaban congeladas antes de que existiera ese patrón. Detecta el HTML viejo por regex (`<header class="site-header">...</header>`, `<footer>...</footer>`), lo reemplaza por el nuevo, y dos guardas la hacen segura de re-correr: una página que ya tiene el patrón nuevo se deja intacta, y una página con forma inesperada se reporta sin tocarla. No forma parte de `build_site.py` ni corre en cada publicación -- es una herramienta de una sola vez para una migración puntual ya ejecutada (ver `CHANGELOG.md`).

Se dispara con `.github/workflows/migrate-note-partials.yml`, un workflow `workflow_dispatch`-only que replica la estructura de `build-site.yml` (corre el script, registra el resultado en `data/pipeline_log.json` con trigger `migracion-partials`, regenera `estado/index.html`, hace commit como `buenas-noticias-build-bot`). Si el patrón de header/footer vuelve a cambiar en el futuro, este script es la plantilla a seguir para otro backfill puntual -- no para dejarlo corriendo de forma recurrente.

## Bitácora — `data/pipeline_log.json` y `estado/index.html`

Cada corrida (de cualquier trigger, o del propio Action) agrega un registro `{timestamp_utc, trigger, status, summary}` a `data/pipeline_log.json`. `trigger` toma valores como `fase_a`, `vigia_fase_a`, `fase_b`, `vigia_fase_b`, `build-site-action`. `scripts/build_status_page.py` lo convierte en `estado/index.html`, un panel legible por humanos. Esta bitácora es un registro mecánico adicional — no sustituye los correos de confirmación/diagnóstico que cada fase le manda a Charly.

## Identidades de commit en el repo

- `buenas-noticias-build-bot` — commits de `build-site.yml`.
- `github-actions[bot]` — commits de `attach-photos.yml`.
- El nombre de usuario de Charly (`CharlyMX` u otro) — commits hechos directamente por una sesión de Claude vía Composio (subir un pendiente, una corrección puntual).

## Disciplina de documentación (aplica a cualquier cambio estructural, programado o manual)

Un cambio estructural al pipeline o al sitio -- una fase nueva o modificada, un fix de arquitectura, una migración retroactiva, un workflow nuevo o modificado -- no se da por terminado solo porque el commit funciona. Se da por terminado cuando, además:

1. `CHANGELOG.md` tiene una entrada nueva y fechada describiendo qué cambió y por qué. Esto es siempre, sin excepción.
2. `ARCHITECTURE.md` queda al día si el cambio afecta el cómo -- un paso nuevo en `build_site.py`, un archivo nuevo en la estructura del repo, un workflow nuevo o su lógica.
3. `PROJECT_CONTEXT.md` queda al día si el cambio afecta el qué/por qué editorial, las fases programadas, o los triggers.

Si una entrada de Changelog anterior describe un comportamiento que un cambio posterior vuelve obsoleto (por ejemplo, "esto no es retroactivo" y luego sí se vuelve retroactivo por una migración), esa entrada se corrige o se referencia explícitamente desde la nueva -- nunca se deja una afirmación desactualizada sin marcar como tal.

Esta regla nace de un vacío real: la Fase 2 (header/footer, ver Changelog 2026-09-26) documentó bien su implementación inicial, pero nadie actualizó esa entrada cuando el backfill retroactivo la volvió obsoleta unas horas después, y este mismo documento nunca llegó a mencionar `assets/partials.js` en absoluto pese a documentar la Fase 1 paso a paso. Charly detectó ambos vacíos el mismo día y se corrigieron de inmediato. La skill `buenas-noticias-intervencion-manual` (Regla 3) aplica esta misma disciplina para intervenciones manuales en chat.

## Disciplina de escritura (aplica a cualquier sesión, programada o manual)

- Todo commit al repo pasa por Composio (`GITHUB_COMMIT_MULTIPLE_FILES`, argumentos `message` + `upserts`/`deletes`) — `git push` directo está bloqueado en el sandbox.
- Validar el JSON localmente antes de subirlo. Calcular el sha1 de blob esperado (`sha1(f"blob {len(data)}\0".encode() + data)`) y compararlo contra lo que devuelve GitHub después del commit — no dar un commit por bueno solo porque la herramienta respondió éxito.
- Nunca hacer una llamada de "prueba" con contenido de relleno contra una ruta real del repo — es el origen exacto del incidente de costo. Probar formatos de llamada contra un archivo de scratch local.
- Una sola espera fija (30-60s) y una sola revisión de estado de un Action disparado — nunca reintentar en bucle.
