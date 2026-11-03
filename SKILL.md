---
name: auditoria-rendimiento-frontend
description: 'Audita el rendimiento frontend de un sitio web completo (descubre todas sus URLs y reporta los problemas por URL) con el enfoque "¿esto necesita pasar ahora?" (LCP real, imágenes, terceros, iframes, JS diferido, CLS, accesibilidad, medición antes/después) y lo que Google y los LLM buscan en la página (SEO/AEO: title, headings, TL;DR, FAQs, JSON-LD, dateModified, enlaces internos, robots/llms.txt; integra OpenSEO MCP y seodraft), y entrega un reporte Excel con todos los hallazgos. Usar cuando pidan revisar, auditar o medir el rendimiento, velocidad, performance, SEO o visibilidad en IA de una web o URL.'
---

# Auditoría de rendimiento frontend → reporte Excel

Basada en *Frontend Performance Optimization: A Practical Guide to Faster Web Pages* (Sachin Patel).
La tesis de la guía: el navegador tiene atención limitada en los primeros segundos; la pregunta que
guía cada decisión no es "¿esto es rápido?" sino **"¿esto necesita pasar ahora?"**. Cargar, ejecutar y
renderizar primero lo que el usuario necesita; diferir todo lo demás hasta que sea relevante.

Complementa esa guía con lo que **Google y los motores de respuesta (ChatGPT, Perplexity, AI Overviews)
buscan en la página**, según las reglas deterministas de *seodraft* (gate/audit: title, description,
H1/headings, enlaces internos, alt, TL;DR, FAQs, `dateModified`, answer-first, no inventar fuentes) y los
datos de *OpenSEO* (site audit, Search Console, visibilidad en IA) cuando su MCP esté conectado. Una página
rápida que no es citable deja la mitad del valor sobre la mesa; una citable pero lenta, igual.

El entregable obligatorio es un **Excel con todos los hallazgos**, generado con `scripts/perf_report_xlsx.py`. Las herramientas recogen evidencia; esta skill la interpreta; el usuario decide
con criterio de ingeniería qué cambiar.

## 1. Entradas y alcance: el sitio completo, problemas por URL

La auditoría por defecto es **completa**: se descubren todas las URLs del sitio y cada una se revisa por
separado, para que el Excel diga **en qué URL** está cada problema. `$SKILL_DIR` es la carpeta de esta skill.

1. Pide/identifica el **sitio** (dominio) o las URLs. Si dan una sola URL y piden solo esa página, salta a
   la Vía A–E sobre esa URL; en cualquier otro caso, audita el sitio completo (Vía 0).
2. Dispositivo: **móvil y escritorio** (móvil manda para Core Web Vitals).
3. Si el usuario entrega JSON de Lighthouse / PageSpeed Insights, trazas de DevTools o un HAR, úsalos
   directamente (la guía recomienda justamente dar esos artefactos a la IA para analizarlos) — no repitas mediciones.
4. Si hay una medición previa (línea base), pídela: el Excel incluye hoja **Antes vs Después** (`--antes`),
   emparejada por URL y dispositivo.
5. Todo se guarda en la carpeta **Documentos** del usuario, una carpeta por sitio y fecha:
   ```bash
   OUT="$(python3 "$SKILL_DIR/scripts/rutas.py" "https://dominio.com")"   # crea e imprime la ruta absoluta
   # → ~/Documents/auditorias-rendimiento/dominio.com-AAAA-MM-DD/   (o ~/Documentos, o la de XDG en Linux)
   ```
   En esta guía `out/` significa `$OUT` (con una subcarpeta por URL en `urls/<slug>/`). Si el usuario
   pide otra ubicación, exporta `AUDITORIA_OUT_BASE=/otra/ruta` antes de llamar a `rutas.py`.

## 2. Medir primero, no optimizar (§1 de la guía)

