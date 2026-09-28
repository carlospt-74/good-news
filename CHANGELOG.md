# Buenas Noticias — changelog

Cronología de cambios estructurales al pipeline y al sitio (no de las publicaciones semanales normales — esas quedan en `data/pipeline_log.json` y en `estado/index.html`). Cada vez que se haga un cambio de este tipo, se agrega una entrada aquí.

## 2026-09-25/26 — Incidente de costo y causa raíz

El 25 de septiembre, la publicación semanal (Fase B) se interrumpió a medias: un plan de 16 pasos nunca llegó a completarse y a las 18:25 UTC arrancó una secuencia nueva mucho más larga, sin correo de confirmación ni de fallo (detectado por Vigía Fase B, registro `status: warning`). El 26 de septiembre, al retomarlo manualmente, publicar ~10 notas — generando y transmitiendo el HTML completo del sitio a través del chat hacia GitHub — consumió aproximadamente el doble del presupuesto de tokens de una sesión PRO completa.

**Causa raíz:** el diseño de esa fecha corría `build_site.py` *dentro* de la sesión de Claude y luego subía el HTML generado a GitHub a través del chat — cientos de KB de contenido pasando por el contexto del modelo en cada publicación. Esto llevó a un rediseño completo del pipeline de publicación (ver entradas de abajo, todas del mismo día como respuesta directa).

## 2026-09-26 — Fase 1: CSS compartido

`build_site.py` ya no embebe el CSS completo (`<style>`) en cada página generada. Ahora lo escribe una sola vez en `assets/styles.css` (`write_shared_assets()`) y cada página lo referencia con `<link>`. Reduce el peso de cada página generada y evita que agregar notas nuevas implique repetir el mismo bloque de CSS cientos de veces.

## 2026-09-26 — Fase 3(b): páginas de nota congeladas

Antes, cada corrida de `build_site.py` reescribía TODAS las páginas de nota de una categoría cada vez que entraba una nota nueva, solo para refrescar su carrusel de "Más de \<categoría\>" — convirtiendo "agregar 10 notas" en "tocar ~90 páginas". Desde este cambio, una página de nota, una vez publicada, nunca se vuelve a tocar. El home y las páginas de categoría sí se regeneran siempre (su contenido cambia cada semana por diseño). Costo aceptado: el carrusel de relacionadas de una nota vieja puede quedar desactualizado con el tiempo.

## 2026-09-26 — Fase 4: publicación vía GitHub Action

Se crea `.github/workflows/build-site.yml`: ahora una sesión de Claude (Fase B) solo sube un lote pequeño (`data/pending/pendiente_<fecha>.json`, unos KB) y dispara el Action por API — el Action hace la fusión, la regeneración de HTML y el commit, enteramente del lado de GitHub, sin que ese contenido pase por el contexto de ningún modelo.

**Bug crítico encontrado y corregido antes de llegar a producción:** el diseño inicial disparaba el Action automáticamente por push a `data/pending/pendiente_*.json` — pero Fase A sube ese archivo horas antes de que Charly tenga oportunidad de aprobar. Con ese diseño, el siguiente viernes se habría publicado el borrador sin esperar aprobación. Corregido de inmediato: el Action solo se dispara por `workflow_dispatch` (manual o disparado explícitamente por Fase B tras confirmar la aprobación), nunca por push.

Se reescribieron los prompts de los triggers Fase B y Vigía Fase B, y la skill `buenas-noticias-publicar`, para reflejar el nuevo flujo.

## 2026-09-26 — `--eliminar`: quitar notas sin editar `site_data.json` a mano

Al probar el flujo nuevo con notas de prueba, quitarlas después reveló que no existía forma barata de remover notas del histórico — la única opción era descargar `site_data.json` completo (~135 KB), editarlo, y volver a subirlo, con un costo de tokens desproporcionado (más caro que publicar). Se agregó a `build_site.py` la opción `--eliminar <archivo.json>` (lista de URLs a quitar), que además borra del disco la página permalink correspondiente (`remove_articles()`), y se integró a `build-site.yml` (detecta `data/pending/eliminar_*.json`). Ahora una corrección o limpieza cuesta lo mismo que una publicación normal.

