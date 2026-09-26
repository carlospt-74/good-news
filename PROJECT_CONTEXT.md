# Buenas Noticias — contexto del proyecto

**Qué es:** un portal de noticias 100% positivas en español, para audiencia de todo el continente americano (EE. UU., Canadá y Latinoamérica). Sitio estático publicado en GitHub Pages: https://carlospt-74.github.io/good-news/ — repositorio `carlospt-74/good-news`.

**Para quién:** lectores que quieren enterarse de logros, avances y buenas noticias reales, verificadas, sin ruido político ni sensacionalismo. El dueño del proyecto es Charly (carlos.perezt@gmail.com).

**Cómo se sostiene la confianza del portal** (no negociable — esto es el criterio editorial, no una preferencia de estilo):

- Cada nota es genuinamente positiva, no solo neutral. Un logro real, un avance verificable, una cifra que mejora — no una nota "no mala".
- Fuente creíble: medios de noticias reales, con autoría identificable. Nunca blogs anónimos ni contenido sin verificar.
- El hecho es verificable, no una promesa a futuro ni un rumor.
- Si la única fuente de un dato es la parte interesada (una empresa hablando de su propio producto, un gobierno de sus propios resultados), se marca `fuente_unica_interesada: true` y se atribuye explícitamente en el texto — nunca se presenta como hecho neutral verificado de forma independiente.
- **Cero tinte político**, sin excepción: se rechaza cualquier nota centrada en un gobierno, funcionario electo o partido presentando sus propios logros o cifras de gestión, aunque el contenido sea positivo y los datos sean ciertos. El motivo no es dudar de la cifra — es que ese encuadre hace parecer que el portal respalda a ese gobierno en particular. Aplica igual a cualquier país y cualquier signo político.
- Notas de la categoría IA solo califican si hay un beneficio humano directo y verificable (diagnóstico médico, accesibilidad, un problema concreto resuelto) — nunca lanzamientos de producto, rondas de inversión, ni "IA hace X más rápido" sin ese beneficio central.
- Cada nota se redacta en palabras propias (nunca copiando frases del original) y siempre enlaza a la fuente — el portal no aloja el contenido completo, dirige tráfico de vuelta al medio original. Esto es lo que mantiene al proyecto del lado seguro de "fair use".

**Categorías:** Deportes, Economía, Ciencia y Salud, Medio Ambiente, Sociedad, Tecnología, Cultura, IA, Otros.

**El pipeline, en una frase por fase** (el detalle técnico de cómo está construido cada fase va en `ARCHITECTURE.md`):

1. **Fase A — Búsqueda, verificación y reescritura** (skills `buenas-noticias-buscar` → `buenas-noticias-verificar` → `buenas-noticias-reescribir`): cada viernes encuentra 8-10 noticias nuevas de la semana, aplica el criterio editorial de arriba, las reescribe originales, y las sube como borrador (`data/pending/pendiente_<fecha>.json`) junto con un correo a Charly pidiendo revisión.
2. **Fase B — Aprobación y publicación** (skill `buenas-noticias-publicar`): unas horas después, revisa si Charly objetó algo por correo, y si no, dispara la publicación real.
3. **Los "Vigías"** (Vigía Fase A, Vigía Fase B): corren poco después de cada fase para confirmar que sí produjo lo esperado, y avisan a Charly por correo si algo se quedó a medias sin que nadie se entere.

**Las 4 tareas programadas** (IDs de trigger, para referencia rápida — el prompt completo de cada una vive en la propia tarea, no aquí):
- `trig_01M5rAiFf2bLou3P5PRTCiLv` — Fase A (viernes 12:00 UTC)
- `trig_01FYDNyMihxFmNZTfdfBSEMN` — Vigía Fase A (viernes 12:45 UTC)
- `trig_019YUyZyGdcfWDqSNitUysAV` — Fase B (viernes 17:00 UTC)
- `trig_01NTYtttd4ELTtTeHjKr2RkU` — Vigía Fase B (viernes 18:15 UTC)

**Un principio operativo que gobierna todo lo demás:** el 25-26 de septiembre de 2026 hubo un incidente de costo serio (publicar ~10 notas, transcribiendo HTML generado a mano por el chat hacia GitHub, consumió como el doble del presupuesto de tokens de una sesión completa). Desde entonces, la regla es: **el trabajo pesado (generar HTML, tocar `site_data.json`) nunca pasa por una sesión de Claude — siempre lo hace un GitHub Action, del lado del repo.** Cualquier cambio futuro al pipeline debe respetar esto. El porqué técnico completo está en `ARCHITECTURE.md` y en `CHANGELOG.md`.