### Vía 0 — Sitio completo (por defecto)
```bash
OUT="$(python3 "$SKILL_DIR/scripts/rutas.py" "https://dominio.com")"
python3 "$SKILL_DIR/scripts/discover_urls.py" "https://dominio.com" --out "$OUT"/urls.json
python3 "$SKILL_DIR/scripts/audit_site.py" --urls "$OUT"/urls.json --out "$OUT" --motor lighthouse
python3 "$SKILL_DIR/scripts/perf_report_xlsx.py" --dir "$OUT" --sitio "<Nombre>" \
  --out "$OUT/reporte-rendimiento-<dominio>-$(date +%Y-%m-%d).xlsx"
```
1. **Descubrimiento** (`discover_urls.py`): lee `robots.txt` → sitemaps (índices y `.gz` incluidos); si no hay
   sitemap, rastrea enlaces internos desde la home respetando `robots.txt`. Normaliza y deduplica (barra
   final, `utm_*`, fragmentos), descarta otros dominios y no-HTML, y agrupa por **plantilla** (`/blog/*`).
   Opciones: `--include`/`--exclude` (regex), `--max N` (tope explícito; por defecto todas),
   `--crawl-depth`, `--max-crawl`. Las URLs descartadas quedan en `excluidas` con su motivo.
2. **Auditoría** (`audit_site.py`): por cada URL ejecuta `aeo_site_checks.py` (SEO/AEO, en paralelo con
   `--concurrency`), Lighthouse móvil y escritorio (`--motor lighthouse`, en serie) o PSI (`--motor psi`,
   usa `PSI_API_KEY` si existe) y, con `--browser`, el recolector Playwright. Los checks de sitio
   (robots.txt, llms.txt, sitemap) corren **una vez** (`out/sitio-aeo.json`).
   - Sitios grandes: `--lighthouse-por-plantilla N` limita Lighthouse/PSI a N URLs por plantilla; los checks
     SEO/AEO siguen corriendo en **todas**. `--solo-movil` reduce a la mitad el tiempo de laboratorio.
     Estima antes: ~20–40 s por corrida de Lighthouse. Avisa al usuario si pasa de ~1 h.
   - Es **reanudable**: si se corta, vuelve a ejecutar el mismo comando; reutiliza las salidas válidas.
   - Deja `out/cobertura.json` (qué paso corrió en cada URL: ok / reutilizado / error / no aplica) y
     `out/errores.json`. Una URL que falla no detiene el resto.
3. **Cruce entre URLs** (`site_crosscheck.py`, lo lanza `audit_site.py` salvo `--sin-crosscheck`): title,
   description y H1 duplicados, URLs del sitemap con error/redirección/noindex, canonical externo o roto,
   enlaces internos rotos y páginas huérfanas. `--verificar-enlaces N` comprueba por HTTP hasta N enlaces
   internos que no están en el sitemap.
4. Luego aplica §3 a una URL representativa **de cada plantilla** (los problemas de plantilla se repiten en
   todas sus URLs) y registra lo manual en `out/manual.json` con la `url` concreta.

Si Lighthouse no está disponible en el entorno, usa `--motor psi` o `--motor ninguno` (solo SEO/AEO) y
complementa con las vías siguientes. Las vías A–E describen cada medición por separado (una URL o depuración).

### Vía A — Lighthouse CLI (preferida: laboratorio completo)
```bash
export CHROME_PATH=$(node -e "console.log(require('playwright').chromium.executablePath())" 2>/dev/null || which google-chrome chromium chromium-browser | head -1)
FLAGS="--headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage"
npx -y lighthouse "$URL" --output=json --output-path="$OUT"/lh-mobile.json  --locale=es --chrome-flags="$FLAGS" --quiet
npx -y lighthouse "$URL" --output=json --output-path="$OUT"/lh-desktop.json --locale=es --preset=desktop --chrome-flags="$FLAGS" --quiet
```
- Varias URLs: usa la Vía 0 (`audit_site.py`), que guarda `out/urls/<slug>/lh-mobile.json`. Si hay tiempo, 3 corridas móviles y conserva la mediana.
- Error "interstitial" / 403 del proxy = la red del entorno bloquea el sitio → Vía B o C. Sin Chrome → B o C.

### Vía B — API de PageSpeed Insights (sin Chrome; añade datos de campo CrUX con INP real)
```bash
curl -s "https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=$URL&strategy=mobile&category=performance&category=accessibility&category=best-practices&category=seo&locale=es" -o "$OUT"/psi-mobile.json
curl -s "https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=$URL&strategy=desktop&category=performance&locale=es" -o "$OUT"/psi-desktop.json
```
El generador acepta estos JSON tal cual. Si la API no está permitida en el entorno, pide al usuario el JSON
(DevTools → Lighthouse → "Save as JSON", o pagespeed.web.dev).