## 2026-09-26 — Fix: `attach-photos.yml` dejó de dispararse solo

Al validar el flujo nuevo de punta a punta con notas reales, se detectó que ninguna nota nueva recibía foto. Causa: el `git push` de `build-site.yml` usa el `GITHUB_TOKEN` por defecto del Action, y GitHub bloquea a propósito que un push hecho con ese token dispare otros workflows (protección anti-loop de la plataforma) — el trigger de push de `attach-photos.yml` estaba bien configurado, pero nunca se activaba desde ahí. Corregido agregando un paso final a `build-site.yml` que dispara `attach-photos.yml` explícitamente por API cuando se agregaron notas nuevas (requirió agregar permiso `actions: write` al workflow).

## 2026-09-26 — Fix: la página de cada nota nunca mostraba su foto

Al hacer una prueba controlada para confirmar el fix anterior (disparo automático de `attach-photos.yml`), se verificó explícitamente la página propia de la nota de prueba -- no solo el home y la categoría, como hacía hasta ahora la verificación de Vigía Fase B -- y se encontró que mostraba el respaldo ilustrado aunque `site_data.json` ya tenía su `image_url` real. Se confirmó que el mismo patrón afecta a notas reales publicadas antes (ej. la nota del hantavirus de Chile), así que no es exclusivo de la prueba.

**Causa:** `attach_photos.py` regenera el sitio llamando a `build_site()`, la misma función que nunca reescribe una página de nota que ya existe (política Fase 3(b)). Como `build_site.py` ya creó esa página (sin foto) en la corrida de publicación previa, `attach_photos.py` nunca lograba escribirle la foto -- sin importar cuántas veces corriera.

**Corregido:** `attach_photos.py` ahora borra del disco la página permalink de cada nota que consigue foto en esa corrida, justo antes de llamar a `build_site()`, para que la regenere una vez con la foto ya incluida. Validado localmente (con una llamada a Pexels simulada) antes de subirlo: la página de nota pasa de mostrar el respaldo ilustrado a mostrar la foto real en la primera corrida, y una segunda corrida no la vuelve a tocar (se preserva la política de congelamiento).

También se amplió el paso de verificación de fotos de Vigía Fase B (antes solo revisaba el home y la página de categoría) para que también revise la página propia de cada nota nueva.

**Backfill retroactivo (resuelto el mismo día, con aprobación explícita de Charly):** se escaneraron las 103 notas publicadas comparando su `image_url` en `site_data.json` contra el contenido real de su página propia, y se encontraron 13 notas afectadas por este mismo bug (páginas con `class="note-photo fallback"` pese a tener foto real guardada). El intento de borrarlas en un solo commit por API (`GITHUB_COMMIT_MULTIPLE_FILES` con `deletes`) fue bloqueado por el clasificador de seguridad de la sesión de Claude ("Modify Shared Resources") por tratarse de un borrado en lote contra el repo en vivo -- ese bloqueo se mantuvo incluso con confirmación explícita de Charly en el chat, así que no se intentó sortear. Charly borró las 13 páginas a mano desde la interfaz de GitHub (usando las URLs `/delete/main/<ruta>` de cada archivo), y desde la sesión de Claude solo se disparó `build-site.yml` para regenerarlas. Verificado en el sitio público (no solo en la fuente): las 13 páginas muestran ahora su foto real, y el conteo de notas se mantuvo en 103. Lección para el futuro: un borrado de varios archivos de página contra este repo probablemente requiera hacerse a mano o por otra vía, no por API de Composio en un solo commit por lote.

