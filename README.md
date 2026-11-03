# auditoria-rendimiento-frontend

Skill para Claude que audita el **rendimiento frontend** y la **visibilidad SEO/AEO** de cualquier sitio web y entrega un **reporte Excel** con todos los hallazgos, priorizados por severidad, ahorro estimado y esfuerzo.

> La pregunta que guía cada decisión no es "¿esto es rápido?" sino **"¿esto necesita pasar ahora?"**.
> Cargar, ejecutar y renderizar primero lo que el usuario necesita; diferir todo lo demás.

Está basada en *Frontend Performance Optimization: A Practical Guide to Faster Web Pages* (Sachin Patel). La complementan las reglas deterministas de [seodraft](#integraciones-opcionales) y los datos de [OpenSEO](#integraciones-opcionales), que cubren lo que Google y los motores de respuesta (ChatGPT, Perplexity, AI Overviews) buscan en una página.

---

## Instalación

```bash
npx skills add https://github.com/oscarcornejo/auditoria-rendimiento-frontend --skill auditoria-rendimiento-frontend
```

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
| **Entre URLs** | Title, description y H1 duplicados; URLs del sitemap con error, redirección o `noindex`; canonical externo o roto; enlaces internos rotos; páginas huérfanas |

Umbrales usados: **LCP ≤ 2,5 s · INP ≤ 200 ms · CLS ≤ 0,1 · TBT ≤ 200 ms · TTFB ≤ 0,8 s**.

## Cómo usarla

La skill se activa cuando le pides a Claude revisar, auditar o medir el rendimiento, la velocidad, el SEO o la visibilidad en IA de una web:

```
Audita el rendimiento de https://ejemplo.com
¿Por qué es lenta la home de mi tienda? https://tienda.cl
Revisa si mi blog es citable por ChatGPT y Perplexity: https://blog.ejemplo.com/articulo
Audita todo ejemplo.com, pero Lighthouse solo en 3 URLs por plantilla
Audita solo las URLs de /blog/ de https://ejemplo.com
```

Por defecto la auditoría es **completa**: descubre todas las URLs del sitio (sitemap o rastreo) y revisa cada una, así el reporte dice **en qué URL** está cada problema. También detecta problemas *entre* URLs (títulos duplicados, enlaces rotos, páginas huérfanas). Si pides una sola página, audita solo esa. Mide en **móvil y escritorio**.

Si ya tienes artefactos (JSON de Lighthouse o PageSpeed Insights, trazas de DevTools, un HAR), pásaselos: la skill los usa directamente y no repite las mediciones. Si además entregas una medición previa, el reporte incluye la hoja **Antes vs Después**.

## Flujo

1. **Descubrir** (`discover_urls.py`): `robots.txt` → sitemaps → rastreo de enlaces internos si no hay sitemap. Normaliza, deduplica y agrupa las URLs por plantilla (`/blog/*`).
2. **Auditar cada URL** (`audit_site.py`): SEO/AEO en todas las URLs, Lighthouse (o PSI) móvil y escritorio y, opcionalmente, el recolector en navegador. Es reanudable y deja un registro de cobertura por URL.
3. **Cruzar URLs** (`site_crosscheck.py`): duplicados de title/description/H1, sitemap con errores o redirecciones, canonical roto, enlaces internos rotos y páginas huérfanas.
4. **Revisión guiada**, una URL representativa por plantilla: *¿qué compite con la primera experiencia significativa del usuario?*
5. **Generar el Excel** con `perf_report_xlsx.py --dir`.
6. **Cierre breve en el chat**: alcance, CWV por plantilla, las 10 peores URLs, los patrones repetidos y los *quick wins*.

Para una sola URL siguen disponibles las vías sueltas: **A.** Lighthouse CLI · **B.** API de PageSpeed Insights · **C.** recolector en navegador (`collect_browser.js`) · **D.** revisión estática con `curl` · **E.** SEO/AEO (`aeo_site_checks.py`).

## Scripts

Todos están en `scripts/`; `SKILL.md` los referencia por ruta.

| Script | Requisitos | Uso |
|---|---|---|
| `discover_urls.py` | Python 3 (stdlib) | Descubre las URLs del sitio → `urls.json` |
| `audit_site.py` | Python 3; Node + `npx lighthouse` para `--motor lighthouse` | Audita todas las URLs → `urls/<slug>/`, `cobertura.json` |
| `site_crosscheck.py` | Python 3 (stdlib) | Problemas entre URLs → `crosscheck.json` |
| `aeo_site_checks.py` | Python 3 (stdlib) | Comprobaciones SEO/AEO de una página y del sitio |
| `perf_report_xlsx.py` | Python 3, `openpyxl` | Genera el reporte Excel (usa `reporte_sitio.py` y `xlsx_estilos.py`) |
| `collect_browser.js` | Navegador | Se ejecuta en la página ya cargada y devuelve `{ metricas, recursos, hallazgos }` |
| `run_collect.js` | Node, `playwright` | Ejecuta `collect_browser.js` emulando un móvil |
| `url_utils.py` | — | Normalización, slug y plantilla de URLs |

### Ejemplo: sitio completo

```bash
mkdir -p perf-audit/out && cd perf-audit
python3 ../scripts/discover_urls.py "https://ejemplo.com" --out out/urls.json
python3 ../scripts/audit_site.py --urls out/urls.json --out out --motor lighthouse
pip install openpyxl
python3 ../scripts/perf_report_xlsx.py --dir out --sitio "Ejemplo" \
  --out "out/reporte-rendimiento-ejemplo-$(date +%Y-%m-%d).xlsx"
```

En sitios grandes, `--lighthouse-por-plantilla 3` limita Lighthouse a 3 URLs por plantilla (SEO/AEO sigue en todas) y `--solo-movil` reduce el tiempo a la mitad. Si se corta, repite el comando: reutiliza lo ya medido.

### Opciones de `discover_urls.py` y `audit_site.py`

| Script | Opción | Descripción |
|---|---|---|
| `discover_urls.py` | `--max N` | Tope de URLs (por defecto todas) |
| | `--include` / `--exclude` | Regex para filtrar URLs |
| | `--crawl-depth`, `--max-crawl` | Límites del rastreo cuando no hay sitemap |
| `audit_site.py` | `--motor lighthouse\|psi\|ninguno` | Medición de laboratorio por URL (PSI usa `PSI_API_KEY` si existe) |
| | `--lighthouse-por-plantilla N` | Lighthouse/PSI solo en N URLs por plantilla (0 = todas) |
| | `--solo-movil` | Lighthouse/PSI solo en móvil |
| | `--browser` | Recolector Playwright en cada URL |
| | `--concurrency N` | Checks HTTP en paralelo (Lighthouse siempre en serie) |
| | `--verificar-enlaces N` | Comprueba por HTTP hasta N enlaces internos fuera del sitemap |
| | `--sin-crosscheck` | No ejecutar `site_crosscheck.py` |

### Ejemplo: una sola URL

```bash
mkdir -p out
URL="https://ejemplo.com"
FLAGS="--headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage"
npx -y lighthouse "$URL" --output=json --output-path=out/lh-mobile.json  --locale=es --chrome-flags="$FLAGS" --quiet
npx -y lighthouse "$URL" --output=json --output-path=out/lh-desktop.json --locale=es --preset=desktop --chrome-flags="$FLAGS" --quiet
node ../scripts/run_collect.js "$URL" out/browser.json   # también escribe out/browser-hallazgos.json
python3 ../scripts/aeo_site_checks.py "$URL" --out out/aeo.json
python3 ../scripts/perf_report_xlsx.py --out out/reporte.xlsx out/lh-mobile.json out/lh-desktop.json \
  --manual out/browser-hallazgos.json out/aeo.json --sitio "Ejemplo"
```

### Opciones de `perf_report_xlsx.py`

| Argumento | Descripción |
|---|---|
| `informes...` | JSON de Lighthouse o de PageSpeed Insights (posicionales, en cualquier cantidad) |
| `--manual` | Uno o más JSON de hallazgos (una lista, o `{ "hallazgos": [...] }`). Se fusionan |
| `--seodraft` | Salida de `seodraft audit` o `seodraft gate`: los *failures* quedan como Alto y los *advisories* AEO como Medio |
| `--dir` | Carpeta de `audit_site.py`: toma todos sus JSON y añade las hojas de sitio completo |
| `--antes` | JSON de Lighthouse de la línea base; genera la hoja **Antes vs Después** (emparejada por URL y dispositivo) |
| `--sitio` | Nombre del sitio para el encabezado del reporte |
| `--out` | Ruta del `.xlsx` (por defecto `reporte-rendimiento.xlsx`) |

Acepta cualquier combinación: solo Lighthouse, solo PSI, solo `--manual`, o todo junto.

### Opciones de `aeo_site_checks.py`

`--out` (por defecto `hallazgos-aeo.json`), `--min-words` (500), `--title-max` (60), `--desc-max` (160), `--internal-links-min` (2), `--sin-checks-sitio` (solo la página) y `--solo-sitio` (solo robots.txt, llms.txt y sitemap).

### Archivos de salida

```
out/
├── urls.json            # URLs descubiertas, plantilla de cada una y URLs excluidas con su motivo
├── cobertura.json       # Por URL: estado de cada paso (ok, reutilizado, error, no aplica)
├── errores.json         # Pasos que fallaron, con el mensaje
├── sitio-aeo.json       # robots.txt, llms.txt y sitemap (una vez por sitio)
├── crosscheck.json      # Problemas entre URLs
├── manual.json          # Hallazgos de la revisión guiada (opcional, lo escribe Claude)
└── urls/<slug>/         # Una carpeta por URL
    ├── aeo.json
    ├── lh-mobile.json  lh-desktop.json     # o psi-mobile.json / psi-desktop.json
    └── browser.json  browser-hallazgos.json  # con --browser
```

El `<slug>` combina el path legible con un hash corto de la URL, así dos URLs nunca comparten carpeta.

### Cómo identifica cada URL

- Se consideran **la misma página**: con y sin barra final, `http` y `https`, con y sin `www.`, host en mayúsculas, y con o sin parámetros de tracking (`utm_*`, `gclid`, `fbclid`…) o fragmento (`#…`).
- En el rastreo, si una URL redirige, se registra la URL final y sus enlaces relativos se resuelven contra ella.
- Solo se audita el mismo sitio (con o sin `www.`). Se descartan otros dominios y archivos que no son HTML (PDF, imágenes, assets), y quedan listados en `urls.json` → `excluidas`.
- Por seguridad, solo se leen sitemaps `http(s)` del mismo sitio: un sitemap o un `robots.txt` no puede hacer que se pidan archivos locales, IPs internas u otros dominios. Un sitemap alojado en otro host (por ejemplo, un CDN) no se lee; en ese caso el descubrimiento pasa al rastreo.

## El reporte Excel

| Hoja | Contenido |
|---|---|
| **Resumen** | URLs, puntajes, conteo por severidad y top 10 (con su URL) |
| **Core Web Vitals** | Laboratorio y campo, con semáforo |
| **Hallazgos** | Una fila por URL y problema (los de sitio llevan el prefijo "(sitio)"): ID, área, severidad, prioridad, ahorro en ms/KB, descripción, recomendación, esfuerzo, estado y responsable (con filtros) |
| **Detalle** | Recursos y elementos afectados por cada hallazgo |
| **Recursos** | Peticiones por peso, protocolo y prioridad |
| **Checklist** | Puntos de la guía, incluida la sección SEO/AEO, marcados como Cumple, No cumple o Revisar manualmente, con cuántas URLs no cumplen |
| **Antes vs Después** | Solo si se pasa `--antes` |
| **Por URL** | Severidades, puntaje y LCP de cada URL, peores primero, y pasos que fallaron *(varias URLs)* |
| **Por plantilla** | Agregado por plantilla: puntaje medio, hallazgos por URL y la peor URL *(varias URLs)* |
| **Patrones** | El mismo problema en muchas URLs, con % afectado: candidatos a arreglo de plantilla *(varias URLs)* |
| **Checklist por URL** | Matriz URL × punto de la guía *(varias URLs)* |
| **Cobertura** | Qué se midió en cada URL y qué URLs se excluyeron y por qué *(varias URLs)* |

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

## Limitaciones conocidas

- Con `--include`, si la home no coincide con el filtro y el sitio no tiene sitemap, el rastreo no avanza y devuelve 0 URLs.
- Si un sitemap falla (error de red o XML inválido), el descubrimiento pasa al rastreo sin avisar; revisa `fuente` en `urls.json`.
- En auditorías parciales (`--max`, `--include`/`--exclude`), una página enlazada solo desde URLs no auditadas puede salir como huérfana, y un canonical a una URL no auditada como "externo".
- Las descargas tienen timeout por operación, no un plazo total: un servidor que responde muy lento puede alargar mucho el descubrimiento.
- Con `--motor psi`, `PSI_API_KEY` se pasa a `curl` como argumento y es visible en la lista de procesos.
- Lighthouse se ejecuta con `npx -y lighthouse` (sin versión fija) y Chrome con `--no-sandbox`: audita sitios de terceros en un entorno aislado.
- Laboratorio ≠ campo: Lighthouse mide en un entorno simulado; el INP real requiere datos de usuarios (PSI/CrUX).

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
├── SKILL.md                 # Instrucciones de la skill
├── README.md
├── requirements-dev.txt     # Dependencias para tests
├── scripts/
│   ├── discover_urls.py     # Descubrimiento de URLs
│   ├── audit_site.py        # Orquestador de la auditoría del sitio
│   ├── site_crosscheck.py   # Problemas entre URLs
│   ├── aeo_site_checks.py   # Comprobaciones SEO/AEO
│   ├── perf_report_xlsx.py  # Generador del reporte Excel
│   ├── reporte_sitio.py     # Hojas de sitio completo
│   ├── xlsx_estilos.py      # Estilos compartidos del Excel
│   ├── url_utils.py         # Utilidades de URL
│   ├── collect_browser.js   # Recolector de señales en el navegador
│   └── run_collect.js       # Runner de Playwright para collect_browser.js
└── tests/                   # pytest
```

## Desarrollo

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q tests/ --cov=scripts
```

Los tests no hacen peticiones de red: `fetch`, `get` y el ejecutor de subprocesos se inyectan como dobles. La cobertura mínima es 80% por módulo.
