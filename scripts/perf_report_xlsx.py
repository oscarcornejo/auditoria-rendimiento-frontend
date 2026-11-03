#!/usr/bin/env python3
"""
Genera un reporte Excel de auditoría de rendimiento frontend a partir de:
  - uno o más JSON de Lighthouse (CLI o PageSpeed Insights API: se acepta el
    objeto raíz de PSI, que trae `lighthouseResult` y `loadingExperience`)
  - opcionalmente un JSON de hallazgos manuales (lista de objetos con las
    claves: url, categoria, titulo, severidad, descripcion, recomendacion,
    evidencia, esfuerzo)

  - o una carpeta completa de audit_site.py (--dir): toma lh-*/psi-* como informes,
    aeo.json, browser-hallazgos.json, sitio-aeo.json, crosscheck.json y manual*.json como
    hallazgos, y cobertura.json + urls.json para las hojas de sitio completo.

Uso:
  python3 perf_report_xlsx.py --out reporte.xlsx lh-mobile.json [lh-desktop.json ...] \
      [--manual hallazgos.json aeo.json ...] [--seodraft audit.json] [--sitio "Nombre"] [--antes lh-base-mobile.json ...]
  python3 perf_report_xlsx.py --out reporte.xlsx --dir out [--sitio "Nombre"]
"""
import argparse, json, datetime, re, sys
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import CellIsRule, FormulaRule

import reporte_sitio
from url_utils import clave_url
from xlsx_estilos import BORDER, COLORES, COLORES_CHECK, ajustar, encabezado, pintar_estado

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
AUDITS_PESADAS = ("screenshot-thumbnails", "final-screenshot", "full-page-screenshot", "script-treemap-data")
CLAVES_PESADAS = ("fullPageScreenshot", "i18n", "timing", "stackPacks")

def leer_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def cargar(path, url=None):
    """Informe de Lighthouse/PSI sin capturas (ahorra memoria con cientos de URLs). ValueError si es un error."""
    raw = leer_json(path)
    if not isinstance(raw, dict):
        raise ValueError("no es un informe de Lighthouse/PSI")
    crux = None
    if "lighthouseResult" in raw:  # respuesta de PageSpeed Insights
        crux = raw.get("loadingExperience") or raw.get("originLoadingExperience")
        raw = raw["lighthouseResult"]
    if raw.get("error") or raw.get("runtimeError") or "audits" not in raw:
        err = raw.get("error") or raw.get("runtimeError") or "sin auditorías"
        raise ValueError(err.get("message", str(err)) if isinstance(err, dict) else str(err))
    lh = {k: v for k, v in raw.items() if k not in CLAVES_PESADAS}
    lh = {**lh, "audits": {k: v for k, v in raw["audits"].items() if k not in AUDITS_PESADAS}}
    ff = raw.get("configSettings", {}).get("formFactor") or raw.get("configSettings", {}).get("emulatedFormFactor", "mobile")
    return {"lh": lh, "crux": crux, "url": url or raw.get("finalDisplayedUrl") or raw.get("finalUrl") or raw.get("requestedUrl"),
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

# ---------- Checklist (puntos de la guía + SEO/AEO) ----------
AEO_IDS = ["aeo:title", "aeo:description", "aeo:headings", "aeo:tldr", "aeo:answer-first", "aeo:faq", "aeo:jsonld", "aeo:fresh",
           "aeo:links", "aeo:alt", "aeo:lang", "aeo:canonical", "aeo:index", "aeo:robots", "aeo:llms", "aeo:sitemap", "aeo:thin", "aeo:og"]
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
    ("SEO / AEO", "Title 15–60 y meta description 50–160, únicos por página", ["document-title", "meta-description", "aeo:title", "aeo:description", "cross:title-duplicado", "cross:description-duplicada"]),
    ("SEO / AEO", "Un solo H1; H2/H3 sin saltos de nivel; encabezados como la pregunta que el lector escribiría", ["heading-order", "aeo:headings", "cross:h1-duplicado"]),
    ("SEO / AEO", "TL;DR / respuesta directa autocontenida (100–400 caracteres) bajo el H1", ["aeo:tldr"]),
    ("SEO / AEO", "Cada sección responde en su primera frase y sobrevive extraída sola (sin 'como vimos arriba')", ["aeo:answer-first"]),
    ("SEO / AEO", "≥ 3 FAQs citables (respuesta ≤ 500 caracteres) marcadas con FAQPage", ["aeo:faq"]),
    ("SEO / AEO", "JSON-LD válido: Article/BlogPosting con author, datePublished y dateModified; Organization/WebSite", ["structured-data", "aeo:jsonld"]),
    ("SEO / AEO", "Frescura: dateModified real y contenido revisado en los últimos 12 meses", ["aeo:fresh", "seodraft:stale-post", "seodraft:missing-updated-date"]),
    ("SEO / AEO", "≥ 2 enlaces internos relevantes, ninguno roto; sin páginas huérfanas; sin canibalización entre URLs", ["crawlable-anchors", "aeo:links", "seodraft:broken-internal-link", "seodraft:orphan-page", "seodraft:cannibalization", "cross:enlace-roto", "cross:huerfana"]),
    ("SEO / AEO", "Imágenes con alt; lang en <html>; canonical correcto; sin noindex accidental", ["image-alt", "html-has-lang", "canonical", "is-crawlable", "aeo:alt", "aeo:lang", "aeo:canonical", "aeo:index", "cross:canonical-externo", "cross:canonical-roto"]),
    ("SEO / AEO", "robots.txt con Sitemap, decisión explícita sobre bots de IA (GPTBot, OAI-SearchBot, ClaudeBot, PerplexityBot, Google-Extended); llms.txt publicado", ["robots-txt", "aeo:robots", "aeo:llms", "aeo:sitemap"]),
    ("SEO / AEO", "El sitemap lista solo URLs finales indexables: 200, sin redirección y sin noindex", ["cross:sitemap-error", "cross:sitemap-redireccion", "cross:sitemap-noindex"]),
    ("SEO / AEO", "Contenido no delgado (≥ 500 palabras en artículos) y sin fuentes inventadas", ["aeo:thin", "seodraft:thin-content"]),
]
CROSS_IDS = ["cross:title-duplicado", "cross:description-duplicada", "cross:h1-duplicado", "cross:enlace-roto", "cross:huerfana",
             "cross:canonical-externo", "cross:canonical-roto", "cross:sitemap-error", "cross:sitemap-redireccion", "cross:sitemap-noindex"]
