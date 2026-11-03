---
name: auditoria-rendimiento-frontend
description: Audita el rendimiento frontend de cualquier sitio web con el enfoque "¿esto necesita pasar ahora?" (LCP real, imágenes, terceros, iframes, JS diferido, CLS, accesibilidad, medición antes/después) y lo que Google y los LLM buscan en la página (SEO/AEO: title, headings, TL;DR, FAQs, JSON-LD, dateModified, enlaces internos, robots/llms.txt; integra OpenSEO MCP y seodraft), y entrega un reporte Excel con todos los hallazgos. Usar cuando pidan revisar, auditar o medir el rendimiento, velocidad, performance, SEO o visibilidad en IA de una web o URL.
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

El entregable obligatorio es un **Excel con todos los hallazgos**, generado con `perf_report_xlsx.py`
(Script 1, al final). Las herramientas recogen evidencia; esta skill la interpreta; el usuario decide
con criterio de ingeniería qué cambiar.

## 1. Entradas y alcance

1. Pide/identifica la(s) **URL(s)**. Si solo dan el dominio, audita como mínimo: home + 1 listado/categoría
   + 1 detalle (producto/artículo) + 1 formulario o checkout si existe.
2. Dispositivo: **móvil y escritorio** (móvil manda para Core Web Vitals).
3. Si el usuario entrega JSON de Lighthouse / PageSpeed Insights, trazas de DevTools o un HAR, úsalos
   directamente (la guía recomienda justamente dar esos artefactos a la IA para analizarlos) — no repitas mediciones.
4. Si hay una medición previa (línea base), pídela: el Excel incluye hoja **Antes vs Después** (`--antes`).
5. `mkdir -p perf-audit/out` y guarda ahí todo.

## 2. Medir primero, no optimizar (§1 de la guía)

Elige la primera vía que funcione; no insistas en una bloqueada.

### Vía A — Lighthouse CLI (preferida: laboratorio completo)
```bash
export CHROME_PATH=$(node -e "console.log(require('playwright').chromium.executablePath())" 2>/dev/null || which google-chrome chromium chromium-browser | head -1)
FLAGS="--headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage"
npx -y lighthouse "$URL" --output=json --output-path=out/lh-mobile.json  --locale=es --chrome-flags="$FLAGS" --quiet
npx -y lighthouse "$URL" --output=json --output-path=out/lh-desktop.json --locale=es --preset=desktop --chrome-flags="$FLAGS" --quiet
```
- Varias URLs: `lh-<slug>-mobile.json` en un bucle. Si hay tiempo, 3 corridas móviles y conserva la mediana.
- Error "interstitial" / 403 del proxy = la red del entorno bloquea el sitio → Vía B o C. Sin Chrome → B o C.

### Vía B — API de PageSpeed Insights (sin Chrome; añade datos de campo CrUX con INP real)
```bash
curl -s "https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=$URL&strategy=mobile&category=performance&category=accessibility&category=best-practices&category=seo&locale=es" -o out/psi-mobile.json
curl -s "https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=$URL&strategy=desktop&category=performance&locale=es" -o out/psi-desktop.json
```
El generador acepta estos JSON tal cual. Si la API no está permitida en el entorno, pide al usuario el JSON
(DevTools → Lighthouse → "Save as JSON", o pagespeed.web.dev).

### Vía C — Recolector en navegador (Claude in Chrome, Playwright o DevTools)
`collect_browser.js` (Script 2) implementa las comprobaciones específicas de la guía que Lighthouse no
reporta: cuál es el **elemento LCP real**, imagen LCP con `lazy` o sin `fetchpriority`, `fetchpriority="high"`
repartido en varias imágenes, slides de carrusel fuera de pantalla cargadas de entrada, animaciones en
elementos no visibles, varias fuentes precargadas, iframes sin caja dimensionada o con `src` en la carga
inicial, botones de solo ícono sin nombre, `aria-label` redundantes y falta de `prefers-reduced-motion`.
- **Claude in Chrome**: navega a la URL, espera carga completa, ejecuta el script con `javascript_tool`,
  guarda el resultado en `out/browser.json` y la clave `hallazgos` en `out/browser-hallazgos.json`.
- **Playwright local**: `node run_collect.js "$URL" out/browser.json` (Script 3; emula móvil).
- Úsala **también** cuando tengas Lighthouse: son hallazgos complementarios.

### Vía D — Revisión estática (último recurso)
`curl -sI "$URL"` y el HTML: scripts síncronos en `<head>`, `<link rel=preload as=font>` múltiples,
`<img>` sin `width/height` o con `fetchpriority="high"` repetido, iframes con `src` directo,
`Cache-Control`, `Content-Encoding`, redirecciones (`curl -sIL`). Registra cada hallazgo en `out/manual.json` (§4).

### Vía E — SEO/AEO: `aeo_site_checks.py` (siempre) + OpenSEO MCP y seodraft (si existen)
```bash
python3 aeo_site_checks.py "$URL" --out out/aeo.json      # solo stdlib; también sirve como Vía D para SEO
```
Script 4: aplica a la página servida las reglas de seodraft (title 15–60, description 50–160, un H1 sin
saltos, ≥ 2 enlaces internos, alt, thin content, TL;DR, FAQs/FAQPage, answer-first, JSON-LD con
author/dateModified, frescura > 12 meses) más canonical/noindex/lang/OG, `robots.txt` (bots de IA y
Sitemap), `llms.txt` y `sitemap.xml`. Corre una vez por URL auditada (home, listado, detalle, artículo).
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
python3 perf_report_xlsx.py --out "out/reporte-rendimiento-<dominio>-$(date +%Y-%m-%d).xlsx" \
  out/lh-mobile.json out/lh-desktop.json [más JSON de Lighthouse/PSI...] \
  --manual out/manual.json out/browser-hallazgos.json out/aeo.json \
  [--seodraft out/seodraft-audit.json] --sitio "<Nombre del sitio>" [--antes out/lh-base-mobile.json out/lh-base-desktop.json]
```
- Acepta cualquier combinación: solo Lighthouse, solo PSI, solo `--manual` (vías C/D/E), o todo junto.
  `--manual` admite varios archivos (listas o `{hallazgos:[...]}`) y los fusiona; `--seodraft` importa la
  salida de `seodraft audit`/`gate` (failures → Alto, advisories AEO → Medio).
- Hojas: **Resumen** (URLs, puntajes, conteo por severidad, top 10) · **Core Web Vitals** (laboratorio + campo
  con semáforo) · **Hallazgos** (ID, área, severidad, prioridad, ahorro ms/KB, descripción, recomendación,
  esfuerzo, estado, responsable; con filtros) · **Detalle** (recursos/elementos afectados por hallazgo) ·
  **Recursos** (peticiones por peso/protocolo/prioridad) · **Checklist** (los puntos de la guía, con
  Cumple / No cumple / Revisar manualmente; incluye la sección **SEO / AEO**) · **Antes vs Después** (solo con `--antes`).
- En **Checklist**, completa a mano los "Revisar manualmente" con lo observado en §3 (columna Evidencia).
- Verifica con openpyxl: hallazgos > 0, CWV con valores, sin filas vacías. Entrega con `SendUserFile`.

## 6. Cierre en el chat (breve)

1. Estado de LCP / CLS / TBT-INP por dispositivo y **cuál es el elemento LCP real**.
   Y en una línea el estado SEO/AEO: ¿la página es citable? (TL;DR, FAQs, JSON-LD con dateModified, rastreable por bots de IA).
2. Qué está compitiendo con la primera experiencia significativa (3-5 hallazgos prioritarios con ahorro estimado).
3. Quick wins (bajo esfuerzo, alto impacto) vs. trabajo estructural, con la advertencia de la guía: cambiar
   **una cosa significativa a la vez, volver a medir, y revertir si no mejora**.
4. Laboratorio ≠ campo; INP solo con usuarios reales; variación entre corridas.

## Errores frecuentes a evitar
- Recomendar `loading="lazy"` o `fetchpriority="high"` en bloque: la guía insiste en priorizar **una** imagen (la LCP).
- Diferir terceros/iframes sin escape hatch de intención del usuario.
- Tratar accesibilidad/SEO como rendimiento: van en el Excel con severidad ≤ Medio, pero el foco es rendimiento;
  eso sí, ninguna recomendación de rendimiento puede introducir una regresión de accesibilidad (§10).
- Implementar todas las recomendaciones de Lighthouse sin juicio de ingeniería (impacto/esfuerzo/riesgo).
- Inventar fuentes o cifras SEO (volúmenes, posiciones) sin OpenSEO/Search Console: si no hay datos, dilo y marca la estimación como tal.
- Reescribir un término para esquivar una canibalización, o "arreglar" un TL;DR ausente desmapeando el campo.
- Terminar sin el Excel. Si una vía falla, usa la siguiente; si todas fallan, pide los JSON al usuario y genera igual el reporte.

---

## Script 1 — `perf_report_xlsx.py` (guardar tal cual)

```python
#!/usr/bin/env python3
"""
Genera un reporte Excel de auditoría de rendimiento frontend a partir de:
  - uno o más JSON de Lighthouse (CLI o PageSpeed Insights API: se acepta el
    objeto raíz de PSI, que trae `lighthouseResult` y `loadingExperience`)
  - opcionalmente un JSON de hallazgos manuales (lista de objetos con las
    claves: url, categoria, titulo, severidad, descripcion, recomendacion,
    evidencia, esfuerzo)

Uso:
  python3 perf_report_xlsx.py --out reporte.xlsx lh-mobile.json [lh-desktop.json ...] \
      [--manual hallazgos.json aeo.json ...] [--seodraft audit.json] [--sitio "Nombre"] [--antes lh-base-mobile.json ...]
"""
import argparse, json, datetime, re
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import CellIsRule, FormulaRule

# ---------- Umbrales Core Web Vitals / métricas de laboratorio ----------
METRICAS = [
    # id auditoría, nombre, unidad, bueno <=, pobre >, es Core Web Vital
    ("largest-contentful-paint", "LCP – Largest Contentful Paint", "ms", 2500, 4000, True),
    ("cumulative-layout-shift", "CLS – Cumulative Layout Shift", "", 0.1, 0.25, True),
    ("total-blocking-time", "TBT – Total Blocking Time (proxy de INP en laboratorio)", "ms", 200, 600, False),
    ("first-contentful-paint", "FCP – First Contentful Paint", "ms", 1800, 3000, False),
    ("speed-index", "Speed Index", "ms", 3400, 5800, False),
    ("interactive", "TTI – Time to Interactive", "ms", 3800, 7300, False),
    ("server-response-time", "TTFB – Tiempo de respuesta del servidor", "ms", 800, 1800, False),
    ("max-potential-fid", "Max Potential FID", "ms", 130, 250, False),
]
CRUX = [  # métricas de campo (PageSpeed Insights loadingExperience)
    ("LARGEST_CONTENTFUL_PAINT_MS", "LCP (campo, p75)", "ms", 2500, 4000),
    ("INTERACTION_TO_NEXT_PAINT", "INP (campo, p75)", "ms", 200, 500),
    ("CUMULATIVE_LAYOUT_SHIFT_SCORE", "CLS (campo, p75)", "/100", 10, 25),
    ("FIRST_CONTENTFUL_PAINT_MS", "FCP (campo, p75)", "ms", 1800, 3000),
    ("EXPERIMENTAL_TIME_TO_FIRST_BYTE", "TTFB (campo, p75)", "ms", 800, 1800),
]