### Vía C — Recolector en navegador (Claude in Chrome, Playwright o DevTools)
`scripts/collect_browser.js` implementa las comprobaciones específicas de la guía que Lighthouse no
reporta: cuál es el **elemento LCP real**, imagen LCP con `lazy` o sin `fetchpriority`, `fetchpriority="high"`
repartido en varias imágenes, slides de carrusel fuera de pantalla cargadas de entrada, animaciones en
elementos no visibles, varias fuentes precargadas, iframes sin caja dimensionada o con `src` en la carga
inicial, botones de solo ícono sin nombre, `aria-label` redundantes y falta de `prefers-reduced-motion`.
- **Claude in Chrome**: navega a la URL, espera carga completa, ejecuta el script con `javascript_tool`,
  guarda el resultado en `out/browser.json` y la clave `hallazgos` en `out/browser-hallazgos.json`.
- **Playwright local**: `node "$SKILL_DIR/scripts/run_collect.js" "$URL" out/browser.json` (emula móvil; en la Vía 0, `--browser`).
- Úsala **también** cuando tengas Lighthouse: son hallazgos complementarios.

### Vía D — Revisión estática (último recurso)
`curl -sI "$URL"` y el HTML: scripts síncronos en `<head>`, `<link rel=preload as=font>` múltiples,
`<img>` sin `width/height` o con `fetchpriority="high"` repetido, iframes con `src` directo,
`Cache-Control`, `Content-Encoding`, redirecciones (`curl -sIL`). Registra cada hallazgo en `out/manual.json` (§4).

### Vía E — SEO/AEO: `aeo_site_checks.py` (siempre) + OpenSEO MCP y seodraft (si existen)
```bash
python3 "$SKILL_DIR/scripts/aeo_site_checks.py" "$URL" --out "$OUT"/aeo.json   # solo stdlib
```
Aplica a la página servida las reglas de seodraft (title 15–60, description 50–160, un H1 sin
saltos, ≥ 2 enlaces internos, alt, thin content, TL;DR, FAQs/FAQPage, answer-first, JSON-LD con
author/dateModified, frescura > 12 meses) más canonical/noindex/lang/OG, `robots.txt` (bots de IA y
Sitemap), `llms.txt` y `sitemap.xml`. En la Vía 0 lo ejecuta `audit_site.py` en todas las URLs
(`--sin-checks-sitio` por página y `--solo-sitio` una vez por dominio).
- **OpenSEO MCP conectado** (herramientas `openseo.*` / skills `/seo-audit`, `/keyword-research`): úsalo
  para lo que esta skill no puede ver desde fuera: Site Audit completo, Search Console (consultas en
  página 2, CTR, impresiones), AI Visibility (menciones/citas de la marca en ChatGPT y AI Overviews) y
  keywords del término objetivo. Vuelca lo relevante a `out/manual.json` con área SEO/AEO. No pagues
  consultas de DataForSEO sin avisar al usuario.
- **Repo de contenido con seodraft** (`.seodraft/config.json`): `seodraft audit > out/seodraft-audit.json`
  (o `node <skill>/scripts/audit.mjs`) y pásalo al generador con `--seodraft`. Si el usuario escribe o
  refresca contenido a partir de la auditoría, remítelo a `/seodraft write` / `/seodraft audit`: ahí está
  el gate que impide publicar sin TL;DR, FAQs o con canibalización.

## 3. Revisión guiada por la guía (lo que las herramientas no ven)

Para cada punto responde: **¿qué compite con la primera experiencia significativa del usuario?**
Registra lo que falle en `out/manual.json`. Umbrales: LCP ≤ 2,5 s · INP ≤ 200 ms · CLS ≤ 0,1 · TBT ≤ 200 ms · TTFB ≤ 0,8 s.