## 2026-09-26 — Bitácora: `pipeline_log.json` no registra reconstrucciones de solo mantenimiento

Al verificar el backfill de arriba, se notó que la corrida de `build-site.yml` que regeneró las 13 páginas no agregó una entrada nueva a `data/pipeline_log.json` (se confirmó consultando el archivo directamente en el commit exacto de esa corrida, no una copia en caché). Causa: el paso de bitácora del workflow solo escribía un registro cuando detectaba un archivo `data/pending/pendiente_*.json` o `data/pending/eliminar_*.json` -- una reconstrucción disparada sin ninguno de los dos (como ese backfill, hecho borrando páginas a mano) corría y funcionaba bien, pero quedaba invisible en la bitácora mecánica y en `estado/index.html`.

**Corregido:** se le quitó la condición a los pasos "Registrar en la bitácora del pipeline" y "Regenerar la página de estado" de `build-site.yml`, para que corran siempre que el build tenga éxito, no solo cuando hay `pendiente` o `eliminar`. Validado con una corrida real de mantenimiento (sin ningún archivo pendiente): `data/pipeline_log.json` pasó de 20 a 21 entradas, con el registro "0 notas nuevas agregadas. Total vigente: 103 notas en 8 categorías", y `estado/index.html` también quedó al día. Efecto colateral esperado y aceptado: ahora cada corrida deja al menos el commit de la bitácora y de `estado/index.html`, aunque no haya notas nuevas ni eliminadas.

## 2026-09-26 — Documentación de arquitectura

Se agregan `PROJECT_CONTEXT.md`, `ARCHITECTURE.md` y este `CHANGELOG.md` al repo, para que cualquier sesión futura (o Charly) pueda orientarse sin tener que reconstruir el contexto desde una conversación larga o desde comentarios de código dispersos.

## 2026-09-26 — Fase 2: header y footer unificados vía `assets/partials.js`

Se retomó la Fase 2 que había quedado pausada (ver más abajo, sección "Pendiente"). A diferencia del CSS (Fase 1), HTML no tiene un mecanismo nativo de "un solo archivo compartido" sin JavaScript, así que la implementación es distinta: `page_shell()` ahora deja un `<header id="site-header-mount">` y un `<footer id="site-footer-mount">` vacíos (con un `<noscript>` de respaldo: un link a inicio), más un `<script defer src="assets/partials.js">`. Ese script, escrito una sola vez por `write_shared_partials()` (mismo patrón que `write_shared_assets()` para el CSS), inyecta el header y el footer completos al cargar la página, usando rutas absolutas ancladas a `/good-news/` (a diferencia de `base_prefix`, que es relativo y varía según la profundidad de cada página, este archivo es uno solo compartido por páginas a cualquier profundidad).

Esto sí resuelve el "nav drift" real: como todas las páginas que este script regenera o crea de aquí en más (home, categorías, notas nuevas) cargan el mismo `assets/partials.js`, si el menú de categorías cambia en el futuro, hasta la nota más nueva lo reflejará sin que nadie tenga que tocar su HTML individualmente. Costo aceptado, consistente con la decisión original: el menú ahora depende de JavaScript — lectores con JS desactivado o crawlers que no lo ejecuten solo ven el `<noscript>` de respaldo en vez del menú completo.

Importante: esto NO es retroactivo. Las 103 notas publicadas antes de este cambio siguen congeladas (política Fase 3(b)) con su header y footer viejos, inlineados en su propio HTML -- mismo "costo aceptado" que ya existía para el carrusel de relacionadas de una nota vieja. Solo las páginas que `build_site.py` sí regenera o crea de aquí en más usan el `<script>` nuevo. **Actualización del mismo día: esto se volvió retroactivo unas horas después mediante un backfill puntual aprobado por Charly -- ver la entrada "Backfill retroactivo de Fase 2" más abajo.**

