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

**Pendiente, sin resolver todavía:** este bug probablemente afectó a todas las notas publicadas desde que existe la política de páginas congeladas (Fase 3(b), 2026-09-26) -- es decir, potencialmente también a notas de semanas anteriores a esa fecha si alguna vez se combinó con este flujo. No se hizo un backfill retroactivo para corregir páginas de notas ya publicadas que quedaron con el respaldo ilustrado pese a tener foto real en los datos -- se dejó fuera de esta corrección porque es una operación de alcance distinto (revisar todo el histórico) que requiere decisión explícita de Charly antes de tocar contenido ya publicado.

## 2026-09-26 — Documentación de arquitectura

Se agregan `PROJECT_CONTEXT.md`, `ARCHITECTURE.md` y este `CHANGELOG.md` al repo, para que cualquier sesión futura (o Charly) pueda orientarse sin tener que reconstruir el contexto desde una conversación larga o desde comentarios de código dispersos.

## Pendiente / considerado y pausado

- **Fase 2 (header/footer unificados):** se analizó unificar el header y footer del sitio en un solo lugar (como ya se hizo con el CSS en Fase 1). El ahorro remanente resultó pequeño (~10% de una página) una vez que Fase 1 ya capturó lo grueso; la justificación real sería evitar "nav drift" en páginas de nota congeladas, un riesgo de bajo impacto y cosmético. Pausado a pedido de Charly, sin descartarse para el futuro.