| Sección de la guía | Verificar |
|---|---|
| §3 Imágenes: priorizar solo lo que importa | ¿Cuál es la imagen LCP **real** (no "todas las del primer pliegue")? Clasifica: LCP / visibles / fuera de pantalla. `loading` controla **cuándo** (eager/lazy); `fetchPriority` controla **cuánto importa** (high/low) — son cosas distintas y `fetchPriority` no reemplaza al lazy. Solo la LCP con `priority`/`fetchpriority="high"`; el resto no. `srcset`/`sizes`: una imagen perfectamente priorizada de 1,5 MB sigue pesando 1,5 MB. |
| §3.4–3.6 Carruseles y placeholders | ¿Se montan/cargan las 5-10 slides cuando el usuario ve una? La primera slide no es automáticamente el hero. La carga no debe atarse a la slide activa (remonta → flashes y re-descargas). Galería a pantalla completa ≠ carrusel de cards (el usuario salta de imagen: no diferir agresivamente). Placeholders estáticos; no animar slides ocultas; `prefers-reduced-motion`. |
| §4 LCP: despejar la pista | Mira **todo lo que carga alrededor del LCP**: fuentes, terceros, iframes, otras imágenes, ejecución de JS. ¿Necesita ocurrir antes de que el usuario vea el contenido principal? Si no, diferir. |
| §4.1 Fuentes | Preload solo de la fuente principal de UI; quitar preload de fuentes secundarias/decorativas (preload no es una medalla: significa "merece competir por ancho de banda temprano"); `font-display: swap`. |
| §5 Terceros | Chat, analytics, mapas, soporte: patrón **página → contenido crítico → `window.load` → idle (`requestIdleCallback` con timeout) → SDK**; diferir oportunistamente, no indefinidamente. Híbrido: si el usuario hace clic antes, cargar de inmediato (el launcher no puede quedar inoperante). |
| §6 Iframes | Un iframe es otro documento completo. Placeholder dimensionado primero → observar → asignar `src` al acercarse → fade-in. Escape hatch: si el usuario pide el contenido, cargarlo ya. "Diferir por defecto, saltarse la espera ante intención del usuario." |
| §7 JavaScript: si no está abierto, no lo envíes | Costo = descarga → parse → compile → ejecución → hidratación. Lightboxes, drawers, paneles de detalle y sliders → `dynamic import` al abrirse (la primera interacción paga; las siguientes usan el chunk cacheado). Skeletons con CSS, no con componentes pesados. Secciones bajo el pliegue en chunks aparte; contenido del primer pliegue y SEO sincrónico. Sin animaciones decorativas durante la hidratación (la animación de "añadir a favoritos" va tras el clic, no en cada hidratación). |
| §8 CLS: reservar el espacio **correcto** | Fuentes de CLS: cambios tras hidratar, imágenes sin dimensiones, iframes sin espacio, estados de carga que no coinciden con el layout final, contenido asíncrono insertado. Servidor y cliente deben coincidir (no renderizar desktop y remontar a mobile tras hidratar: usar device hints u otras entradas estables). La geometría del skeleton debe igualar la UI final (`aspect-ratio`, mismo grid). Iframe: caja antes que `src`. |
| §9 Enfoques que no funcionan | Todo en alta prioridad; lazy en el LCP; diferir terceros sin escape hatch; skeleton que reserva "algún" espacio pero no el correcto; optimizar una métrica añadiendo complejidad o riesgo. Buscar la estrategia más simple que mejore la UX sin crear otro problema. |
| §10 Accesibilidad sin regresiones | Botones de solo ícono con etiqueta; sin `aria-label` redundantes; `role="presentation"` en estructura; `role="status"` en estados de carga; `inert` para contenido montado pero no interactivo; `prefers-reduced-motion`. "Que el navegador haga menos sin que la experiencia sea menos comprensible." |
| §11 Medir el resultado | Comparar antes/después de cada cambio significativo; si no hay cifras exactas, mejoras relativas ("LCP mejoró ~X %, JS inicial bajó ~Y %"). Conectar cada cambio de ingeniería con un resultado medible. |
| SEO/AEO — lo que Google y los LLM buscan | **Estructura citable**: un H1; H2/H3 como la pregunta que el lector escribiría; cada sección responde en su **primera frase** y sobrevive extraída sola. **TL;DR** autocontenido (100–400 caracteres) bajo el H1: es el bloque que un motor de respuesta levanta. **≥ 3 FAQs** reales (respuesta ≤ 500 caracteres, contesta en la primera frase) marcadas con FAQPage. **Frescura**: `updatedDate` real → `dateModified` en JSON-LD y visible; > 12 meses sin tocar = oportunidad de refresco. **Entidad y autoría**: Article con author, Organization/WebSite con sameAs. **Enlazado**: ≥ 2 internos relevantes, ninguno roto, sin huérfanas, sin dos URLs para el mismo término (canibalización = parar, no reescribir). **Rastreo**: canonical, sin noindex accidental, robots.txt con Sitemap y decisión explícita sobre bots de IA (permitir OAI-SearchBot/PerplexityBot/ClaudeBot para citación aunque se bloquee GPTBot/Google-Extended para entrenamiento), `llms.txt`. **Fuentes**: citar solo URLs verificadas; una fuente inventada es peor que ninguna. |
| Framework (Next/React) | `next/image` con `priority` solo en LCP, `next/font`, `dynamic(() => import(...), { ssr: false })` para overlays y widgets, RSC/Server Components para datos, `startTransition`/`useDeferredValue` en interacciones costosas, `React.lazy` + `Suspense`, `<Activity>` para preservar estado de UI oculta sin pagar su render al inicio. |

