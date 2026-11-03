# auditoria-rendimiento-frontend

Skill para Claude que audita el **rendimiento frontend** y la **visibilidad SEO/AEO** de cualquier sitio web y entrega un **reporte Excel** con todos los hallazgos, priorizados por severidad, ahorro estimado y esfuerzo.

> La pregunta que guía cada decisión no es "¿esto es rápido?" sino **"¿esto necesita pasar ahora?"**.
> Cargar, ejecutar y renderizar primero lo que el usuario necesita; diferir todo lo demás.

Está basada en *Frontend Performance Optimization: A Practical Guide to Faster Web Pages* (Sachin Patel). La complementan las reglas deterministas de [seodraft](#integraciones-opcionales) y los datos de [OpenSEO](#integraciones-opcionales), que cubren lo que Google y los motores de respuesta (ChatGPT, Perplexity, AI Overviews) buscan en una página.

---

## Qué revisa

| Área | Ejemplos de lo que detecta |
|---|---|
| **LCP** | Cuál es el elemento LCP *real*, si tiene `loading="lazy"` o le falta `fetchpriority="high"`, y qué recursos compiten con él |
| **Imágenes** | `fetchpriority="high"` repetido en varias imágenes, falta de `srcset`/`sizes`, slides de carrusel fuera de pantalla que se cargan de entrada |
| **Fuentes** | Varias fuentes precargadas, falta de `font-display: swap` |
| **Terceros** | Chat, analytics y mapas que cargan antes del contenido crítico o sin *escape hatch* ante la intención del usuario |
| **Iframes** | Sin caja dimensionada o con `src` asignado en la carga inicial |
| **JavaScript** | Overlays, drawers y sliders que no se cargan con `dynamic import`, y animaciones que corren durante la hidratación |
| **CLS** | Imágenes sin dimensiones, skeletons con una geometría distinta a la UI final, desajustes entre servidor y cliente |
| **Accesibilidad** | Botones de solo ícono sin nombre, `aria-label` redundantes, falta de `prefers-reduced-motion` |
| **SEO** | Title (15–60), description (50–160), un solo H1, enlaces internos, `alt`, canonical, noindex, `lang`, Open Graph |
| **AEO** | TL;DR, FAQs con FAQPage, *answer-first*, JSON-LD con `author`/`dateModified`, frescura, `robots.txt` para bots de IA, `llms.txt`, `sitemap.xml` |

Umbrales usados: **LCP ≤ 2,5 s · INP ≤ 200 ms · CLS ≤ 0,1 · TBT ≤ 200 ms · TTFB ≤ 0,8 s**.

## Cómo usarla

La skill se activa cuando le pides a Claude revisar, auditar o medir el rendimiento, la velocidad, el SEO o la visibilidad en IA de una web:

```
Audita el rendimiento de https://ejemplo.com
¿Por qué es lenta la home de mi tienda? https://tienda.cl
Revisa si mi blog es citable por ChatGPT y Perplexity: https://blog.ejemplo.com/articulo
```

Si solo das el dominio, audita como mínimo la home, un listado o categoría, un detalle (producto o artículo) y un formulario o checkout si lo hay. Mide en **móvil y escritorio**.

Si ya tienes artefactos (JSON de Lighthouse o PageSpeed Insights, trazas de DevTools, un HAR), pásaselos: la skill los usa directamente y no repite las mediciones. Si además entregas una medición previa, el reporte incluye la hoja **Antes vs Después**.

## Flujo

1. **Medir primero.** Usa la primera vía que funcione:
   - **A. Lighthouse CLI** (la preferida): laboratorio completo, en móvil y escritorio.
   - **B. API de PageSpeed Insights**: no necesita Chrome y añade datos de campo de CrUX (con INP real).
   - **C. Recolector en navegador** (`collect_browser.js`): comprobaciones de la guía que Lighthouse no reporta. Se ejecuta con Claude in Chrome, Playwright o DevTools, y se usa *también* cuando hay Lighthouse.
   - **D. Revisión estática**: cabeceras y HTML con `curl`, como último recurso.
   - **E. SEO/AEO** (`aeo_site_checks.py`): corre siempre, una vez por URL.
2. **Revisión guiada.** Para cada punto de la guía responde *¿qué compite con la primera experiencia significativa del usuario?*
3. **Clasificar** cada hallazgo con la rúbrica de severidad y una estimación honesta del esfuerzo.
4. **Generar el Excel** con `perf_report_xlsx.py`.
5. **Cierre breve en el chat**: estado de los CWV, elemento LCP real, si la página es citable, los 3-5 hallazgos prioritarios y los *quick wins*.

## Scripts

Los scripts están en `scripts/`. También van embebidos en `SKILL.md` para que la skill funcione aunque solo se cargue ese archivo.

| Script | Requisitos | Uso |
|---|---|---|
| `perf_report_xlsx.py` | Python 3, `openpyxl` | Genera el reporte Excel |
| `collect_browser.js` | Navegador | Se ejecuta en la página ya cargada y devuelve `{ metricas, recursos, hallazgos }` |
| `run_collect.js` | Node, `playwright` | Ejecuta `collect_browser.js` emulando un móvil |
| `aeo_site_checks.py` | Python 3 (solo stdlib) | Comprobaciones SEO/AEO sobre la URL servida |

### Ejemplo de ejecución manual

```bash
mkdir -p perf-audit/out && cd perf-audit
URL="https://ejemplo.com"

# A. Lighthouse
FLAGS="--headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage"
npx -y lighthouse "$URL" --output=json --output-path=out/lh-mobile.json  --locale=es --chrome-flags="$FLAGS" --quiet
npx -y lighthouse "$URL" --output=json --output-path=out/lh-desktop.json --locale=es --preset=desktop --chrome-flags="$FLAGS" --quiet

# C. Recolector en navegador (Playwright)
node ../scripts/run_collect.js "$URL" out/browser.json   # también escribe out/browser-hallazgos.json

# E. SEO/AEO
python3 ../scripts/aeo_site_checks.py "$URL" --out out/aeo.json

# Reporte
pip install openpyxl
python3 ../scripts/perf_report_xlsx.py \
  --out "out/reporte-rendimiento-ejemplo-$(date +%Y-%m-%d).xlsx" \
  out/lh-mobile.json out/lh-desktop.json \
  --manual out/browser-hallazgos.json out/aeo.json \
  --sitio "Ejemplo"
```

### Opciones de `perf_report_xlsx.py`

| Argumento | Descripción |
|---|---|
| `informes...` | JSON de Lighthouse o de PageSpeed Insights (posicionales, en cualquier cantidad) |
| `--manual` | Uno o más JSON de hallazgos (una lista, o `{ "hallazgos": [...] }`). Se fusionan |
| `--seodraft` | Salida de `seodraft audit` o `seodraft gate`: los *failures* quedan como Alto y los *advisories* AEO como Medio |
| `--antes` | JSON de Lighthouse de la línea base; genera la hoja **Antes vs Después** |
| `--sitio` | Nombre del sitio para el encabezado del reporte |
| `--out` | Ruta del `.xlsx` (por defecto `reporte-rendimiento.xlsx`) |

Acepta cualquier combinación: solo Lighthouse, solo PSI, solo `--manual`, o todo junto.

### Opciones de `aeo_site_checks.py`

`--out` (por defecto `hallazgos-aeo.json`), `--min-words` (500), `--title-max` (60), `--desc-max` (160), `--internal-links-min` (2).

## El reporte Excel

| Hoja | Contenido |
|---|---|
| **Resumen** | URLs, puntajes, conteo por severidad y top 10 |
| **Core Web Vitals** | Laboratorio y campo, con semáforo |
| **Hallazgos** | ID, área, severidad, prioridad, ahorro en ms/KB, descripción, recomendación, esfuerzo, estado y responsable (con filtros) |
| **Detalle** | Recursos y elementos afectados por cada hallazgo |
| **Recursos** | Peticiones por peso, protocolo y prioridad |
| **Checklist** | Puntos de la guía, incluida la sección SEO/AEO, marcados como Cumple, No cumple o Revisar manualmente |
| **Antes vs Después** | Solo si se pasa `--antes` |

## Formato de hallazgos manuales

`out/manual.json` es una lista de objetos:

```json
[
  {
    "url": "https://ejemplo.com",
    "categoria": "Imágenes",
    "titulo": "fetchpriority=high en 6 imágenes",
    "severidad": "Medio",
    "descripcion": "Qué pasa y por qué importa",
    "recomendacion": "Qué cambiar, concreto",
    "evidencia": "snippet, cabecera o URL del recurso",
    "esfuerzo": "Bajo",
    "form_factor": "Ambos"
  }
]
```

- **Áreas válidas:** Imágenes · LCP · JavaScript · CSS · Fuentes · Red y caché · Terceros · Iframes · Renderizado · Layout (CLS) · Accesibilidad · Medición · SEO · AEO
- **Esfuerzo:** Bajo · Medio · Alto

### Rúbrica de severidad

| Severidad | Criterio |
|---|---|
| **Crítico** | Pone un Core Web Vital en "Pobre", compite directamente con el LCP, ahorra ≥ 1 s o ≥ 500 KB, o el puntaje es < 50 |
| **Alto** | Ahorra ≥ 300 ms o ≥ 150 KB, el puntaje está entre 50 y 74, o afecta claramente a LCP/INP/CLS |
| **Medio** | Puntaje entre 75 y 89, mejora incremental, prioridades mal repartidas |
| **Bajo** | Buenas prácticas, accesibilidad sin impacto en rendimiento, informativo |

Un hallazgo Medio con esfuerzo Bajo es un *quick win* y va antes que uno Alto con esfuerzo Alto.

## Integraciones opcionales

- **OpenSEO MCP**: si está conectado, aporta lo que no se ve desde fuera: Site Audit completo, Search Console (CTR, impresiones, consultas en página 2), visibilidad de la marca en ChatGPT y AI Overviews, y keywords. La skill avisa antes de lanzar consultas de pago a DataForSEO.
- **seodraft**: si el repositorio de contenido tiene `.seodraft/config.json`, la salida de `seodraft audit` se importa con `--seodraft`. Para escribir o refrescar contenido, la skill remite a `/seodraft write` y `/seodraft audit`.

## Principios

- Priorizar **una** imagen (la LCP), no aplicar `lazy` ni `fetchpriority` en bloque.
- Diferir terceros e iframes, pero siempre con un *escape hatch* que los cargue de inmediato si el usuario los pide.
- Ninguna mejora de rendimiento puede introducir una regresión de accesibilidad.
- No seguir todas las recomendaciones de Lighthouse sin evaluar impacto, esfuerzo, complejidad y riesgo.
- No inventar fuentes ni cifras SEO (volúmenes, posiciones) si no hay datos reales.
- Cambiar **una cosa significativa a la vez**, volver a medir y revertir si no mejora.
- Laboratorio ≠ campo: el INP real solo se obtiene con usuarios reales.

## Estructura

```
auditoria-rendimiento-frontend/
├── SKILL.md                 # Instrucciones de la skill (incluye los scripts embebidos)
├── README.md
└── scripts/
    ├── perf_report_xlsx.py  # Generador del reporte Excel
    ├── collect_browser.js   # Recolector de señales en el navegador
    ├── run_collect.js       # Runner de Playwright para collect_browser.js
    └── aeo_site_checks.py   # Comprobaciones SEO/AEO
```