Validado antes de tocar el repo real: el script parcheado se corrió contra datos sintéticos en un directorio de prueba aislado (nunca contra `site_data.json` real), se verificó que `assets/partials.js` resultante pasara `node --check`, y se simuló su ejecución con un `document` de prueba en Node para confirmar que el HTML inyectado (header, footer, resaltado de categoría activa) es idéntico en estructura al que generaba el código viejo. Ya en el repo: se disparó `build-site.yml` por `workflow_dispatch` y se verificó en el sitio público (no solo en la fuente) que home y `/deportes/` ya muestran el header/footer nuevo con `id="site-header-mount"`/`id="site-footer-mount"` y cargan `assets/partials.js` (sintaxis válida también en la copia servida), mientras que una nota vieja (`/deportes/corredora-puertorriquena-gana-medalla-historica-y-conoce-en-persona-a/`) conserva su `<header class="site-header">` y `<footer>` inline de siempre, sin cambios. El conteo se mantuvo en 103 notas / 8 categorías y `pipeline_log.json` registró la corrida automáticamente (fix de la sección anterior funcionando).

## 2026-09-26 — Backfill retroactivo de Fase 2: header/footer en las 103 notas viejas

Charly preguntó si las notas viejas alguna vez recibirían el header/footer nuevo de la Fase 2. La respuesta por diseño era no (política Fase 3(b), páginas congeladas). Pidió el plan y el costo de migrarlas de todos modos, lo aprobó, y se ejecutó ese mismo día.

Se creó `scripts/migrate_note_partials.py`: script idempotente de un solo uso que busca en cada página de nota el patrón viejo (`<header class="site-header">...</header>` / `<footer>...</footer>` inline, vía regex) y lo reemplaza por los mount points + `<script defer src="assets/partials.js">` de la Fase 2. Si una página ya tiene el patrón nuevo, la deja intacta (así se puede correr más de una vez sin riesgo); si una página tiene una forma inesperada, la reporta y no la toca. Se agregó `.github/workflows/migrate-note-partials.yml` (un workflow de una sola vez, `workflow_dispatch` únicamente, mismo patrón que `build-site.yml`: corre el script, registra el resultado en `data/pipeline_log.json` con trigger `migracion-partials`, regenera `estado/index.html`, y hace commit como `buenas-noticias-build-bot`).

Validado antes de tocar el repo real: corrida contra datos sintéticos en un directorio aislado, y un dry-run completo contra un clon local de las 103 notas reales del repo (diff uniforme de 25 líneas por archivo, cero fallos) antes de disparar el workflow de verdad.

Resultado de la corrida real (`workflow_dispatch`, 2026-09-26 22:29 UTC): 103/103 notas migradas, 0 ya estaban al día, 0 archivos no encontrados, 0 con forma inesperada. `data/site_data.json`, `data/published_urls.json` y `assets/partials.js` quedaron sin tocar (confirmado comparando el sha de blob antes y después vía la API de GitHub, no una copia en caché). Verificación posterior: conteo de categorías correcto (suma 103 en 8 categorías), título y resumen preservados en una muestra de las 103 páginas, y spot-check en vivo de 4 categorías no muestreadas antes (Economía, IA, Cultura, Sociedad) -- las 4 con HTTP 200 y los 5 marcadores esperados (mount points, script, categoría activa, título).

Con esto, la afirmación "esto NO es retroactivo" de la entrada de Fase 2 de arriba ya no aplica desde este commit: las 103 notas publicadas hasta ese momento tienen el mismo header/footer compartido que las páginas nuevas.

## 2026-09-26 — Regla nueva: disciplina de documentación obligatoria

Charly notó, al revisar el trabajo de Fase 2 y su backfill, dos vacíos: la entrada de Fase 2 de este Changelog decía "esto NO es retroactivo" y nadie la corrigió cuando el backfill la volvió obsoleta unas horas después; y `ARCHITECTURE.md` nunca llegó a mencionar `assets/partials.js`, `write_shared_partials()` ni el patrón de mount points, pese a documentar la Fase 1 (CSS) paso a paso.

