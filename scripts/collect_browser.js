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