## 4. Rúbrica de severidad y formato de hallazgo manual

| Severidad | Criterio |
|---|---|
| Crítico | Pone un Core Web Vital en "Pobre", compite directamente con el LCP (p. ej. LCP con `lazy`, terceros antes del contenido), ahorro estimado ≥ 1 s / ≥ 500 KB, o puntaje de auditoría < 50 |
| Alto | Ahorro ≥ 300 ms / ≥ 150 KB, puntaje 50-74, o afecta claramente a LCP/INP/CLS |
| Medio | Puntaje 75-89, mejora incremental, prioridades mal repartidas, higiene de recursos |
| Bajo | Buenas prácticas, accesibilidad sin impacto de rendimiento, informativo |

La guía pide evaluar también **impacto, esfuerzo, complejidad y riesgo**: rellena `esfuerzo` con honestidad; un
hallazgo "Medio" de esfuerzo "Bajo" es un quick win y va antes que un "Alto" de esfuerzo "Alto".

`out/manual.json` es una lista de objetos:
```json
[{"url":"https://…","categoria":"Imágenes","titulo":"fetchpriority=high en 6 imágenes","severidad":"Medio",
  "descripcion":"Qué pasa y por qué importa","recomendacion":"Qué cambiar, concreto",
  "evidencia":"snippet, cabecera o URL del recurso","esfuerzo":"Bajo|Medio|Alto","form_factor":"Ambos"}]
```
Áreas válidas: Imágenes · LCP · JavaScript · CSS · Fuentes · Red y caché · Terceros · Iframes · Renderizado · Layout (CLS) · Accesibilidad · Medición · SEO · AEO.

## 5. Generar el Excel (obligatorio)

```bash
python3 -c "import openpyxl" 2>/dev/null || pip install openpyxl --break-system-packages -q
# Sitio completo (Vía 0): toma todo lo que hay en $OUT
python3 "$SKILL_DIR/scripts/perf_report_xlsx.py" --dir "$OUT" --sitio "<Nombre del sitio>" \
  --out "$OUT/reporte-rendimiento-<dominio>-$(date +%Y-%m-%d).xlsx" [--manual "$OUT"/manual.json] [--antes "$OUT"/lh-base-*.json]
# Una URL o archivos sueltos
python3 "$SKILL_DIR/scripts/perf_report_xlsx.py" --out "$OUT"/reporte.xlsx "$OUT"/lh-mobile.json "$OUT"/lh-desktop.json \
  --manual "$OUT"/manual.json "$OUT"/browser-hallazgos.json "$OUT"/aeo.json [--seodraft "$OUT"/seodraft-audit.json] --sitio "<Nombre>"
```
- `--dir` lee `urls.json`, `cobertura.json`, `crosscheck.json`, `sitio-aeo.json`, `manual.json` y cada
  `urls/<slug>/` (Lighthouse/PSI, `aeo.json`, `browser-hallazgos.json`), asignando la URL por carpeta.
  Un JSON con `error`/`runtimeError` se omite con aviso. Se puede combinar con informes y `--manual` sueltos.
- `--seodraft` importa la salida de `seodraft audit`/`gate` (failures → Alto, advisories AEO → Medio).
- Hojas: **Resumen** (URLs, puntajes, conteo por severidad, top 10 con URL) · **Core Web Vitals** · **Hallazgos**
  (una fila por URL y problema; los de sitio llevan el prefijo "(sitio)") · **Detalle** · **Recursos** ·
  **Checklist** (con la columna "URLs que no cumplen") · **Antes vs Después** (con `--antes`).
  Con más de una URL, además: **Por URL** (severidades, puntaje y LCP por URL, peores primero, pasos con
  error) · **Por plantilla** · **Patrones** (mismo problema en muchas URLs = arreglo de plantilla) ·
  **Checklist por URL** (matriz URL × punto) · **Cobertura** (qué se midió en cada URL y qué URLs se excluyeron y por qué).