Ambos vacíos se corrigieron el mismo día que se detectaron (ver entradas de arriba y la sección nueva "Disciplina de documentación" en `ARCHITECTURE.md`), y se estableció una regla permanente para que no se repita: todo cambio estructural al pipeline o al sitio (una fase nueva, un fix de arquitectura, una migración retroactiva, un workflow nuevo) no se da por terminado solo porque el commit funciona -- se da por terminado cuando además `CHANGELOG.md` tiene su entrada fechada (siempre), `ARCHITECTURE.md` queda al día si cambió el cómo, y `PROJECT_CONTEXT.md` queda al día si cambió el qué/por qué editorial o las fases programadas. Esta regla vive ahora en `ARCHITECTURE.md` (sección "Disciplina de documentación") y en la skill `buenas-noticias-intervencion-manual` (Regla 3), para que cualquier sesión futura -- programada o manual -- la vea antes de dar un cambio por terminado.

## 2026-09-27 — Rediseño del hero del home y regla de estilo: nunca guión largo en texto generado

Charly pidió mejorar el bloque de bienvenida (hero) del home: centrarlo, darle más aire, y agregar un párrafo que explique la propuesta del portal a alguien que llega cansado de noticias estresantes. Se implementó en `build_home_html()`: el `.hero-text` ahora está centrado con fondo suave y bordes redondeados (antes iba pegado a la izquierda, sin separación visual del feed), se agregó un párrafo `.hero-intro` nuevo con el mensaje de bienvenida, y una fila `.hero-badges` con tres sellos de confianza (fuentes verificadas, cero ruido político, conteo de notas/categorías). El mecanismo de generación (page_shell, write_shared_partials, la política de páginas de nota congeladas) no cambió -- es un cambio de contenido/CSS dentro de build_home_html(), no de arquitectura.

En la misma conversación, Charly señaló que el guión largo ("--" en el teclado, el carácter unicode em dash) es una señal reconocible de texto generado por IA y pidió no usarlo nunca en texto que ve el lector -- ni en el copy nuevo del hero ni en los titulares/resúmenes que redacta la Fase 3. Se verificó que el copy nuevo del hero no lo usa, y se encontró que 1 de las 103 notas ya publicadas sí lo tiene (nota de diseñadoras guna/emberá/ngäbe en Panamá, sin corregir por ahora -- Charly no pidió ese backfill retroactivo, solo la regla hacia adelante). **Actualización: corregida el mismo día, con aprobación de Charly; ver la entrada "Ajustes posteriores al rediseño" más abajo.** Se agregó la regla explícita a la skill `buenas-noticias-reescribir` (ver ese archivo) para que la Fase 3 la aplique en cada corrida futura.

## 2026-09-27 -- Rediseño completo del sitio (home, categorías y notas)

Charly aprobó un rediseño visual completo, iterado primero como maquetas HTML fuera del repo (sistema de diseño generado con la skill ui-ux-pro-max). Cambia solo la capa de presentación de `build_site.py`; la lógica de datos (fusión, poda, slugs, `--eliminar`, política Fase 3(b)) no cambió.