IDS_SITIO = {"aeo:robots", "aeo:llms", "aeo:sitemap", "robots-txt"}  # se evalúan una vez por dominio, no por URL

# ---------- Construcción del libro ----------
def construir(informes, manuales, out, sitio, antes=None, contexto=None):
    """Genera el libro. `contexto` (modo --dir): {urls, cobertura, crosscheck} para las hojas de sitio completo."""
    ctx = contexto or {}
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
        url_m = (reporte_sitio.PREFIJO_SITIO if m.get("alcance") == "sitio" else "") + (m.get("url") or "")
        hallazgos.append([f"H-{hid:03d}", url_m, m.get("form_factor", "Ambos"), m.get("grupo", "Rendimiento"),
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
    encabezado(ws, ["ID", "Severidad", "Área", "Hallazgo", "Ahorro est. (ms)", "Ahorro est. (KB)", "Dispositivo", "URL"], fila=r); r += 1
    for h in hallazgos[:10]:
        for i, v in enumerate([h[0], h[7], h[4], h[6], h[10], h[11], h[2], h[1]], 1):
            ws.cell(row=r, column=i, value=v).border = BORDER
        ws.cell(row=r, column=2).fill = PatternFill("solid", fgColor=COLORES[h[7]]); r += 1
    ajustar(ws, [45, 14, 22, 55, 16, 16, 14, 50])
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
    cols = ["Área", "Punto de control", "Auditorías relacionadas", "Resultado", "Evidencia / comentario", "URLs que no cumplen"]
    encabezado(ws, cols)
    ids_fallidos = {h[5] for h in hallazgos}
    ids_evaluados = {aid for inf in informes for aid, a in inf["lh"].get("audits", {}).items()
                     if a.get("scoreDisplayMode") not in ("notApplicable", "manual", "error")}
    if any(str(h[5]).startswith("aeo:") for h in hallazgos):  # corrió aeo_site_checks.py → todas sus reglas cuentan como evaluadas
        ids_evaluados |= set(AEO_IDS)
    if any(str(h[5]).startswith("cross:") for h in hallazgos) or ctx.get("crosscheck"):
        ids_evaluados |= set(CROSS_IDS)
    for area, punto, ids in CHECK:
        if any(i in ids_fallidos for i in ids):
            res = "No cumple"
        elif ids and any(i in ids_evaluados for i in ids):
            res = "Cumple"
        else:
            res = "Revisar manualmente"
        ws.append([area, punto, ", ".join(ids), res, "", reporte_sitio.no_cumplen_por_punto(hallazgos, ids)])
    n = ws.max_row
    for row in ws.iter_rows(min_row=2, max_row=n):
        for c in row: c.border = BORDER
    pintar_estado(ws, "D", n, colores=COLORES_CHECK)
    ws.auto_filter.ref = f"A1:F{n}"
    ajustar(ws, [16, 60, 50, 20, 50, 14])

    # ===== Hoja Antes vs Después (opcional, §11 del artículo: medir el resultado) =====
    if antes:
        ws = wb.create_sheet("Antes vs Después")
        encabezado(ws, ["URL", "Dispositivo", "Métrica", "Antes", "Después", "Diferencia", "Mejora %", "Unidad", "Estado después"])
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
        for a_inf in antes:
            d_inf = emparejar_despues(a_inf, informes)
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
                ws.append([d_inf["url"], a_inf["ff"], nombre, va, vd, round(diff, 3), round(mejora, 1), unidad, est])
        n = ws.max_row
        for row in ws.iter_rows(min_row=2, max_row=n):
            for c in row: c.border = BORDER
        if n > 1:
            ws.conditional_formatting.add(f"G2:G{n}", CellIsRule(operator="greaterThan", formula=["0"], fill=PatternFill("solid", fgColor="C6EFCE")))
            ws.conditional_formatting.add(f"G2:G{n}", CellIsRule(operator="lessThan", formula=["0"], fill=PatternFill("solid", fgColor="FFC7CE")))
            pintar_estado(ws, "I", n)
        ajustar(ws, [45, 12, 48, 12, 12, 12, 11, 8, 18])

    # ===== Hojas de sitio completo: con --dir o con más de una URL =====
    urls_distintas = {clave_url(inf["url"]) for inf in informes} | {clave_url(h[1]) for h in hallazgos if not reporte_sitio.es_de_sitio(h) and h[1]}
    if ctx or len(urls_distintas) > 1:
        reporte_sitio.agregar_hojas(wb, hallazgos, informes, CHECK, {**ctx, "ids_sitio": IDS_SITIO})

    wb.save(out)
    return len(hallazgos), len(recursos)

def emparejar_despues(a_inf, informes):
    """Informe 'después' de la misma URL y dispositivo; si no hay, el único de ese dispositivo."""
    mismo_ff = [d for d in informes if d["ff"] == a_inf["ff"]]
    misma_url = [d for d in mismo_ff if clave_url(d["url"]) == clave_url(a_inf["url"])]
    return (misma_url or (mismo_ff if len(mismo_ff) == 1 else [None]))[0]

def cargar_informes(entradas):
    """[(ruta, url|None)] → informes válidos; avisa y omite los que son errores."""
    informes = []
    for ruta, url in entradas:
        try:
            informes.append(cargar(ruta, url))
        except (OSError, ValueError, KeyError) as e:
            print(f"aviso: se omite {ruta}: {e}", file=sys.stderr)
    return informes

def cargar_manuales(entradas):
    """[(ruta, url|None)] → hallazgos; `url` (de la carpeta urls/<slug>/) reemplaza la de cada hallazgo."""
    manuales = []
    for ruta, url in entradas:
        try:
            raw = leer_json(ruta)
        except (OSError, ValueError) as e:
            print(f"aviso: se omite {ruta}: {e}", file=sys.stderr)
            continue
        lista = (raw.get("hallazgos") or []) if isinstance(raw, dict) else raw
        manuales += [{**m, "url": url} if url and m.get("alcance") != "sitio" else m for m in lista if isinstance(m, dict)]
    return manuales

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("informes", nargs="*", help="JSON de Lighthouse o de PageSpeed Insights")
    ap.add_argument("--manual", nargs="*", default=[], help="JSON de hallazgos manuales (lista, o {hallazgos:[...]} de collect_browser/aeo_site_checks); se fusionan")
    ap.add_argument("--seodraft", nargs="*", default=[], help="JSON de salida de `seodraft audit` o `seodraft gate` (failures/advisories)")
    ap.add_argument("--out", default="reporte-rendimiento.xlsx")
    ap.add_argument("--sitio", default="")
    ap.add_argument("--antes", nargs="*", default=[], help="JSON de Lighthouse de la línea base (genera hoja Antes vs Después)")
    ap.add_argument("--dir", help="Carpeta de audit_site.py: toma todos sus JSON y añade las hojas de sitio completo")
    a = ap.parse_args()
    d = reporte_sitio.cargar_directorio(a.dir) if a.dir else {"informes": [], "manuales": []}
    informes = cargar_informes(d["informes"] + [(p, None) for p in a.informes])
    manuales = cargar_manuales(d["manuales"] + [(p, None) for p in a.manual])
    for p in a.seodraft:
        manuales += importar_seodraft(leer_json(p))
    if not informes and not manuales:
        sys.exit("No hay informes ni hallazgos válidos para generar el reporte.")
    contexto = {k: d[k] for k in ("urls", "cobertura", "crosscheck")} if a.dir else None
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    n_h, n_r = construir(informes, manuales, a.out, a.sitio, antes=cargar_informes((p, None) for p in a.antes), contexto=contexto)
    print(f"OK: {n_h} hallazgos, {n_r} recursos, {len(informes)} informes")
    print(f"Reporte: {Path(a.out).resolve()}")
    if a.dir:
        print(f"Carpeta de la auditoría: {Path(a.dir).resolve()}")