- En **Checklist**, completa a mano los "Revisar manualmente" con lo observado en §3 (columna Evidencia).
- Verifica con openpyxl: hallazgos > 0, CWV con valores, sin filas vacías, y que **Cobertura** no tenga
  pasos en error sin explicar. Entrega con `SendUserFile` si está disponible.
- Al terminar, `perf_report_xlsx.py` imprime las rutas absolutas (`Reporte: …` y `Carpeta de la auditoría: …`):
  cópialas tal cual al cierre del chat.

## 6. Cierre en el chat (breve)

1. **Ubicación de la entrega**: ruta absoluta del Excel y de la carpeta de la auditoría (JSON por URL,
   `cobertura.json`, `crosscheck.json`), tal como las imprimió `perf_report_xlsx.py`.
2. Alcance real: URLs descubiertas, auditadas y excluidas (y si Lighthouse fue a todas o por plantilla).
3. Estado de LCP / CLS / TBT-INP por dispositivo **por plantilla** y cuál es el elemento LCP real en cada una.
   Y en una línea el estado SEO/AEO: ¿las páginas son citables? (TL;DR, FAQs, JSON-LD con dateModified, rastreable por bots de IA).
4. Las **10 peores URLs** (hoja Por URL) y los patrones que se repiten en más URLs (hoja Patrones): ahí está el mayor retorno.
5. Qué está compitiendo con la primera experiencia significativa (3-5 hallazgos prioritarios con ahorro estimado).
6. Quick wins (bajo esfuerzo, alto impacto) vs. trabajo estructural, con la advertencia de la guía: cambiar
   **una cosa significativa a la vez, volver a medir, y revertir si no mejora**.
7. Laboratorio ≠ campo; INP solo con usuarios reales; variación entre corridas.

## Errores frecuentes a evitar
- Recomendar `loading="lazy"` o `fetchpriority="high"` en bloque: la guía insiste en priorizar **una** imagen (la LCP).
- Diferir terceros/iframes sin escape hatch de intención del usuario.
- Tratar accesibilidad/SEO como rendimiento: van en el Excel con severidad ≤ Medio, pero el foco es rendimiento;
  eso sí, ninguna recomendación de rendimiento puede introducir una regresión de accesibilidad (§10).
- Implementar todas las recomendaciones de Lighthouse sin juicio de ingeniería (impacto/esfuerzo/riesgo).
- Inventar fuentes o cifras SEO (volúmenes, posiciones) sin OpenSEO/Search Console: si no hay datos, dilo y marca la estimación como tal.
- Reescribir un término para esquivar una canibalización, o "arreglar" un TL;DR ausente desmapeando el campo.
- Auditar una muestra de URLs elegida a mano cuando se pidió el sitio: usa la Vía 0; si recortas (por plantilla o `--max`), dilo en el cierre.
- Terminar sin el Excel. Si una vía falla, usa la siguiente; si todas fallan, pide los JSON al usuario y genera igual el reporte.

## Scripts (en `scripts/`)

| Script | Qué hace |
|---|---|
| `discover_urls.py` | Descubre las URLs del sitio (robots.txt → sitemaps → rastreo) → `urls.json` |
| `audit_site.py` | Orquesta la auditoría de todas las URLs, reanudable → `urls/<slug>/`, `cobertura.json` |
| `aeo_site_checks.py` | Checks SEO/AEO de una página y del sitio (solo stdlib) |
| `site_crosscheck.py` | Problemas entre URLs: duplicados, sitemap, canonical, enlaces rotos, huérfanas |
| `collect_browser.js` / `run_collect.js` | Recolector en navegador de los checks de la guía (Playwright) |
| `perf_report_xlsx.py` | Genera el Excel (con `reporte_sitio.py` y `xlsx_estilos.py` para las hojas de sitio) |
| `url_utils.py` | Normalización, clave de unión, slug y plantilla de URLs |
| `rutas.py` | Carpeta de salida en Documentos: `auditorias-rendimiento/<dominio>-<fecha>/` |

Requisitos: Python 3.9+ con `openpyxl`; Node + `npx lighthouse` para Lighthouse; `playwright` para `--browser`.