- **Sistema visual:** fondo crema, verde bosque como color principal y ámbar como acento; titulares en Newsreader, texto en Public Sans; modo oscuro automático con botón para cambiarlo (se recuerda por visitante). Íconos SVG en `assets/icons.svg` (sprite nuevo, escrito por `write_shared_assets()`) en lugar de los emojis por categoría; se quitaron `CATEGORY_COLORS`, `CATEGORY_LIGHT` y `CATEGORY_EMOJI` y se agregaron `CATEGORY_ICONS` y `CATEGORY_DESC`.
- **Logo:** el PNG anterior se veía pixeleado (sobre todo en modo oscuro), así que el logo ahora es texto: "buenas noticias" en Caveat Brush (la misma letra del logo original) con un punto ámbar, y "Always positive" debajo. `assets/logo.png` se conserva pero ya no se usa en el header ni en el footer.
- **Home:** hero compacto con titular de dos renglones (palabra que rota), "Lo mejor de hoy" (las 3 destacadas en bento), "Explora por tema" (pestañas por categoría, sin repetir las destacadas) y franja de confianza.
- **Categoría:** encabezado con ícono y frase, chips para saltar entre categorías, nota más reciente destacada y cuadrícula del resto.
- **Nota:** encabezado centrado, foto a todo el ancho, resumen en columna de lectura con barra lateral (recuadro de la fuente + compartir por WhatsApp o copiar enlace) y "Más de <categoría>". Etiquetas `og:` y `description` en todas las páginas, para que una nota compartida por WhatsApp o redes muestre foto y resumen.
- **Footer:** centrado, con el aviso editorial redactado por Charly.
- `assets/partials.js` ahora también lleva los comportamientos compartidos (tema, menú móvil, pestañas del home, copiar enlace), cada uno activo solo si su elemento existe en la página.

**Notas ya publicadas:** como todas las páginas comparten `assets/styles.css`, las 103 notas congeladas habrían recibido el CSS nuevo con su HTML viejo. Para evitarlo se agregó a `build_site.py` el flag `--rebuild-notes` (y el input booleano `rebuild_notes` a `build-site.yml`, falso por defecto) que regenera también las notas ya publicadas; se usa una sola vez, en la misma corrida que publica el rediseño. Sin el flag, la política Fase 3(b) sigue igual (validado: una corrida normal escribe solo home + 9 categorías). Fase B dispara el workflow sin inputs, así que su comportamiento no cambia.

Validado antes de subir: el sitio completo (113 páginas: home, 9 categorías, 103 notas) se generó con los datos reales en una copia temporal fuera del repo y se revisó en el navegador (sin imágenes rotas ni errores de consola, `partials.js` pasa `node --check`, `attach_photos.py` sigue importando `build_site` sin cambios).