# ---------- Clasificación de auditorías por área (según la guía de referencia) ----------
CATEGORIA = {
    "Imágenes": ["uses-optimized-images", "uses-webp-images", "modern-image-formats", "uses-responsive-images",
                 "offscreen-images", "efficient-animated-content", "unsized-images", "image-size-responsive",
                 "image-aspect-ratio", "prioritize-lcp-image", "lcp-lazy-loaded", "uses-responsive-images-snapshot"],
    "JavaScript": ["unused-javascript", "unminified-javascript", "legacy-javascript", "bootup-time",
                   "mainthread-work-breakdown", "duplicated-javascript", "long-tasks", "no-unload-listeners",
                   "dom-size", "third-party-facades", "forced-reflow-insight", "long-critical-network-tree",
                   "legacy-javascript-insight", "duplicated-javascript-insight", "modern-http-insight"],
    "CSS": ["unused-css-rules", "unminified-css", "render-blocking-resources", "critical-request-chains",
            "non-composited-animations", "render-blocking-insight", "cls-culprits-insight", "layout-shifts"],
    "Fuentes": ["font-display", "font-display-insight", "preload-fonts"],
    "Red y caché": ["uses-long-cache-ttl", "uses-text-compression", "server-response-time", "redirects",
                    "uses-rel-preconnect", "uses-rel-preload", "uses-http2", "total-byte-weight",
                    "network-requests", "network-rtt", "network-server-latency", "cache-insight",
                    "network-dependency-tree-insight", "document-latency-insight", "lcp-discovery-insight",
                    "lcp-breakdown-insight", "lcp-phases-insight"],
    "Terceros": ["third-party-summary", "third-party-facades", "third-parties-insight"],
    "Renderizado": ["largest-contentful-paint-element", "layout-shift-elements", "viewport",
                    "viewport-insight", "interaction-to-next-paint-insight", "inp-breakdown-insight",
                    "image-delivery-insight", "dom-size-insight", "bf-cache", "largest-contentful-paint",
                    "cumulative-layout-shift", "total-blocking-time", "first-contentful-paint", "speed-index",
                    "interactive", "max-potential-fid"],
}
AUDIT_TO_CAT = {a: c for c, ids in CATEGORIA.items() for a in ids}
CAT_GROUP = {"performance": "Rendimiento", "accessibility": "Accesibilidad",
             "best-practices": "Buenas prácticas", "seo": "SEO", "pwa": "PWA", "agentic-browsing": "Navegación agéntica"}

RECOMENDACION = {
    "render-blocking-resources": "Inline del CSS crítico, `defer`/`async` en scripts, mover JS no esencial al final; cargar CSS no crítico con `media=print` + `onload`.",
    "unused-javascript": "Code splitting por ruta/componente, `React.lazy` + `Suspense`, tree shaking, eliminar librerías no usadas.",
    "unused-css-rules": "PurgeCSS / `@tailwind` con `content` bien configurado, dividir CSS por ruta, eliminar reglas muertas.",
    "unminified-javascript": "Activar minificación (Terser/esbuild) en el build de producción.",
    "unminified-css": "Activar cssnano / Lightning CSS en el build de producción.",
    "uses-text-compression": "Habilitar Brotli (preferido) o Gzip en servidor/CDN para HTML, CSS, JS, SVG y JSON.",
    "uses-long-cache-ttl": "`Cache-Control: public, max-age=31536000, immutable` para assets con hash; HTML con `no-cache` o TTL corto.",
    "uses-optimized-images": "Recomprimir imágenes (calidad 75-85), usar pipeline de optimización (Sharp, next/image, CDN de imágenes).",
    "modern-image-formats": "Servir AVIF/WebP con `<picture>` o vía CDN con negociación de contenido.",
    "uses-responsive-images": "Usar `srcset` + `sizes` para servir el tamaño adecuado a cada viewport.",
    "offscreen-images": "`loading=\"lazy\"` en imágenes bajo el pliegue; NUNCA en la imagen LCP.",
    "unsized-images": "Declarar `width`/`height` o `aspect-ratio` en CSS para reservar espacio y evitar CLS.",
    "prioritize-lcp-image": "`fetchpriority=\"high\"` + `<link rel=preload>` en la imagen LCP; que sea descubrible en el HTML inicial.",
    "lcp-lazy-loaded": "Quitar `loading=\"lazy\"` de la imagen LCP.",
    "font-display": "`font-display: swap` (u `optional`) en `@font-face`; preload de la fuente principal; usar `size-adjust` para reducir CLS.",
    "server-response-time": "Mejorar TTFB: caché en servidor/CDN, SSR/ISR, optimizar consultas, HTTP/2 o HTTP/3, edge rendering.",
    "redirects": "Eliminar cadenas de redirección; apuntar enlaces y canonicals al destino final (https + www/no-www).",
    "uses-rel-preconnect": "`<link rel=preconnect>` (y `dns-prefetch`) a orígenes críticos de terceros (máx. 2-4).",
    "uses-rel-preload": "Preload de recursos críticos descubiertos tarde (fuentes, imagen LCP, CSS crítico).",
    "uses-http2": "Servir todos los recursos por HTTP/2 o HTTP/3 (verificar CDN y orígenes de terceros).",
    "total-byte-weight": "Reducir peso total de la página: imágenes, bundles, fuentes; auditar con bundle analyzer.",
    "bootup-time": "Reducir JS ejecutado al inicio: code splitting, diferir trabajo no crítico, evitar polyfills innecesarios.",
    "mainthread-work-breakdown": "Dividir tareas largas (`scheduler.yield`, `requestIdleCallback`), mover cálculo pesado a Web Workers.",
    "dom-size": "Reducir nodos DOM: virtualización de listas, evitar wrappers innecesarios, paginar contenido.",
    "third-party-summary": "Auditar scripts de terceros: cargar con `async`/`defer`, diferir tras interacción, usar facades (p. ej. lite-youtube), gestor de etiquetas con consentimiento.",
    "third-party-facades": "Reemplazar embeds pesados por facades que cargan el recurso real al interactuar.",
    "legacy-javascript": "Actualizar `browserslist`/targets para dejar de transpilar y enviar polyfills a navegadores modernos.",
    "duplicated-javascript": "Deduplicar dependencias (`npm dedupe`, alias en bundler) y revisar módulos repetidos entre chunks.",
    "non-composited-animations": "Animar solo `transform` y `opacity`; evitar animar `top/left/width/height`.",
    "layout-shift-elements": "Reservar espacio para contenido dinámico (ads, banners, imágenes), evitar insertar contenido sobre el existente.",
    "long-tasks": "Fragmentar tareas > 50 ms; diferir hidratación no crítica; usar `startTransition` para actualizaciones no urgentes.",
    "critical-request-chains": "Acortar cadenas críticas: inline CSS crítico, preload, reducir profundidad de imports.",
    "bf-cache": "Eliminar `unload` listeners y cabeceras `Cache-Control: no-store` en HTML para habilitar back/forward cache.",
    "viewport": "Añadir `<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">`.",
    "efficient-animated-content": "Reemplazar GIF animados por video (`<video autoplay muted loop playsinline>`) en WebM/MP4.",
}

def severidad(score, wasted_ms=0, wasted_kb=0, score_mode="numeric"):
    if score is None:
        return "Info"
    if score_mode == "informative":
        return "Bajo"
    if score < 0.5 or wasted_ms >= 1000 or wasted_kb >= 500:
        return "Crítico"
    if score < 0.75 or wasted_ms >= 300 or wasted_kb >= 150:
        return "Alto"
    if score < 0.9:
        return "Medio"
    return "Bajo"

PRIORIDAD = {"Crítico": 1, "Alto": 2, "Medio": 3, "Bajo": 4, "Info": 5}
ESFUERZO_DEF = {"Imágenes": "Bajo", "Fuentes": "Bajo", "Red y caché": "Medio", "CSS": "Medio",
                "JavaScript": "Alto", "Terceros": "Medio", "Renderizado": "Medio", "Accesibilidad": "Bajo",
                "Buenas prácticas": "Bajo", "SEO": "Bajo", "Manual": "Medio", "LCP": "Medio", "Iframes": "Bajo", "Layout (CLS)": "Medio", "Medición": "Bajo", "AEO": "Bajo"}

def estado(valor, bueno, pobre):
    if valor is None:
        return "Sin dato"
    if valor <= bueno:
        return "Bueno"
    if valor <= pobre:
        return "Necesita mejorar"
    return "Pobre"

def limpiar(txt):
    """Quita enlaces markdown y backticks del texto de Lighthouse."""
    if not txt:
        return ""
    txt = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", txt)
    return txt.replace("`", "")

# ---------- Carga de informes ----------
def cargar(path):
    raw = json.load(open(path, encoding="utf-8"))
    crux = None
    if "lighthouseResult" in raw:  # respuesta de PageSpeed Insights
        crux = raw.get("loadingExperience") or raw.get("originLoadingExperience")
        raw = raw["lighthouseResult"]
    ff = raw.get("configSettings", {}).get("formFactor") or raw.get("configSettings", {}).get("emulatedFormFactor", "mobile")
    return {"lh": raw, "crux": crux, "url": raw.get("finalDisplayedUrl") or raw.get("finalUrl") or raw.get("requestedUrl"),
            "ff": "Móvil" if ff == "mobile" else "Escritorio", "fecha": raw.get("fetchTime", "")[:19].replace("T", " ")}

# ---------- Importador de seodraft (gate/audit JSON) ----------
SEODRAFT_AEO = ("tldr", "faq", "updated", "stale", "thin")
SEODRAFT_SEV = {"error": "Alto", "advisory": "Medio"}
def importar_seodraft(raw):
    """Convierte {failures:[{rule,file,message,severity}], advisories:[...]} en hallazgos manuales."""
    out = []
    for it in (raw.get("failures") or []) + (raw.get("advisories") or []):
        rule = it.get("rule", ""); es_aeo = any(k in rule for k in SEODRAFT_AEO)
        sev = "Crítico" if rule in ("cannibalization", "broken-internal-link", "missing-title") else SEODRAFT_SEV.get(it.get("severity"), "Medio")
        if it.get("severity") == "advisory" and not es_aeo:
            sev = "Bajo"
        out.append({"url": it.get("file") or "", "categoria": "AEO" if es_aeo else "SEO", "id": f"seodraft:{rule}",
                    "titulo": f"seodraft · {rule}", "severidad": sev, "descripcion": it.get("message", ""),
                    "recomendacion": "Aplicar la corrección propuesta por `/seodraft audit` y volver a correr el audit sobre el archivo; si cambia contenido, subir updatedDate.",
                    "evidencia": it.get("file", ""), "esfuerzo": "Bajo", "form_factor": "Ambos"})
    return out

# ---------- Estilos ----------
HDR_FILL = PatternFill("solid", fgColor="1F3864")
HDR_FONT = Font(bold=True, color="FFFFFF")
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
COLORES = {"Crítico": "F8696B", "Alto": "FFA366", "Medio": "FFEB84", "Bajo": "C6E0B4", "Info": "DDEBF7",
           "Bueno": "C6EFCE", "Necesita mejorar": "FFEB9C", "Pobre": "FFC7CE", "Sin dato": "EDEDED"}

def encabezado(ws, cols, fila=1):
    for i, c in enumerate(cols, 1):
        cell = ws.cell(row=fila, column=i, value=c)
        cell.fill, cell.font, cell.border = HDR_FILL, HDR_FONT, BORDER
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = f"A{fila + 1}"

def ajustar(ws, anchos):
    for i, a in enumerate(anchos, 1):
        ws.column_dimensions[get_column_letter(i)].width = a

def pintar_estado(ws, col_letter, n_filas, fila_ini=2):
    if n_filas < fila_ini:
        return
    rng = f"{col_letter}{fila_ini}:{col_letter}{n_filas}"
    for k, color in COLORES.items():
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=[f'"{k}"'],
                                                      fill=PatternFill("solid", fgColor=color)))

