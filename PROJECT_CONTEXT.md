# Buenas Noticias — contexto del proyecto

**Qué es:** un portal de noticias 100% positivas en español, para audiencia de todo el continente americano (EE. UU., Canadá y Latinoamérica). Sitio estático publicado en GitHub Pages: https://buenasnoticias.charlymx.com/ — repositorio `carlospt-74/good-news`.

**Para quién:** lectores que quieren enterarse de logros, avances y buenas noticias reales, verificadas, sin ruido político ni sensacionalismo. El dueño del proyecto es Charly (carlos.perezt@gmail.com).

**Cómo se sostiene la confianza del portal** (no negociable — esto es el criterio editorial, no una preferencia de estilo):

- Cada nota es genuinamente positiva, no solo neutral. Un logro real, un avance verificable, una cifra que mejora — no una nota "no mala".
- Fuente creíble: medios de noticias reales, con autoría identificable. Nunca blogs anónimos ni contenido sin verificar.
- El hecho es verificable, no una promesa a futuro ni un rumor.
- Si la única fuente de un dato es la parte interesada (una empresa hablando de su propio producto, un gobierno de sus propios resultados), se marca `fuente_unica_interesada: true` y se atribuye explícitamente en el texto — nunca se presenta como hecho neutral verificado de forma independiente.
- **Cero tinte político**, sin excepción: se rechaza cualquier nota centrada en un gobierno, funcionario electo o partido presentando sus propios logros o cifras de gestión, aunque el contenido sea positivo y los datos sean ciertos. El motivo no es dudar de la cifra — es que ese encuadre hace parecer que el portal respalda a ese gobierno en particular. Aplica igual a cualquier país y cualquier signo político. Esto no excluye el contenido personal, de salud, religioso o caritativo del Papa o del Vaticano (desde 2026-10-16): aunque el Vaticano es técnicamente un Estado, esta regla protege contra el *encuadre político* de un gobierno presumiendo sus logros, no contra la cobertura pastoral/humana del líder de una religión -- sí sigue aplicando de lleno a diplomacia o geopolítica vaticana propiamente dicha.
- Notas de la categoría IA solo califican si hay un beneficio humano directo y verificable (diagnóstico médico, accesibilidad, un problema concreto resuelto) — nunca lanzamientos de producto, rondas de inversión, ni "IA hace X más rápido" sin ese beneficio central.
- Cada nota se redacta en palabras propias (nunca copiando frases del original) y siempre enlaza a la fuente — el portal no aloja el contenido completo, dirige tráfico de vuelta al medio original. Esto es lo que mantiene al proyecto del lado seguro de "fair use".
- Extensión del resumen (desde 2026-09-28, solo para notas nuevas): 2 a 3 párrafos, entre 150 y 250 palabras y nunca más del 35-40% del texto original, redactados a partir de la nota completa y solo con hechos que aparecen en ella. Las citas textuales y los detalles finos se dejan para el medio original, para que el resumen no lo reemplace. Las notas publicadas antes de esa fecha conservan su resumen corto de un párrafo.

**Categorías:** Deportes, Economía, Ciencia y Salud, Medio Ambiente, Sociedad, Tecnología, Cultura, IA, Otros.

**Región de búsqueda (desde donde se toman las notas):** medios establecidos de Estados Unidos, Canadá y Latinoamérica. Esta restricción es sobre el *medio/portal* que publica, no sobre de qué país o región habla la noticia -- un medio americano que cubre al Vaticano, a Europa o a cualquier otra región del mundo sigue calificando sin problema (aclarado el 2026-10-16 tras una ambigüedad real en la redacción original de esta regla).

**El pipeline, en una frase por fase** (el detalle técnico de cómo está construido cada fase va en `ARCHITECTURE.md`):

1. **Fase A — Búsqueda, verificación y reescritura** (skills `buenas-noticias-buscar` → `buenas-noticias-verificar` → `buenas-noticias-reescribir`): cada viernes encuentra al menos 12 noticias nuevas de la semana (de las cuales 2 a 3 deben ser temas católicos/del Vaticano/del Papa, usando las categorías existentes -- normalmente Sociedad o Cultura -- y no una categoría dedicada; criterio vigente desde 2026-10-16), aplica el criterio editorial de arriba, las reescribe originales, y las sube como borrador (`data/pending/pendiente_<fecha>.json`) junto con un correo a Charly pidiendo revisión.
2. **Fase B — Aprobación y publicación** (skill `buenas-noticias-publicar`): unas horas después, revisa si Charly objetó algo por correo, y si no, dispara la publicación real.
3. **Los "Vigías"** (Vigía Fase A, Vigía Fase B): corren poco después de cada fase para confirmar que sí produjo lo esperado, y avisan a Charly por correo si algo se quedó a medias sin que nadie se entere.

**Las 4 tareas programadas** (IDs de trigger, para referencia rápida — el prompt completo de cada una vive en la propia tarea, no aquí):
- `trig_01M5rAiFf2bLou3P5PRTCiLv` — Fase A (viernes 12:00 UTC)
- `trig_01FYDNyMihxFmNZTfdfBSEMN` — Vigía Fase A (viernes 12:45 UTC)
- `trig_019YUyZyGdcfWDqSNitUysAV` — Fase B (viernes 17:00 UTC)
- `trig_01NTYtttd4ELTtTeHjKr2RkU` — Vigía Fase B (viernes 18:15 UTC)

**Un principio operativo que gobierna todo lo demás:** el 25-26 de septiembre de 2026 hubo un incidente de costo serio (publicar ~10 notas, transcribiendo HTML generado a mano por el chat hacia GitHub, consumió como el doble del presupuesto de tokens de una sesión completa). Desde entonces, la regla es: **el trabajo pesado (generar HTML, tocar `site_data.json`) nunca pasa por una sesión de Claude — siempre lo hace un GitHub Action, del lado del repo.** Cualquier cambio futuro al pipeline debe respetar esto. El porqué técnico completo está en `ARCHITECTURE.md` y en `CHANGELOG.md`.