**Publicado el mismo día (PR #1):** Charly hizo el merge y corrió `build-site.yml` con `rebuild_notes` marcado (corrida #14, `success`). El commit del bot (`51a1691`) regeneró las 103 notas, el home, las 9 categorías y `estado/index.html`, y escribió `styles.css`, `partials.js` e `icons.svg`; `data/site_data.json` no cambió. Verificado en el sitio público (no solo en la fuente): home y las 9 categorías con la plantilla nueva, las categorías enlazan exactamente 103 notas (ninguna huérfana ni perdida), y las 103 páginas de nota revisadas una por una tienen la plantilla nueva y su foto.

## 2026-09-27 -- Ajustes posteriores al rediseño: Vigía Fase B y guion largo

- **Compatibilidad con Vigía Fase B.** Su paso 2b detecta notas sin foto buscando la cadena literal "photo fallback", que era la clase del respaldo ilustrado del diseño anterior. La plantilla nueva usaba otras clases (`media fallback`, `cover-fallback`), así que el vigía habría dado "ok" aunque una nota nueva se quedara sin foto. En vez de modificar el prompt del trigger, `card_html()` y `build_note_html()` ahora agregan la clase `photo` a su respaldo (`media photo fallback`, `cover-fallback photo fallback`), con un comentario en el código para que nadie la quite. Se revisaron los prompts de los otros tres triggers (Fase A, Vigía Fase A, Fase B): ninguno depende del HTML del sitio. Validado con una simulación de viernes en una copia aislada: una nota nueva sin foto sale con la plantilla nueva y con el marcador; tras simular `attach_photos.py` (borrar su página y reconstruir) sale con su foto y sin el marcador; y la corrida normal escribe solo home + 9 categorías + la nota nueva.
- **Guion largo corregido.** La nota de diseñadoras guna, emberá y ngäbe (ver la entrada del rediseño del hero, más arriba en este mismo día) tenía dos guiones largos en su resumen ("el diseño textil —como la tradicional mola— se convirtió"). Charly aprobó corregirla: se cambiaron por comas en `data/site_data.json` (única nota con guion largo en el histórico). Con el rediseño, esa nota aparecía también en el "Más de Sociedad" de otras 3 notas, así que la corrección se publica con otra corrida de `build-site.yml` con `rebuild_notes`, que regenera las 4 páginas.

## 2026-09-27 -- Fix: las pestañas de "Explora por tema" no filtraban

Charly notó que al elegir una categoría en "Explora por tema" (home) la cuadrícula no cambiaba. Causa: el JavaScript sí marcaba las tarjetas con el atributo `hidden`, pero la regla `.card{display:flex}` del CSS nuevo le ganaba al `display:none` que el navegador aplica a `[hidden]`, así que las 48 tarjetas seguían visibles (también en "Todas", que debía mostrar 12, y el botón "Ver todas" aparecía aunque debía estar oculto). No se detectó en la revisión local porque ahí no se probaron las pestañas en el sitio generado. Corregido con una regla `[hidden]{display:none!important}` en `shared_css()`. Validado en una copia aislada: al cargar se ven 12 tarjetas y el botón oculto; cada categoría muestra solo sus 6 notas más recientes y el botón "Ver todas las de <categoría>" con el enlace correcto; al volver a "Todas", 12 tarjetas y botón oculto. Como el cambio es solo de `assets/styles.css`, basta una corrida normal de `build-site.yml` (sin `rebuild_notes`) para publicarlo.

(De paso se quitó un encabezado "Pendiente" duplicado por error en la entrada anterior.)

## 2026-09-28 -- Resúmenes más completos: 2 a 3 párrafos (solo notas nuevas)

Charly notó que los resúmenes eran muy cortos frente a la nota original. Ejemplo medido: la nota de los yaguaretés de Corrientes (El Monterizo) tiene ~550 palabras en 6 párrafos y su resumen tenía 88 palabras en un párrafo (16%); los 103 resúmenes publicados miden entre 51 y 111 palabras (mediana 79). Causa: la skill `buenas-noticias-reescribir` pedía 2 a 4 oraciones y redactaba a partir del título y el extracto de la búsqueda, sin leer la nota completa. Además, ese resumen incluía un dato ("desde 2012") que no aparece en la nota enlazada.

Charly pidió llegar al 50-60% del original; se acordó un tope menor para no debilitar el criterio de "no reemplazar a la nota original" en el que se apoya el portal (ver `PROJECT_CONTEXT.md`): **2 a 3 párrafos, 150-250 palabras, máximo 35-40% del original**, solo para notas nuevas (las 103 publicadas se quedan como están).

- **Skill `buenas-noticias-reescribir`** (nueva versión, la guarda Charly en claude.ai): lee la nota completa solo de las notas ya aprobadas (reutiliza lo que haya traído la verificación en la misma sesión; si no, un `web_fetch_exa` con tope de ~12,000 caracteres), respeta la extensión y el tope, usa solo hechos de la nota enlazada, y separa los párrafos con una línea en blanco en `summary`. Si no puede leer la nota completa, escribe un solo párrafo con lo verificable y lo avisa en el correo de revisión. Las fases de búsqueda y verificación no cambian.
- **`build_site.py`**: nueva función `parrafos()`; la página de la nota muestra cada párrafo aparte, y la tarjeta y `og:description` usan solo el primero. Validado en una copia aislada: las 113 páginas actuales salen idénticas byte por byte, y una nota de prueba de 3 párrafos se muestra con sus 3 párrafos en su página y con solo el primero en la tarjeta del home y en `og:description`.

## Pendiente / considerado y pausado

Nada pendiente por ahora.