# ---------- Construcción del libro ----------
def construir(informes, manuales, out, sitio, antes=None):
    wb = Workbook()
    hallazgos, recursos, detalle, metricas_rows, crux_rows, scores_rows = [], [], [], [], [], []
    hid = 1

    for inf in informes:
        lh, url, ff = inf["lh"], inf["url"], inf["ff"]
        audits = lh.get("audits", {})
        # Puntajes por categoría
        for cid, cat in lh.get("categories", {}).items():
            if cat.get("score") is not None:
                scores_rows.append([url, ff, CAT_GROUP.get(cid, cat.get("title", cid)), round(cat["score"] * 100)])
        # Métricas de laboratorio
        for aid, nombre, unidad, bueno, pobre, cwv in METRICAS:
            a = audits.get(aid)
            if not a or a.get("numericValue") is None:
                continue
            v = a["numericValue"]
            v = round(v, 3) if unidad == "" else round(v)
            metricas_rows.append([url, ff, nombre, "Sí" if cwv else "No", v, unidad, bueno, pobre,
                                  estado(v, bueno, pobre), a.get("displayValue", ""), "Laboratorio (Lighthouse)"])
        # Métricas de campo (CrUX)
        if inf["crux"] and inf["crux"].get("metrics"):
            for key, nombre, unidad, bueno, pobre in CRUX:
                m = inf["crux"]["metrics"].get(key)
                if m:
                    p75 = m.get("percentile")
                    crux_rows.append([url, nombre, p75, unidad, bueno, pobre, estado(p75, bueno, pobre),
                                      m.get("category", ""), "Campo (CrUX, 28 días)"])
        # Auditorías → hallazgos
        audit_group = {}
        for cid, cat in lh.get("categories", {}).items():
            for ref in cat.get("auditRefs", []):
                audit_group.setdefault(ref["id"], CAT_GROUP.get(cid, cid))
        for aid, a in audits.items():
            score, mode = a.get("score"), a.get("scoreDisplayMode", "numeric")
            if mode in ("notApplicable", "manual", "error"):
                continue
            det = a.get("details", {}) or {}
            items = det.get("items", []) if isinstance(det, dict) else []
            if not isinstance(items, list):
                items = []
            wasted_ms = (det.get("overallSavingsMs") or 0) if isinstance(det, dict) else 0
            wasted_kb = round((det.get("overallSavingsBytes") or 0) / 1024) if isinstance(det, dict) else 0
            es_problema = (score is not None and score < 0.9) or \
                          (mode == "informative" and (wasted_ms or wasted_kb) and aid in RECOMENDACION)
            if not es_problema:
                continue
            grupo = audit_group.get(aid, "Rendimiento")
            cat = AUDIT_TO_CAT.get(aid, grupo if grupo != "Rendimiento" else "Renderizado")
            sev = severidad(score, wasted_ms, wasted_kb, mode)
            if grupo != "Rendimiento":  # accesibilidad/SEO/buenas prácticas: no desplazan a los de rendimiento
                sev = "Medio" if (score is not None and score < 0.5) else "Bajo"
            hallazgos.append([f"H-{hid:03d}", url, ff, grupo, cat, aid, limpiar(a.get("title")), sev, PRIORIDAD[sev],
                              None if score is None else round(score * 100), wasted_ms or "", wasted_kb or "",
                              a.get("displayValue", ""), limpiar(a.get("description")),
                              RECOMENDACION.get(aid, "Revisar los elementos afectados en la hoja 'Detalle' y aplicar la guía de la auditoría."),
                              len(items), ESFUERZO_DEF.get(cat, "Medio"), "Pendiente", ""])
            # Detalle de elementos afectados
            for it in items[:60]:
                if not isinstance(it, dict):
                    continue
                recurso = it.get("url") or (it.get("node") or {}).get("selector") or (it.get("node") or {}).get("snippet") or it.get("entity") or it.get("label") or ""
                detalle.append([f"H-{hid:03d}", aid, url, ff, str(recurso)[:500],
                                round(it.get("totalBytes", 0) / 1024) if it.get("totalBytes") else "",
                                round(it.get("wastedBytes", 0) / 1024) if it.get("wastedBytes") else "",
                                round(it.get("wastedMs", 0)) if it.get("wastedMs") else "",
                                round(it.get("blockingTime", 0)) if it.get("blockingTime") else "",
                                round(it.get("duration", 0)) if it.get("duration") else ""])
            hid += 1
        # Recursos de red
        nr = audits.get("network-requests", {}).get("details", {}).get("items", [])
        for r in nr:
            recursos.append([url, ff, r.get("url", "")[:400], r.get("resourceType", ""), r.get("mimeType", ""),
                             round((r.get("transferSize") or 0) / 1024, 1), round((r.get("resourceSize") or 0) / 1024, 1),
                             round((r.get("networkEndTime") or 0) - (r.get("networkRequestTime") or 0)),
                             r.get("protocol", ""), r.get("priority", ""), r.get("statusCode", ""),
                             "Sí" if r.get("isLinkPreload") else ""])

    # Hallazgos manuales
    for m in manuales:
        sev = m.get("severidad", "Medio")
        hallazgos.append([f"H-{hid:03d}", m.get("url", ""), m.get("form_factor", "Ambos"), m.get("grupo", "Rendimiento"),
                          m.get("categoria", "Manual"), m.get("id", "manual"), m.get("titulo", ""), sev, PRIORIDAD.get(sev, 3),
                          "", "", "", m.get("evidencia", ""), m.get("descripcion", ""), m.get("recomendacion", ""),
                          m.get("afectados", ""), m.get("esfuerzo", "Medio"), "Pendiente", m.get("notas", "")])
        hid += 1

    hallazgos.sort(key=lambda h: (h[8], -(h[10] or 0), -(h[11] or 0)))

    # ===== Hoja Resumen =====
    ws = wb.active
    ws.title = "Resumen"
    ws["A1"] = f"Auditoría de rendimiento frontend – {sitio or (informes[0]['url'] if informes else '')}"
    ws["A1"].font = Font(bold=True, size=16, color="1F3864")
    ws["A2"] = f"Generado: {datetime.datetime.now():%Y-%m-%d %H:%M}   |   Herramienta: Lighthouse {informes[0]['lh'].get('lighthouseVersion','') if informes else ''}"
    ws["A4"] = "URLs auditadas"; ws["A4"].font = Font(bold=True, size=12)
    encabezado(ws, ["URL", "Dispositivo", "Fecha análisis"], fila=5)
    r = 6
    for inf in informes:
        ws.append([inf["url"], inf["ff"], inf["fecha"]]); r += 1
    r += 1
    ws.cell(row=r, column=1, value="Puntajes Lighthouse (0-100)").font = Font(bold=True, size=12); r += 1
    encabezado(ws, ["URL", "Dispositivo", "Categoría", "Puntaje"], fila=r); r += 1
    ini = r
    for s in scores_rows:
        for i, v in enumerate(s, 1):
            ws.cell(row=r, column=i, value=v).border = BORDER
        r += 1
    if r > ini:
        rng = f"D{ini}:D{r-1}"
        ws.conditional_formatting.add(rng, CellIsRule(operator="lessThan", formula=["50"], fill=PatternFill("solid", fgColor="FFC7CE")))
        ws.conditional_formatting.add(rng, CellIsRule(operator="between", formula=["50", "89"], fill=PatternFill("solid", fgColor="FFEB9C")))
        ws.conditional_formatting.add(rng, CellIsRule(operator="greaterThanOrEqual", formula=["90"], fill=PatternFill("solid", fgColor="C6EFCE")))
    r += 1
    ws.cell(row=r, column=1, value="Hallazgos por severidad").font = Font(bold=True, size=12); r += 1
    encabezado(ws, ["Severidad", "Cantidad", "Descripción"], fila=r); r += 1
    desc = {"Crítico": "Impacto directo en Core Web Vitals o > 1 s de ahorro. Atender primero.",
            "Alto": "Impacto notable en carga/interactividad. Atender en el sprint.",
            "Medio": "Mejora incremental. Planificar.",
            "Bajo": "Higiene / buenas prácticas.", "Info": "Informativo, sin puntaje."}
    for sev in ["Crítico", "Alto", "Medio", "Bajo", "Info"]:
        n = sum(1 for h in hallazgos if h[7] == sev)
        for i, v in enumerate([sev, n, desc[sev]], 1):
            c = ws.cell(row=r, column=i, value=v); c.border = BORDER
        ws.cell(row=r, column=1).fill = PatternFill("solid", fgColor=COLORES[sev]); r += 1
    r += 1
    ws.cell(row=r, column=1, value="Top 10 hallazgos prioritarios").font = Font(bold=True, size=12); r += 1
    encabezado(ws, ["ID", "Severidad", "Área", "Hallazgo", "Ahorro est. (ms)", "Ahorro est. (KB)", "Dispositivo"], fila=r); r += 1
    for h in hallazgos[:10]:
        for i, v in enumerate([h[0], h[7], h[4], h[6], h[10], h[11], h[2]], 1):
            ws.cell(row=r, column=i, value=v).border = BORDER
        ws.cell(row=r, column=2).fill = PatternFill("solid", fgColor=COLORES[h[7]]); r += 1
    ajustar(ws, [45, 14, 22, 55, 16, 16, 14])
    ws.freeze_panes = None

    # ===== Hoja Core Web Vitals =====
    ws = wb.create_sheet("Core Web Vitals")
    cols = ["URL", "Dispositivo", "Métrica", "Core Web Vital", "Valor", "Unidad", "Bueno (≤)", "Pobre (>)", "Estado", "Valor mostrado", "Fuente"]
    encabezado(ws, cols)
    for m in metricas_rows:
        ws.append(m)
    n = ws.max_row
    for row in ws.iter_rows(min_row=2, max_row=n):
        for c in row: c.border = BORDER
    pintar_estado(ws, "I", n)
    if crux_rows:
        ws.append([]); ws.append(["Datos de campo (Chrome UX Report)"]); ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
        f = ws.max_row + 1
        encabezado(ws, ["URL", "Métrica", "p75", "Unidad", "Bueno (≤)", "Pobre (>)", "Estado", "Categoría CrUX", "Fuente"], fila=f)
        for c in crux_rows: ws.append(c)
        pintar_estado(ws, "G", ws.max_row, fila_ini=f + 1)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{n}"
    ajustar(ws, [45, 12, 48, 14, 12, 8, 10, 10, 18, 16, 24])

    # ===== Hoja Hallazgos =====
    ws = wb.create_sheet("Hallazgos")
    cols = ["ID", "URL", "Dispositivo", "Categoría LH", "Área", "Auditoría (id)", "Hallazgo", "Severidad", "Prioridad",
            "Puntaje (0-100)", "Ahorro est. (ms)", "Ahorro est. (KB)", "Valor / evidencia", "Descripción", "Recomendación",
            "Elementos afectados", "Esfuerzo", "Estado", "Responsable / notas"]
    encabezado(ws, cols)
    for h in hallazgos:
        ws.append(h)
    n = ws.max_row
    for row in ws.iter_rows(min_row=2, max_row=n):
        for c in row:
            c.border = BORDER; c.alignment = Alignment(vertical="top", wrap_text=True)
    pintar_estado(ws, "H", n)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{n}"
    ajustar(ws, [8, 36, 11, 14, 14, 28, 42, 11, 9, 10, 11, 11, 22, 60, 60, 10, 10, 11, 24])

    # ===== Hoja Detalle =====
    ws = wb.create_sheet("Detalle")
    cols = ["ID hallazgo", "Auditoría", "URL página", "Dispositivo", "Recurso / elemento", "Tamaño (KB)", "Desperdicio (KB)",
            "Desperdicio (ms)", "Bloqueo (ms)", "Duración (ms)"]
    encabezado(ws, cols)
    for d in detalle: ws.append(d)
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for c in row: c.border = BORDER
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{ws.max_row}"
    ajustar(ws, [11, 28, 36, 11, 80, 12, 14, 14, 12, 12])

    # ===== Hoja Recursos =====
    ws = wb.create_sheet("Recursos")
    cols = ["URL página", "Dispositivo", "Recurso", "Tipo", "MIME", "Transferido (KB)", "Tamaño (KB)", "Tiempo (ms)",
            "Protocolo", "Prioridad", "Estado HTTP", "Preload"]
    encabezado(ws, cols)
    recursos.sort(key=lambda x: -x[5])
    for rr in recursos: ws.append(rr)
    n = ws.max_row
    for row in ws.iter_rows(min_row=2, max_row=n):
        for c in row: c.border = BORDER
    if n > 1:
        ws.conditional_formatting.add(f"F2:F{n}", CellIsRule(operator="greaterThan", formula=["300"], fill=PatternFill("solid", fgColor="FFC7CE")))
        ws.conditional_formatting.add(f"I2:I{n}", FormulaRule(formula=['OR(I2="http/1.1",I2="http/1.0")'], fill=PatternFill("solid", fgColor="FFEB9C")))
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{n}"
    ajustar(ws, [36, 11, 80, 12, 24, 14, 12, 11, 10, 11, 10, 8])

    # ===== Hoja Checklist =====
    ws = wb.create_sheet("Checklist")
    cols = ["Área", "Punto de control", "Auditorías relacionadas", "Resultado", "Evidencia / comentario"]
    encabezado(ws, cols)
    ids_fallidos = {h[5] for h in hallazgos}
    ids_evaluados = {aid for inf in informes for aid, a in inf["lh"].get("audits", {}).items()
                     if a.get("scoreDisplayMode") not in ("notApplicable", "manual", "error")}
    AEO_IDS = ["aeo:title", "aeo:description", "aeo:headings", "aeo:tldr", "aeo:answer-first", "aeo:faq", "aeo:jsonld", "aeo:fresh",
               "aeo:links", "aeo:alt", "aeo:lang", "aeo:canonical", "aeo:index", "aeo:robots", "aeo:llms", "aeo:sitemap", "aeo:thin", "aeo:og"]
    if any(str(h[5]).startswith("aeo:") for h in hallazgos):  # corrió aeo_site_checks.py → todas sus reglas cuentan como evaluadas
        ids_evaluados |= set(AEO_IDS)
    CHECK = [
        # Sección 12 del artículo (checklist práctico) + §10 accesibilidad + §11 medición
        ("Imágenes", "Se identificó la imagen LCP real (no todas las del primer pliegue)", ["largest-contentful-paint-element", "lcp-discovery-insight"]),
        ("Imágenes", "La imagen LCP tiene trato preferente: eager + fetchpriority=high / preload, descubrible en el HTML", ["prioritize-lcp-image", "lcp-lazy-loaded"]),
        ("Imágenes", "No todas las imágenes above-the-fold son fetchpriority=high (si todo es importante, nada lo es)", []),
        ("Imágenes", "Se sirve el tamaño correcto para el viewport (srcset/sizes, formatos modernos, peso)", ["uses-responsive-images", "uses-optimized-images", "modern-image-formats", "image-delivery-insight"]),
        ("Imágenes", "Lazy-load solo en imágenes realmente fuera de pantalla", ["offscreen-images"]),
        ("Imágenes", "Carruseles: no se montan ni cargan todas las slides de entrada; carga no atada a la slide activa", []),
        ("Imágenes", "Placeholders estáticos; no se animan slides ocultas; se respeta prefers-reduced-motion", []),
        ("LCP", "LCP ≤ 2,5 s en móvil", ["largest-contentful-paint"]),
        ("LCP", "Nada innecesario compite con el LCP: fuentes, terceros, iframes, otras imágenes, JS", ["render-blocking-resources", "lcp-breakdown-insight", "lcp-phases-insight", "critical-request-chains"]),
        ("LCP", "Fuentes: preload solo de la fuente principal; font-display: swap; sin preload de fuentes secundarias", ["font-display", "font-display-insight", "uses-rel-preload"]),
        ("Terceros", "Scripts de terceros fuera de la ruta crítica de renderizado", ["third-party-summary", "third-parties-insight", "render-blocking-resources"]),
        ("Terceros", "Patrón load → idle → interacción (requestIdleCallback con timeout) en vez de cargar todo al inicio", ["third-party-summary", "bootup-time"]),
        ("Terceros", "Escape hatch: si el usuario pide la funcionalidad (clic en chat, mapa), se carga de inmediato", []),
        ("Iframes", "Los iframes no bloquean la página: src se asigna al acercarse (IntersectionObserver) o por intención del usuario", ["third-party-facades"]),
        ("Iframes", "Cada iframe tiene una caja dimensionada antes de tener src (sin CLS al cargar)", ["layout-shift-elements", "cls-culprits-insight"]),
        ("JavaScript", "Overlays, drawers, galerías y lightboxes se importan dinámicamente al abrirse, no en la carga inicial", ["unused-javascript", "bootup-time"]),
        ("JavaScript", "Estados de carga ligeros: skeletons con CSS, no con componentes pesados", []),
        ("JavaScript", "Secciones bajo el pliegue en chunks separados; contenido del primer pliegue y SEO sincrónico", ["unused-javascript"]),
        ("JavaScript", "Sin trabajo innecesario durante la hidratación; animaciones por interacción, no al arrancar", ["mainthread-work-breakdown", "long-tasks", "total-blocking-time"]),
        ("JavaScript", "TBT ≤ 200 ms (proxy de INP) y sin tareas largas > 50 ms", ["total-blocking-time", "long-tasks"]),
        ("Layout (CLS)", "CLS ≤ 0,1", ["cumulative-layout-shift"]),
        ("Layout (CLS)", "Se reserva espacio antes de que llegue el contenido asíncrono (imágenes con dimensiones, iframes, banners)", ["unsized-images", "layout-shift-elements", "layout-shifts"]),
        ("Layout (CLS)", "La geometría del skeleton coincide con la UI final (aspect-ratio, grid igual al definitivo)", []),
        ("Layout (CLS)", "Servidor y cliente toman la misma decisión de layout (sin remontar desktop→mobile tras hidratar)", []),
        ("Layout (CLS)", "No se remonta contenido innecesariamente", []),
        ("Accesibilidad", "Botones de solo ícono con etiqueta accesible; sin aria-label redundantes", ["button-name", "link-name"]),
        ("Accesibilidad", "role=status en estados de carga; inert en contenido montado pero no interactivo; role=presentation donde corresponde", []),
        ("Accesibilidad", "Se respeta prefers-reduced-motion en animaciones y placeholders", []),
        ("Medición", "Se midió antes de optimizar e identificó el cuello de botella real (no por suposición)", []),
        ("Medición", "Un cambio significativo a la vez; se vuelve a medir; se revierte si no mejora", []),
        ("Medición", "Se usan datos de laboratorio y de usuarios reales (RUM / CrUX)", []),
        ("Red y caché", "Compresión, caché larga en assets, HTTP/2-3, sin redirecciones (higiene base)", ["uses-text-compression", "uses-long-cache-ttl", "uses-http2", "redirects"]),
        # SEO / AEO: lo que Google y los motores de respuesta buscan (reglas tipo seodraft aplicadas a la página)
        ("SEO / AEO", "Title 15–60 y meta description 50–160, únicos por página", ["document-title", "meta-description", "aeo:title", "aeo:description"]),
        ("SEO / AEO", "Un solo H1; H2/H3 sin saltos de nivel; encabezados como la pregunta que el lector escribiría", ["heading-order", "aeo:headings"]),
        ("SEO / AEO", "TL;DR / respuesta directa autocontenida (100–400 caracteres) bajo el H1", ["aeo:tldr"]),
        ("SEO / AEO", "Cada sección responde en su primera frase y sobrevive extraída sola (sin 'como vimos arriba')", ["aeo:answer-first"]),
        ("SEO / AEO", "≥ 3 FAQs citables (respuesta ≤ 500 caracteres) marcadas con FAQPage", ["aeo:faq"]),
        ("SEO / AEO", "JSON-LD válido: Article/BlogPosting con author, datePublished y dateModified; Organization/WebSite", ["structured-data", "aeo:jsonld"]),
        ("SEO / AEO", "Frescura: dateModified real y contenido revisado en los últimos 12 meses", ["aeo:fresh", "seodraft:stale-post", "seodraft:missing-updated-date"]),
        ("SEO / AEO", "≥ 2 enlaces internos relevantes, ninguno roto; sin páginas huérfanas; sin canibalización entre URLs", ["crawlable-anchors", "aeo:links", "seodraft:broken-internal-link", "seodraft:orphan-page", "seodraft:cannibalization"]),
        ("SEO / AEO", "Imágenes con alt; lang en <html>; canonical correcto; sin noindex accidental", ["image-alt", "html-has-lang", "canonical", "is-crawlable", "aeo:alt", "aeo:lang", "aeo:canonical", "aeo:index"]),
        ("SEO / AEO", "robots.txt con Sitemap, decisión explícita sobre bots de IA (GPTBot, OAI-SearchBot, ClaudeBot, PerplexityBot, Google-Extended); llms.txt publicado", ["robots-txt", "aeo:robots", "aeo:llms", "aeo:sitemap"]),
        ("SEO / AEO", "Contenido no delgado (≥ 500 palabras en artículos) y sin fuentes inventadas", ["aeo:thin", "seodraft:thin-content"]),
    ]
    for area, punto, ids in CHECK:
        if any(i in ids_fallidos for i in ids):
            res = "No cumple"
        elif ids and any(i in ids_evaluados for i in ids):
            res = "Cumple"
        else:
            res = "Revisar manualmente"
        ws.append([area, punto, ", ".join(ids), res, ""])
    n = ws.max_row
    for row in ws.iter_rows(min_row=2, max_row=n):
        for c in row: c.border = BORDER
    for k, color in {"No cumple": "FFC7CE", "Cumple": "C6EFCE", "Revisar manualmente": "FFEB9C"}.items():
        ws.conditional_formatting.add(f"D2:D{n}", CellIsRule(operator="equal", formula=[f'"{k}"'], fill=PatternFill("solid", fgColor=color)))
    ws.auto_filter.ref = f"A1:E{n}"
    ajustar(ws, [16, 60, 50, 20, 50])

    # ===== Hoja Antes vs Después (opcional, §11 del artículo: medir el resultado) =====
    if antes:
        ws = wb.create_sheet("Antes vs Después")
        encabezado(ws, ["Dispositivo", "Métrica", "Antes", "Después", "Diferencia", "Mejora %", "Unidad", "Estado después"])
        def _kpis(inf):
            au = inf["lh"].get("audits", {})
            k = [("Puntaje rendimiento", round((inf["lh"].get("categories", {}).get("performance", {}).get("score") or 0) * 100), "pts", None, None, True)]
            for aid, nombre, unidad, bueno, pobre, _ in METRICAS:
                a = au.get(aid)
                if a and a.get("numericValue") is not None:
                    v = a["numericValue"]; k.append((nombre, round(v, 3) if unidad == "" else round(v), unidad, bueno, pobre, False))
            nr = au.get("network-requests", {}).get("details", {}).get("items", []) or []
            k.append(("JS inicial transferido", round(sum((r.get("transferSize") or 0) for r in nr if r.get("resourceType") == "Script") / 1024), "KB", None, None, False))
            k.append(("Peso total transferido", round(sum((r.get("transferSize") or 0) for r in nr) / 1024), "KB", None, None, False))
            k.append(("Nº de peticiones", len(nr), "", None, None, False))
            return k
        despues_por_ff = {inf["ff"]: inf for inf in informes}
        for a_inf in antes:
            d_inf = despues_por_ff.get(a_inf["ff"])
            if not d_inf:
                continue
            kd = {x[0]: x for x in _kpis(d_inf)}
            for nombre, va, unidad, bueno, pobre, mayor_mejor in _kpis(a_inf):
                if nombre not in kd:
                    continue
                vd = kd[nombre][1]
                diff = vd - va
                mejora = ((vd - va) / va * 100) if (mayor_mejor and va) else ((va - vd) / va * 100 if va else 0)
                est = estado(vd, bueno, pobre) if bueno is not None else ""
                ws.append([a_inf["ff"], nombre, va, vd, round(diff, 3), round(mejora, 1), unidad, est])
        n = ws.max_row
        for row in ws.iter_rows(min_row=2, max_row=n):
            for c in row: c.border = BORDER
        if n > 1:
            ws.conditional_formatting.add(f"F2:F{n}", CellIsRule(operator="greaterThan", formula=["0"], fill=PatternFill("solid", fgColor="C6EFCE")))
            ws.conditional_formatting.add(f"F2:F{n}", CellIsRule(operator="lessThan", formula=["0"], fill=PatternFill("solid", fgColor="FFC7CE")))
            pintar_estado(ws, "H", n)
        ajustar(ws, [12, 48, 12, 12, 12, 11, 8, 18])

    wb.save(out)
    return len(hallazgos), len(recursos)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("informes", nargs="*", help="JSON de Lighthouse o de PageSpeed Insights")
    ap.add_argument("--manual", nargs="*", default=[], help="JSON de hallazgos manuales (lista, o {hallazgos:[...]} de collect_browser/aeo_site_checks); se fusionan")
    ap.add_argument("--seodraft", nargs="*", default=[], help="JSON de salida de `seodraft audit` o `seodraft gate` (failures/advisories)")
    ap.add_argument("--out", default="reporte-rendimiento.xlsx")
    ap.add_argument("--sitio", default="")
    ap.add_argument("--antes", nargs="*", default=[], help="JSON de Lighthouse de la línea base (genera hoja Antes vs Después)")
    a = ap.parse_args()
    informes = [cargar(p) for p in a.informes]
    manuales = []
    for p in a.manual:
        raw = json.load(open(p, encoding="utf-8"))
        manuales += raw["hallazgos"] if isinstance(raw, dict) else raw
    for p in a.seodraft:
        manuales += importar_seodraft(json.load(open(p, encoding="utf-8")))
    n_h, n_r = construir(informes, manuales, a.out, a.sitio, antes=[cargar(p) for p in a.antes])
    print(f"OK → {a.out}: {n_h} hallazgos, {n_r} recursos, {len(informes)} informes")
```

## Script 2 — `collect_browser.js` (ejecutar en la página cargada)

```javascript
// Recolector de señales de rendimiento desde el navegador (fallback sin Lighthouse).
// Ejecutar en la página cargada (Claude in Chrome javascript_tool, DevTools o Playwright page.evaluate).
// Devuelve { metricas, recursos, hallazgos } donde `hallazgos` es compatible con --manual del generador Excel.
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const url = location.href, origen = location.origin;
  const nav = performance.getEntriesByType("navigation")[0] || {};
  const paint = Object.fromEntries(performance.getEntriesByType("paint").map((p) => [p.name, Math.round(p.startTime)]));

  // LCP y CLS vía PerformanceObserver (buffered). INP real requiere interacción del usuario.
  let lcp = 0, cls = 0, longTasks = [], lcpEl = null;
  try {
    new PerformanceObserver((l) => l.getEntries().forEach((e) => { lcp = Math.round(e.startTime); lcpEl = e.element || lcpEl; })).observe({ type: "largest-contentful-paint", buffered: true });
    new PerformanceObserver((l) => l.getEntries().forEach((e) => { if (!e.hadRecentInput) cls += e.value; })).observe({ type: "layout-shift", buffered: true });
    new PerformanceObserver((l) => l.getEntries().forEach((e) => longTasks.push(Math.round(e.duration)))).observe({ type: "longtask", buffered: true });
  } catch (_) {}
  await sleep(1500);

  const res = performance.getEntriesByType("resource").map((r) => ({
    url: r.name, tipo: r.initiatorType, transferidoKB: +(r.transferSize / 1024).toFixed(1),
    tamanoKB: +(r.decodedBodySize / 1024).toFixed(1), duracionMs: Math.round(r.duration),
    protocolo: r.nextHopProtocol, tercero: !r.name.startsWith(origen), renderBloqueante: r.renderBlockingStatus === "blocking",
  }));
  const pesoTotalKB = Math.round(res.reduce((s, r) => s + r.transferidoKB, 0));
  const terceros = [...new Set(res.filter((r) => r.tercero).map((r) => new URL(r.url).host))];

  const H = [];
  const add = (categoria, titulo, severidad, descripcion, recomendacion, evidencia, esfuerzo = "Medio") =>
    H.push({ url, categoria, titulo, severidad, descripcion, recomendacion, evidencia: String(evidencia).slice(0, 400), esfuerzo });

  // --- Métricas ---
  const ttfb = Math.round(nav.responseStart || 0);
  if (ttfb > 800) add("Red y caché", "TTFB alto", ttfb > 1800 ? "Crítico" : "Alto", `TTFB de ${ttfb} ms (objetivo ≤ 800 ms).`, "Caché en CDN/servidor, SSR/ISR, optimizar backend, HTTP/2-3.", `responseStart=${ttfb}`);
  if (lcp > 2500) add("Renderizado", "LCP fuera de objetivo", lcp > 4000 ? "Crítico" : "Alto", `LCP de ${lcp} ms (objetivo ≤ 2500 ms).`, "Priorizar el recurso LCP (preload, fetchpriority=high), reducir bloqueantes y TTFB.", `LCP=${lcp}`);
  if (cls > 0.1) add("Renderizado", "CLS fuera de objetivo", cls > 0.25 ? "Crítico" : "Alto", `CLS de ${cls.toFixed(3)} (objetivo ≤ 0.1).`, "Reservar espacio a imágenes/ads/embeds, font-display + size-adjust, no insertar contenido sobre el existente.", `CLS=${cls.toFixed(3)}`);
  const tbt = longTasks.reduce((s, d) => s + Math.max(0, d - 50), 0);
  if (tbt > 200) add("JavaScript", "Tareas largas bloquean el hilo principal", tbt > 600 ? "Crítico" : "Alto", `${longTasks.length} tareas largas, TBT≈${tbt} ms.`, "Code splitting, fragmentar tareas, diferir hidratación, Web Workers.", longTasks.join(","));

  // --- Ruta crítica ---
  const scriptsBloq = [...document.querySelectorAll("head script[src]:not([async]):not([defer]):not([type=module])")].map((s) => s.src);
  if (scriptsBloq.length) add("JavaScript", "Scripts bloqueantes en <head>", "Alto", `${scriptsBloq.length} script(s) síncronos en el head.`, "Añadir defer/async o mover al final del body.", scriptsBloq.join("\n"));
  const cssBloq = res.filter((r) => r.renderBloqueante);
  if (cssBloq.length > 2) add("CSS", "Múltiples hojas de estilo bloqueantes", "Medio", `${cssBloq.length} recursos bloquean el renderizado.`, "Inline del CSS crítico, combinar hojas, cargar el resto de forma asíncrona.", cssBloq.map((r) => r.url).join("\n"));
  const preconnect = document.querySelectorAll('link[rel=preconnect],link[rel=dns-prefetch]').length;
  if (terceros.length > 2 && preconnect === 0) add("Red y caché", "Sin preconnect a orígenes de terceros", "Bajo", `${terceros.length} orígenes externos sin preconnect.`, "Añadir <link rel=preconnect> a los 2-4 orígenes más críticos.", terceros.join(", "), "Bajo");

  // --- Imágenes ---
  const imgs = [...document.images];
  const sinDim = imgs.filter((i) => !i.getAttribute("width") || !i.getAttribute("height")).filter((i) => getComputedStyle(i).aspectRatio === "auto");
  if (sinDim.length) add("Imágenes", "Imágenes sin dimensiones explícitas", sinDim.length > 3 ? "Alto" : "Medio", `${sinDim.length} imágenes sin width/height ni aspect-ratio (riesgo de CLS).`, "Declarar width/height o aspect-ratio.", sinDim.slice(0, 8).map((i) => i.currentSrc || i.src).join("\n"), "Bajo");
  const bajoPliegue = imgs.filter((i) => i.getBoundingClientRect().top > innerHeight && i.loading !== "lazy");
  if (bajoPliegue.length) add("Imágenes", "Imágenes fuera de pantalla sin lazy loading", "Medio", `${bajoPliegue.length} imágenes bajo el pliegue se cargan de inmediato.`, 'Añadir loading="lazy" (nunca en la imagen LCP).', bajoPliegue.slice(0, 8).map((i) => i.currentSrc || i.src).join("\n"), "Bajo");
  const formatosViejos = res.filter((r) => /\.(jpe?g|png|gif)(\?|$)/i.test(r.url) && r.transferidoKB > 50);
  if (formatosViejos.length) add("Imágenes", "Imágenes pesadas en formatos no modernos", formatosViejos.some((r) => r.transferidoKB > 300) ? "Alto" : "Medio", `${formatosViejos.length} imágenes JPG/PNG/GIF > 50 KB.`, "Servir AVIF/WebP con <picture> o CDN de imágenes; comprimir.", formatosViejos.map((r) => `${r.url} (${r.transferidoKB} KB)`).join("\n"), "Bajo");
  const sinSrcset = imgs.filter((i) => i.naturalWidth > 1.5 * i.getBoundingClientRect().width * devicePixelRatio && !i.srcset && i.getBoundingClientRect().width > 0);
  if (sinSrcset.length) add("Imágenes", "Imágenes sobredimensionadas sin srcset", "Medio", `${sinSrcset.length} imágenes se sirven mucho más grandes que su tamaño renderizado.`, "Usar srcset + sizes.", sinSrcset.slice(0, 8).map((i) => `${i.currentSrc} ${i.naturalWidth}px → ${Math.round(i.getBoundingClientRect().width)}px`).join("\n"), "Bajo");

  // --- §3 Imágenes: LCP real, loading vs fetchPriority, prioridad en todas partes ---
  const desc = (el) => el ? `<${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""}${el.className && typeof el.className === "string" ? "." + el.className.trim().split(/\s+/).slice(0, 2).join(".") : ""}> ${el.currentSrc || el.src || ""}`.trim() : "";
  const lcpDesc = desc(lcpEl);
  if (lcpEl && lcpEl.tagName === "IMG") {
    if (lcpEl.loading === "lazy") add("Imágenes", "La imagen LCP tiene loading=\"lazy\"", "Crítico", "El elemento LCP real se difiere; retrasa directamente el LCP.", 'Usar loading="eager" + fetchpriority="high" (o priority en next/image) solo en la imagen LCP.', lcpDesc, "Bajo");
    else if (lcpEl.getAttribute("fetchpriority") !== "high") add("Imágenes", "La imagen LCP no tiene fetchpriority=\"high\"", "Medio", "La imagen LCP compite en igualdad con el resto de recursos.", 'Añadir fetchpriority="high" (y preload si se descubre tarde) únicamente a la imagen LCP.', lcpDesc, "Bajo");
  }
  if (lcpEl && lcpEl.tagName !== "IMG" && getComputedStyle(lcpEl).backgroundImage !== "none") add("Imágenes", "LCP es un background-image CSS", "Alto", "El navegador descubre la imagen LCP tarde (tras el CSS), no desde el HTML.", "Usar <img> con fetchpriority=\"high\" o <link rel=preload as=image>.", lcpDesc, "Medio");
  const altaPrio = imgs.filter((i) => i.getAttribute("fetchpriority") === "high");
  if (altaPrio.length > 1) add("Imágenes", "fetchpriority=\"high\" en varias imágenes", "Medio", `${altaPrio.length} imágenes con prioridad alta compiten entre sí; si todo es importante, nada lo es.`, "Dejar fetchpriority=\"high\" solo en la imagen LCP; el resto a auto/low.", altaPrio.map((i) => i.currentSrc || i.src).join("\n"), "Bajo");
  const slidesFuera = imgs.filter((i) => { const r = i.getBoundingClientRect(); return (r.left >= innerWidth || r.right <= 0) && r.top < innerHeight && i.loading !== "lazy" && i.complete; });
  if (slidesFuera.length) add("Imágenes", "Slides de carrusel fuera de pantalla cargadas de inmediato", "Medio", `${slidesFuera.length} imágenes a la izquierda/derecha del viewport (carrusel) se descargan en la carga inicial.`, "Montar/cargar slides bajo demanda; la primera slide no es automáticamente el hero; no atar la carga a la slide activa.", slidesFuera.slice(0, 8).map((i) => i.currentSrc || i.src).join("\n"), "Medio");
  const animFuera = (document.getAnimations ? document.getAnimations() : []).filter((a) => { const t = a.effect && a.effect.target; if (!t || !t.getBoundingClientRect) return false; const r = t.getBoundingClientRect(); return a.playState === "running" && (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth || r.width === 0); });
  if (animFuera.length) add("Renderizado", "Animaciones corriendo en elementos no visibles", "Bajo", `${animFuera.length} animaciones activas fuera del viewport u ocultas (placeholders/slides) consumen CPU.`, "Placeholder estático por defecto; animar solo cerca del viewport; respetar prefers-reduced-motion.", animFuera.slice(0, 5).map((a) => desc(a.effect.target)).join("\n"), "Bajo");

  // --- §4.1 Fuentes: preload solo de la principal ---
  const preloadFonts = [...document.querySelectorAll('link[rel=preload][as=font]')].map((l) => l.href);
  if (preloadFonts.length > 1) add("Fuentes", "Varias fuentes precargadas", "Medio", `${preloadFonts.length} preloads de fuentes compiten por ancho de banda temprano con el recurso LCP.`, "Mantener preload solo para la fuente principal de UI; quitar el de fuentes secundarias/decorativas.", preloadFonts.join("\n"), "Bajo");

  // --- §6 / §8.3 Iframes: caja antes que src ---
  const ifr = [...document.querySelectorAll("iframe")];
  const ifrSinCaja = ifr.filter((f) => !(f.getAttribute("width") && f.getAttribute("height")) && getComputedStyle(f).aspectRatio === "auto" && !(f.parentElement && getComputedStyle(f.parentElement).aspectRatio !== "auto"));
  if (ifrSinCaja.length) add("Terceros", "Iframes sin caja dimensionada", "Alto", `${ifrSinCaja.length} iframes sin width/height ni aspect-ratio: al cargar desplazan el layout (CLS).`, "Renderizar un placeholder con el tamaño final y asignar src después (IntersectionObserver o intención del usuario).", ifrSinCaja.map((f) => f.src || desc(f)).join("\n"), "Bajo");
  const ifrInicio = ifr.filter((f) => f.src && !/^about:/.test(f.src) && f.loading !== "lazy");
  if (ifrInicio.length) add("Terceros", "Iframes con src en la carga inicial", "Medio", `${ifrInicio.length} documentos embebidos (mapas, video, widgets) compiten con el contenido crítico.`, "Diferir: placeholder → load/idle → observar → asignar src al acercarse; cargar de inmediato si el usuario lo pide.", ifrInicio.map((f) => f.src).join("\n"), "Medio");

  // --- §10 Accesibilidad sin regresiones ---
  const btnSinNombre = [...document.querySelectorAll("button, a[href]")].filter((b) => !b.textContent.trim() && !b.getAttribute("aria-label") && !b.getAttribute("aria-labelledby") && !b.getAttribute("title") && !b.querySelector("img[alt]:not([alt=''])"));
  if (btnSinNombre.length) add("Accesibilidad", "Botones/enlaces de solo ícono sin nombre accesible", "Medio", `${btnSinNombre.length} controles sin texto ni aria-label.`, "Añadir aria-label (o texto visualmente oculto); evitar aria-label redundante donde ya hay texto visible.", btnSinNombre.slice(0, 8).map(desc).join("\n"), "Bajo");
  const ariaRedundante = [...document.querySelectorAll("[aria-label]")].filter((e) => e.textContent.trim() && e.getAttribute("aria-label").trim().toLowerCase() === e.textContent.trim().toLowerCase());
  if (ariaRedundante.length) add("Accesibilidad", "aria-label redundantes", "Bajo", `${ariaRedundante.length} elementos con aria-label idéntico a su texto visible.`, "Eliminar el aria-label cuando el texto visible ya describe el control.", ariaRedundante.slice(0, 5).map(desc).join("\n"), "Bajo");
  const noReduce = (() => { try { for (const ss of document.styleSheets) for (const r of ss.cssRules) if (r.media && /prefers-reduced-motion/.test(r.media.mediaText)) return false; } catch (_) {} return (document.getAnimations ? document.getAnimations().length : 0) > 0; })();
  if (noReduce) add("Accesibilidad", "Animaciones sin prefers-reduced-motion", "Bajo", "Hay animaciones activas y ninguna hoja de estilo accesible declara @media (prefers-reduced-motion).", "Desactivar o reducir animaciones y placeholders animados bajo prefers-reduced-motion: reduce.", "", "Bajo");

  // --- Fuentes ---
  const fontFaces = [];
  for (const ss of document.styleSheets) { try { for (const r of ss.cssRules) if (r instanceof CSSFontFaceRule) fontFaces.push(r); } catch (_) {} }
  const sinDisplay = fontFaces.filter((r) => !r.style.getPropertyValue("font-display"));
  if (sinDisplay.length) add("Fuentes", "@font-face sin font-display", "Medio", `${sinDisplay.length} declaraciones sin font-display (texto invisible / FOIT).`, "font-display: swap u optional; preload de la fuente principal.", sinDisplay.map((r) => r.style.getPropertyValue("font-family")).join(", "), "Bajo");
  const fuentesKB = res.filter((r) => /\.(woff2?|ttf|otf)(\?|$)/i.test(r.url)).reduce((s, r) => s + r.transferidoKB, 0);
  if (fuentesKB > 200) add("Fuentes", "Peso de fuentes elevado", "Medio", `${Math.round(fuentesKB)} KB en fuentes.`, "Subsetting, WOFF2, limitar variantes/pesos, fuentes variables.", `${Math.round(fuentesKB)} KB`, "Bajo");

  // --- Red / caché / peso ---
  if (pesoTotalKB > 1500) add("Red y caché", "Peso total de página elevado", pesoTotalKB > 3000 ? "Crítico" : "Alto", `${pesoTotalKB} KB transferidos.`, "Reducir imágenes, bundles y fuentes; code splitting; lazy loading.", `${pesoTotalKB} KB`);
  const http1 = res.filter((r) => /^http\/1/.test(r.protocolo));
  if (http1.length) add("Red y caché", "Recursos servidos por HTTP/1.x", "Medio", `${http1.length} recursos sin HTTP/2 o HTTP/3.`, "Habilitar HTTP/2-3 en servidor/CDN y en orígenes de terceros.", [...new Set(http1.map((r) => new URL(r.url).host))].join(", "));
  const jsKB = res.filter((r) => r.tipo === "script").reduce((s, r) => s + r.transferidoKB, 0);
  if (jsKB > 500) add("JavaScript", "Volumen de JavaScript elevado", jsKB > 1000 ? "Crítico" : "Alto", `${Math.round(jsKB)} KB de JS transferidos.`, "Code splitting, tree shaking, eliminar librerías, diferir terceros.", `${Math.round(jsKB)} KB`, "Alto");
  if (terceros.length > 5) add("Terceros", "Muchos orígenes de terceros", "Medio", `${terceros.length} orígenes externos.`, "Auditar y diferir terceros, facades, cargar tras consentimiento.", terceros.join(", "));

  // --- DOM / render ---
  const nodos = document.getElementsByTagName("*").length;
  if (nodos > 1500) add("Renderizado", "DOM excesivo", nodos > 3000 ? "Alto" : "Medio", `${nodos} nodos DOM.`, "Virtualización de listas, eliminar wrappers, paginar.", `${nodos} nodos`);
  if (!document.querySelector('meta[name=viewport]')) add("Renderizado", "Falta meta viewport", "Alto", "No hay meta viewport.", 'Añadir <meta name="viewport" content="width=device-width, initial-scale=1">.', "", "Bajo");
  const iframes = [...document.querySelectorAll("iframe:not([loading=lazy])")];
  if (iframes.length) add("Terceros", "Iframes sin lazy loading", "Bajo", `${iframes.length} iframes cargan de inmediato.`, 'loading="lazy" o facade al interactuar.', iframes.map((f) => f.src).join("\n"), "Bajo");

  return {
    metricas: { url, lcpElemento: lcpDesc, ttfbMs: ttfb, fcpMs: paint["first-contentful-paint"] || null, lcpMs: lcp || null, cls: +cls.toFixed(3), tbtAproxMs: tbt, domNodos: nodos, pesoTotalKB, jsKB: Math.round(jsKB), fuentesKB: Math.round(fuentesKB), nRecursos: res.length, terceros },
    recursos: res.sort((a, b) => b.transferidoKB - a.transferidoKB).slice(0, 100),
    hallazgos: H,
  };
})();
```

## Script 3 — `run_collect.js` (runner Playwright para el Script 2)

```javascript
// Uso: node run_collect.js <url> <salida.json>   (Playwright + collect_browser.js)
const { chromium } = require("playwright"); const fs = require("fs");
(async () => {
  const [url, out = "browser-collect.json"] = process.argv.slice(2);
  const b = await chromium.launch(); const ctx = await b.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.6, isMobile: true });
  const p = await ctx.newPage(); await p.goto(url, { waitUntil: "networkidle" });
  const r = await p.evaluate(fs.readFileSync(__dirname + "/collect_browser.js", "utf8"));
  fs.writeFileSync(out, JSON.stringify(r, null, 2)); fs.writeFileSync(out.replace(/\.json$/, "-hallazgos.json"), JSON.stringify(r.hallazgos, null, 2));
  console.log(JSON.stringify(r.metricas), "\nhallazgos:", r.hallazgos.length); await b.close();
})();
```

## Script 4 — `aeo_site_checks.py` (SEO/AEO sobre la URL, solo stdlib)

```python
#!/usr/bin/env python3
"""
Comprobaciones SEO / AEO deterministas sobre una URL pública (sin navegador,
solo stdlib): lo que Google y los motores de respuesta (ChatGPT, Perplexity,
AI Overviews) buscan en una página. Reglas inspiradas en seodraft
(gate/audit) aplicadas al HTML servido, más rastreabilidad por bots de IA.

Uso:
  python3 aeo_site_checks.py <url> [--out hallazgos-aeo.json] [--min-words 500]
Salida: JSON con {metricas, hallazgos} — `hallazgos` es compatible con --manual
del generador de Excel (perf_report_xlsx.py).
"""
import sys, json, re, argparse, html, datetime
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.parse import urlparse, urljoin
from urllib.error import URLError, HTTPError

UA = "Mozilla/5.0 (compatible; auditoria-rendimiento-frontend/1.0)"
BOTS_IA = ["GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "anthropic-ai", "PerplexityBot",
           "Google-Extended", "Bytespider", "CCBot", "Applebot-Extended", "meta-externalagent"]

def get(url, timeout=20):
    try:
        with urlopen(Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"}), timeout=timeout) as r:
            return r.status, r.read().decode(r.headers.get_content_charset() or "utf-8", "ignore"), dict(r.headers)
    except HTTPError as e:
        return e.code, "", {}
    except (URLError, Exception) as e:
        return None, str(e), {}

class P(HTMLParser):
    """Extrae lo necesario del HTML: meta, headings, enlaces, imágenes, JSON-LD, texto."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""; self.meta = {}; self.links_rel = {}; self.headings = []; self.a = []; self.imgs = []
        self.jsonld = []; self.text = []; self.lang = ""; self.ps = []; self._stack = []; self._cur = None
        self._in_jsonld = False; self._skip = 0; self._p = None; self.dates_visibles = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html": self.lang = a.get("lang", "")
        elif tag == "title": self._cur = "title"
        elif tag == "meta":
            k = (a.get("name") or a.get("property") or "").lower()
            if k: self.meta[k] = a.get("content", "")
        elif tag == "link" and a.get("rel"): self.links_rel.setdefault(a["rel"].lower(), []).append(a.get("href", ""))
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"): self._cur = tag; self.headings.append([int(tag[1]), ""])
        elif tag == "a" and a.get("href"): self.a.append(a["href"])
        elif tag == "img": self.imgs.append(a)
        elif tag == "script":
            if (a.get("type") or "").lower().strip() == "application/ld+json": self._in_jsonld = True; self._jl = ""
            else: self._skip += 1
        elif tag in ("style", "noscript", "svg"): self._skip += 1
        elif tag == "p": self._p = ""
        elif tag == "time" and a.get("datetime"): self.dates_visibles.append(a["datetime"])
    def handle_endtag(self, tag):
        if tag in ("title", "h1", "h2", "h3", "h4", "h5", "h6"): self._cur = None
        elif tag == "script":
            if self._in_jsonld:
                self._in_jsonld = False
                try: self.jsonld.append(json.loads(self._jl))
                except Exception: self.jsonld.append({"_invalid": True})
            elif self._skip: self._skip -= 1
        elif tag in ("style", "noscript", "svg") and self._skip: self._skip -= 1
        elif tag == "p" and self._p is not None:
            if self._p.strip(): self.ps.append(self._p.strip())
            self._p = None
    def handle_data(self, d):
        if self._in_jsonld: self._jl += d; return
        if self._skip: return
        if self._cur == "title": self.title += d
        elif self._cur and self._cur.startswith("h"): self.headings[-1][1] += d
        if self._p is not None: self._p += d
        self.text.append(d)

def flatten_ld(objs):
    out = []
    def walk(o):
        if isinstance(o, dict):
            if "@type" in o: out.append(o)
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(objs); return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url"); ap.add_argument("--out", default="hallazgos-aeo.json")
    ap.add_argument("--min-words", type=int, default=500); ap.add_argument("--title-max", type=int, default=60)
    ap.add_argument("--desc-max", type=int, default=160); ap.add_argument("--internal-links-min", type=int, default=2)
    args = ap.parse_args()
    url = args.url; origen = "{0.scheme}://{0.netloc}".format(urlparse(url))
    H = []
    def add(cat, titulo, sev, desc, rec, ev="", esf="Bajo", id="aeo:otro"):
        H.append({"url": url, "id": id, "categoria": cat, "titulo": titulo, "severidad": sev, "descripcion": desc,
                  "recomendacion": rec, "evidencia": str(ev)[:400], "esfuerzo": esf, "form_factor": "Ambos"})

    status, body, hdr = get(url)
    if not body or (status and status >= 400):
        print(json.dumps({"error": f"No se pudo obtener la página (status={status}): {body[:200]}"})); sys.exit(0)
    p = P(); p.feed(body)
    texto = re.sub(r"\s+", " ", " ".join(p.text)).strip(); palabras = len(texto.split())
    ld = flatten_ld(p.jsonld); tipos = [str(o.get("@type")) for o in ld]

    # ---------- SEO básico (reglas estilo seodraft: title/description/h1/headings/links/alt) ----------
    t = p.title.strip()
    if not t: add("SEO", "Falta <title>", "Crítico", "La página no tiene título.", f"Añadir un <title> de 15–{args.title_max} caracteres con el término objetivo.", "", id="aeo:title")
    elif not (15 <= len(t) <= args.title_max): add("SEO", "Longitud de <title> fuera de rango", "Medio", f"{len(t)} caracteres (rango 15–{args.title_max}).", "Reescribir el título a la longitud correcta; no truncar a ciegas.", t, id="aeo:title")
    d = (p.meta.get("description") or "").strip()
    if not d: add("SEO", "Falta meta description", "Alto", "Sin meta description: Google y los motores de respuesta improvisan el resumen.", f"Añadir una description de 50–{args.desc_max} caracteres que responda a la intención.", "", id="aeo:description")
    elif not (50 <= len(d) <= args.desc_max): add("SEO", "Longitud de meta description fuera de rango", "Medio", f"{len(d)} caracteres (rango 50–{args.desc_max}).", "Ajustar la description a la longitud correcta cortando en límite de palabra.", d, id="aeo:description")
    h1 = [h for h in p.headings if h[0] == 1]
    if len(h1) != 1: add("SEO", f"{len(h1)} H1 en la página", "Alto" if len(h1) == 0 else "Medio", "Debe haber exactamente un H1 con el tema principal.", "Dejar un único H1; el resto como H2/H3.", " | ".join(h[1].strip() for h in h1)[:300], id="aeo:headings")
    saltos = [(a[1].strip()[:40], a[0], b[0]) for a, b in zip(p.headings, p.headings[1:]) if b[0] > a[0] + 1]
    if saltos: add("SEO", "Saltos de nivel en encabezados", "Medio", f"{len(saltos)} saltos (p. ej. H2→H4). Rompen el outline que Google y los LLM usan para entender la estructura.", "Corregir la jerarquía: H3 solo bajo H2, sin saltar niveles.", "; ".join(f"'{s[0]}' H{s[1]}→H{s[2]}" for s in saltos[:5]), id="aeo:headings")
    h2 = [h for h in p.headings if h[0] == 2]
    if palabras > 300 and len(h2) < 2: add("AEO", "Menos de 2 H2", "Medio", "Los motores de respuesta citan secciones; sin H2 no hay secciones extraíbles.", "Estructurar el contenido en ≥ 2 secciones H2 con encabezados que sean la pregunta que el lector escribiría.", f"{len(h2)} H2", id="aeo:headings")
    internos = [a for a in p.a if a.startswith("/") and not a.startswith("//") or a.startswith(origen)]
    internos = [a for a in internos if not a.startswith("#")]
    if palabras > 300 and len(set(internos)) < args.internal_links_min: add("SEO", "Pocos enlaces internos", "Medio", f"{len(set(internos))} enlaces internos (mínimo {args.internal_links_min}).", "Enlazar a páginas propias relevantes por tema; evita páginas huérfanas y reparte autoridad.", "", id="aeo:links")
    sin_alt = [i.get("src", "")[:120] for i in p.imgs if i.get("alt") is None and "presentation" not in (i.get("role") or "")]
    if sin_alt: add("SEO", "Imágenes sin atributo alt", "Medio", f"{len(sin_alt)} imágenes sin alt.", "Añadir alt descriptivo (o alt=\"\" si es decorativa).", "\n".join(sin_alt[:6]), id="aeo:alt")
    if not p.lang: add("SEO", "Falta atributo lang en <html>", "Bajo", "Sin lang, buscadores y lectores de pantalla adivinan el idioma.", 'Añadir <html lang="es"> (o el idioma real).', "", id="aeo:lang")
    canon = p.links_rel.get("canonical", [])
    if not canon: add("SEO", "Falta rel=canonical", "Medio", "Sin canonical, variantes de URL (utm, trailing slash, www) compiten entre sí.", "Declarar <link rel=canonical> apuntando a la URL definitiva.", "", id="aeo:canonical")
    elif urlparse(urljoin(url, canon[0])).path.rstrip("/") != urlparse(url).path.rstrip("/"): add("SEO", "Canonical apunta a otra URL", "Alto", "La página declara como canónica otra URL: Google indexará esa y no esta.", "Verificar que sea intencional (p. ej. variante de paginación/filtro); si no, corregir el canonical.", canon[0], id="aeo:canonical")
    robots_meta = (p.meta.get("robots") or "").lower()
    if "noindex" in robots_meta: add("SEO", "Página con noindex", "Crítico", "La página pide no ser indexada: no aparecerá en Google ni será citada por motores que rastrean el índice.", "Quitar noindex si la página debe posicionar.", robots_meta, id="aeo:index")
    if not p.meta.get("og:title") and not p.meta.get("og:description"): add("SEO", "Sin Open Graph", "Bajo", "Sin og:title/og:description las comparticiones y algunos agregadores muestran texto pobre.", "Añadir og:title, og:description, og:image.", "", id="aeo:og")

    # ---------- AEO: lo que citan los motores de respuesta ----------
    if palabras and palabras < args.min_words and len(h2) >= 1: add("AEO", "Contenido delgado (thin content)", "Medio", f"{palabras} palabras de texto (umbral {args.min_words}). Poco material citable y señal de baja profundidad.", "Ampliar con respuestas concretas, datos y ejemplos; o consolidar con otra página que cubra el mismo término.", f"{palabras} palabras", id="aeo:thin")
    primer_p = p.ps[0] if p.ps else ""
    tldr = any(re.search(r"\b(tl;?dr|en resumen|resumen|en pocas palabras|key takeaways|puntos clave|respuesta corta)\b", h[1], re.I) for h in p.headings) or \
           re.search(r"^(tl;?dr|en resumen|resumen|respuesta corta)\b", primer_p, re.I) is not None
    if palabras > 400 and not tldr: add("AEO", "Sin TL;DR / respuesta directa al inicio", "Alto", "No hay un bloque autocontenido (100–400 caracteres) que responda al término objetivo; es el bloque que un motor de respuesta 'levanta' y cita.", "Añadir un TL;DR o 'En resumen' bajo el H1 que responda la pregunta por completo (no un teaser), y alimentarlo en los datos estructurados.", primer_p[:200], "Bajo", id="aeo:tldr")
    if primer_p and len(primer_p) < 80 and palabras > 400: add("AEO", "Primer párrafo demasiado corto / sin respuesta", "Medio", "La primera frase tras el H1 no responde la pregunta del lector (answer-first).", "Responder en la primera frase; la elaboración va después.", primer_p, "Bajo", id="aeo:answer-first")
    preguntas = sum(1 for h in p.headings if h[0] in (2, 3) and h[1].strip().endswith("?"))
    faq_ld = any("FAQPage" in t for t in tipos)
    faq_h = any(re.search(r"\b(faq|preguntas frecuentes|preguntas)\b", h[1], re.I) for h in p.headings)
    if palabras > 400 and not (faq_ld or faq_h or preguntas >= 3): add("AEO", "Sin sección FAQ ni encabezados en forma de pregunta", "Medio", "Los motores de respuesta citan pares pregunta/respuesta; no hay FAQs ni ≥ 3 encabezados como pregunta.", "Añadir ≥ 3 FAQs reales (lo que el lector escribiría) con respuesta ≤ 500 caracteres que conteste en la primera frase, y marcarlas con FAQPage en JSON-LD.", f"preguntas={preguntas}, FAQPage={faq_ld}", "Bajo", id="aeo:faq")
    elif faq_h and not faq_ld: add("AEO", "FAQ visible sin datos estructurados FAQPage", "Bajo", "Hay FAQ en la página pero no está marcada en JSON-LD.", "Añadir schema.org/FAQPage con las mismas preguntas y respuestas.", "", "Bajo", id="aeo:faq")
    anaforas = sum(1 for s in p.ps if re.search(r"\b(como (vimos|mencionamos|dijimos) (arriba|antes|anteriormente)|as (we saw|mentioned) above|como se explicó antes)\b", s, re.I))
    if anaforas: add("AEO", "Secciones que dependen del contexto anterior", "Bajo", f"{anaforas} referencias tipo 'como vimos arriba': la sección no sobrevive si un LLM la extrae sola.", "Hacer cada sección autocontenida: sin referencias a lo dicho antes ni pronombres que apunten a otro encabezado.", "", "Bajo", id="aeo:answer-first")

    # ---------- Datos estructurados y frescura (dateModified) ----------
    if not ld: add("AEO", "Sin datos estructurados (JSON-LD)", "Alto", "Sin schema.org Google no obtiene tipo, autor ni fechas; los LLM pierden señales de entidad y frescura.", "Añadir JSON-LD: Article/BlogPosting (headline, author, datePublished, dateModified), Organization/WebSite, y FAQPage/Product/BreadcrumbList cuando aplique.", "", "Medio", id="aeo:jsonld")
    else:
        if any(o.get("_invalid") for o in p.jsonld): add("SEO", "JSON-LD inválido", "Alto", "Un bloque application/ld+json no es JSON válido: Google lo ignora.", "Validar en el Rich Results Test y corregir.", "", id="aeo:jsonld")
        arts = [o for o in ld if any(k in str(o.get("@type")) for k in ("Article", "BlogPosting", "NewsArticle", "TechArticle"))]
        for o in arts[:1]:
            dm, dp = o.get("dateModified"), o.get("datePublished")
            if not dm: add("AEO", "Article sin dateModified", "Medio", "Sin dateModified, un refresco del contenido nunca se refleja: la frescura es una señal fuerte para Google y los LLM.", "Emitir dateModified desde la fecha de última actualización real (updatedDate) y mostrarla también visible.", json.dumps({"datePublished": dp})[:200], "Bajo", id="aeo:fresh")
            else:
                try:
                    f = datetime.date.fromisoformat(str(dm)[:10]); meses = (datetime.date.today() - f).days / 30
                    if meses > 12: add("AEO", "Contenido sin actualizar hace más de 12 meses", "Medio", f"dateModified = {dm} ({meses:.0f} meses). Los motores de respuesta ponderan la recencia.", "Revisar y refrescar el contenido; actualizar dateModified solo cuando cambie de verdad.", str(dm), "Medio", id="aeo:fresh")
                except ValueError: add("SEO", "dateModified con formato no ISO", "Bajo", "La fecha no es ISO 8601.", "Usar YYYY-MM-DD o fecha-hora ISO.", str(dm), id="aeo:fresh")
            if not o.get("author"): add("AEO", "Article sin author", "Bajo", "Sin autor identificable (E-E-A-T) la fuente es menos citable.", "Añadir author (Person/Organization) con nombre y, si existe, URL de perfil.", "", "Bajo", id="aeo:jsonld")
        if not any(k in " ".join(tipos) for k in ("Organization", "WebSite", "Person")): add("AEO", "Sin entidad Organization/WebSite en JSON-LD", "Bajo", "Los LLM asocian contenido a entidades; falta la del sitio/marca.", "Añadir Organization (name, url, logo, sameAs) y WebSite.", ", ".join(tipos)[:200], "Bajo", id="aeo:jsonld")

    # ---------- Rastreabilidad por bots de IA: robots.txt, llms.txt, sitemap ----------
    st, robots, _ = get(urljoin(origen, "/robots.txt"), 10)
    if st == 200 and robots:
        bloqueados = []
        for bloque in re.split(r"(?i)(?=user-agent:)", robots):
            ua = re.findall(r"(?i)user-agent:\s*(\S+)", bloque)
            if any(b.lower() in [u.lower() for u in ua] for b in BOTS_IA) and re.search(r"(?im)^\s*disallow:\s*/\s*$", bloque):
                bloqueados += [u for u in ua if u.lower() in [b.lower() for b in BOTS_IA]]
        if bloqueados: add("AEO", "robots.txt bloquea bots de IA", "Info", f"Bloqueados: {', '.join(sorted(set(bloqueados)))}. Si es intencional (protección de contenido) está bien; si se quiere ser citado por ChatGPT/Perplexity/AI Overviews, no.", "Decidir explícitamente: permitir OAI-SearchBot/PerplexityBot/ClaudeBot (citación) aunque se bloquee el entrenamiento (GPTBot, Google-Extended, CCBot).", ", ".join(sorted(set(bloqueados))), "Bajo", id="aeo:robots")
        if not re.search(r"(?i)sitemap:", robots): add("SEO", "robots.txt sin Sitemap:", "Bajo", "No declara la ubicación del sitemap.", "Añadir 'Sitemap: https://…/sitemap.xml'.", "", "Bajo", id="aeo:robots")
    else: add("SEO", "Sin robots.txt accesible", "Bajo", f"robots.txt devolvió {st}.", "Publicar robots.txt (aunque sea permisivo) con la línea Sitemap.", "", "Bajo", id="aeo:robots")
    st, _, _ = get(urljoin(origen, "/llms.txt"), 10)
    if st != 200: add("AEO", "Sin llms.txt", "Bajo", "No existe /llms.txt: un mapa en Markdown del sitio para agentes y LLM (propuesta llmstxt.org). No garantiza citas, pero es barato.", "Publicar /llms.txt con descripción del sitio y enlaces a las páginas clave; opcionalmente /llms-full.txt.", "", "Bajo", id="aeo:llms")
    sm_ok = any(get(urljoin(origen, s), 10)[0] == 200 for s in ("/sitemap.xml", "/sitemap_index.xml"))
    if not sm_ok: add("SEO", "Sin sitemap.xml accesible", "Medio", "No se encontró /sitemap.xml ni /sitemap_index.xml.", "Generar y publicar sitemap con lastmod real.", "", "Bajo", id="aeo:sitemap")
    xr = (hdr.get("X-Robots-Tag") or hdr.get("x-robots-tag") or "")
    if "noindex" in xr.lower(): add("SEO", "Cabecera X-Robots-Tag: noindex", "Crítico", "El servidor pide no indexar la página.", "Eliminar la cabecera si la página debe posicionar.", xr, id="aeo:index")

    metricas = {"url": url, "status": status, "title": t, "title_len": len(t), "description_len": len(d), "lang": p.lang,
                "palabras": palabras, "h1": len(h1), "h2": len(h2), "headings_pregunta": preguntas, "enlaces_internos": len(set(internos)),
                "imgs": len(p.imgs), "imgs_sin_alt": len(sin_alt), "jsonld_tipos": tipos, "tldr_detectado": bool(tldr), "faq": faq_ld or faq_h,
                "canonical": canon[:1], "robots_meta": robots_meta, "llms_txt": st == 200, "sitemap": sm_ok}
    json.dump({"metricas": metricas, "hallazgos": H}, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps({"ok": True, "out": args.out, "hallazgos": len(H), "metricas": metricas}, ensure_ascii=False))

if __name__ == "__main__":
    main()
```
