#!/usr/bin/env python3
"""
Comprobaciones SEO / AEO deterministas sobre una URL pública (sin navegador,
solo stdlib): lo que Google y los motores de respuesta (ChatGPT, Perplexity,
AI Overviews) buscan en una página. Reglas inspiradas en seodraft
(gate/audit) aplicadas al HTML servido, más rastreabilidad por bots de IA.

Hay dos alcances:
  - página: title, description, headings, enlaces, alt, canonical, noindex, TL;DR, FAQ, JSON-LD…
  - sitio:  robots.txt (bots de IA, Sitemap:), llms.txt, sitemap.xml — una vez por dominio.

Uso:
  python3 aeo_site_checks.py <url> [--out aeo.json] [--min-words 500]
  python3 aeo_site_checks.py <url> --sin-checks-sitio   # auditoría por URL dentro de un sitio completo
  python3 aeo_site_checks.py <origen> --solo-sitio      # checks de sitio, una sola vez
Salida: JSON con {metricas, hallazgos[, error]} — `hallazgos` es compatible con --manual
del generador de Excel (perf_report_xlsx.py). Si la página no responde, escribe
igual el archivo con `error` y el status (lo usa site_crosscheck.py).
"""
import argparse
import datetime
import http.client
import json
import re
import sys
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from discover_urls import sitemap_permitido, sitemaps_de_robots
from url_utils import ESQUEMAS_WEB, mismo_sitio, normalizar

UA = "Mozilla/5.0 (compatible; auditoria-rendimiento-frontend/1.0)"
BOTS_IA = ["GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "anthropic-ai", "PerplexityBot",
           "Google-Extended", "Bytespider", "CCBot", "Applebot-Extended", "meta-externalagent"]
TIMEOUT_PAGINA_S = 20
TIMEOUT_SITIO_S = 10
MAX_ENLACES_GUARDADOS = 1000
MESES_FRESCURA = 12
PALABRAS_ESTRUCTURA = 300
PALABRAS_AEO = 400
FAQS_MINIMAS = 3
PRIMER_PARRAFO_MIN = 80


def get(url, timeout=TIMEOUT_PAGINA_S):
    """GET de texto. Devuelve (status, cuerpo, cabeceras, url_final); status None si falla la conexión."""
    if urlparse(url).scheme not in ESQUEMAS_WEB:
        return None, f"esquema no permitido: {url}", {}, url
    try:
        with urlopen(Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"}), timeout=timeout) as r:
            body = r.read().decode(r.headers.get_content_charset() or "utf-8", "ignore")
            return r.status, body, dict(r.headers), r.geturl()
    except HTTPError as e:
        return e.code, "", {}, url
    except (URLError, OSError, ValueError, LookupError, http.client.HTTPException) as e:
        return None, str(e), {}, url


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


def _recolector(url, alcance=None):
    hallazgos = []
    def add(cat, titulo, sev, desc, rec, ev="", esf="Bajo", id="aeo:otro"):
        h = {"url": url, "id": id, "categoria": cat, "titulo": titulo, "severidad": sev, "descripcion": desc,
             "recomendacion": rec, "evidencia": str(ev)[:400], "esfuerzo": esf, "form_factor": "Ambos"}
        if alcance:
            h["alcance"] = alcance
        hallazgos.append(h)
    return hallazgos, add


def _enlaces_internos(p, url):
    out = []
    for href in p.a:
        n = normalizar(href, base=url)
        if n and mismo_sitio(n, url) and n not in out:
            out.append(n)
    return out


def _seo_basico(p, url, opc, add, internos, palabras):
    t = p.title.strip()
    if not t: add("SEO", "Falta <title>", "Crítico", "La página no tiene título.", f"Añadir un <title> de 15–{opc.title_max} caracteres con el término objetivo.", "", id="aeo:title")
    elif not (15 <= len(t) <= opc.title_max): add("SEO", "Longitud de <title> fuera de rango", "Medio", f"{len(t)} caracteres (rango 15–{opc.title_max}).", "Reescribir el título a la longitud correcta; no truncar a ciegas.", t, id="aeo:title")
    d = (p.meta.get("description") or "").strip()
    if not d: add("SEO", "Falta meta description", "Alto", "Sin meta description: Google y los motores de respuesta improvisan el resumen.", f"Añadir una description de 50–{opc.desc_max} caracteres que responda a la intención.", "", id="aeo:description")
    elif not (50 <= len(d) <= opc.desc_max): add("SEO", "Longitud de meta description fuera de rango", "Medio", f"{len(d)} caracteres (rango 50–{opc.desc_max}).", "Ajustar la description a la longitud correcta cortando en límite de palabra.", d, id="aeo:description")
    h1 = [h for h in p.headings if h[0] == 1]
    if len(h1) != 1: add("SEO", f"{len(h1)} H1 en la página", "Alto" if len(h1) == 0 else "Medio", "Debe haber exactamente un H1 con el tema principal.", "Dejar un único H1; el resto como H2/H3.", " | ".join(h[1].strip() for h in h1)[:300], id="aeo:headings")
    saltos = [(a[1].strip()[:40], a[0], b[0]) for a, b in zip(p.headings, p.headings[1:]) if b[0] > a[0] + 1]
    if saltos: add("SEO", "Saltos de nivel en encabezados", "Medio", f"{len(saltos)} saltos (p. ej. H2→H4). Rompen el outline que Google y los LLM usan para entender la estructura.", "Corregir la jerarquía: H3 solo bajo H2, sin saltar niveles.", "; ".join(f"'{s[0]}' H{s[1]}→H{s[2]}" for s in saltos[:5]), id="aeo:headings")
    h2 = [h for h in p.headings if h[0] == 2]
    if palabras > PALABRAS_ESTRUCTURA and len(h2) < 2: add("AEO", "Menos de 2 H2", "Medio", "Los motores de respuesta citan secciones; sin H2 no hay secciones extraíbles.", "Estructurar el contenido en ≥ 2 secciones H2 con encabezados que sean la pregunta que el lector escribiría.", f"{len(h2)} H2", id="aeo:headings")
    if palabras > PALABRAS_ESTRUCTURA and len(internos) < opc.internal_links_min: add("SEO", "Pocos enlaces internos", "Medio", f"{len(internos)} enlaces internos (mínimo {opc.internal_links_min}).", "Enlazar a páginas propias relevantes por tema; evita páginas huérfanas y reparte autoridad.", "", id="aeo:links")
    sin_alt = [i.get("src", "")[:120] for i in p.imgs if i.get("alt") is None and "presentation" not in (i.get("role") or "")]
    if sin_alt: add("SEO", "Imágenes sin atributo alt", "Medio", f"{len(sin_alt)} imágenes sin alt.", "Añadir alt descriptivo (o alt=\"\" si es decorativa).", "\n".join(sin_alt[:6]), id="aeo:alt")
    if not p.lang: add("SEO", "Falta atributo lang en <html>", "Bajo", "Sin lang, buscadores y lectores de pantalla adivinan el idioma.", 'Añadir <html lang="es"> (o el idioma real).', "", id="aeo:lang")
    canon = p.links_rel.get("canonical", [])
    if not canon: add("SEO", "Falta rel=canonical", "Medio", "Sin canonical, variantes de URL (utm, trailing slash, www) compiten entre sí.", "Declarar <link rel=canonical> apuntando a la URL definitiva.", "", id="aeo:canonical")
    elif urlparse(urljoin(url, canon[0])).path.rstrip("/") != urlparse(url).path.rstrip("/"): add("SEO", "Canonical apunta a otra URL", "Alto", "La página declara como canónica otra URL: Google indexará esa y no esta.", "Verificar que sea intencional (p. ej. variante de paginación/filtro); si no, corregir el canonical.", canon[0], id="aeo:canonical")
    robots_meta = (p.meta.get("robots") or "").lower()
    if "noindex" in robots_meta: add("SEO", "Página con noindex", "Crítico", "La página pide no ser indexada: no aparecerá en Google ni será citada por motores que rastrean el índice.", "Quitar noindex si la página debe posicionar.", robots_meta, id="aeo:index")
    if not p.meta.get("og:title") and not p.meta.get("og:description"): add("SEO", "Sin Open Graph", "Bajo", "Sin og:title/og:description las comparticiones y algunos agregadores muestran texto pobre.", "Añadir og:title, og:description, og:image.", "", id="aeo:og")
    return {"title": t, "description": d, "h1": h1, "h2": h2, "sin_alt": sin_alt, "canon": canon, "robots_meta": robots_meta}


def _aeo_contenido(p, opc, add, palabras, h2, tipos):
    if palabras and palabras < opc.min_words and len(h2) >= 1: add("AEO", "Contenido delgado (thin content)", "Medio", f"{palabras} palabras de texto (umbral {opc.min_words}). Poco material citable y señal de baja profundidad.", "Ampliar con respuestas concretas, datos y ejemplos; o consolidar con otra página que cubra el mismo término.", f"{palabras} palabras", id="aeo:thin")
    primer_p = p.ps[0] if p.ps else ""
    tldr = any(re.search(r"\b(tl;?dr|en resumen|resumen|en pocas palabras|key takeaways|puntos clave|respuesta corta)\b", h[1], re.I) for h in p.headings) or \
           re.search(r"^(tl;?dr|en resumen|resumen|respuesta corta)\b", primer_p, re.I) is not None
    if palabras > PALABRAS_AEO and not tldr: add("AEO", "Sin TL;DR / respuesta directa al inicio", "Alto", "No hay un bloque autocontenido (100–400 caracteres) que responda al término objetivo; es el bloque que un motor de respuesta 'levanta' y cita.", "Añadir un TL;DR o 'En resumen' bajo el H1 que responda la pregunta por completo (no un teaser), y alimentarlo en los datos estructurados.", primer_p[:200], "Bajo", id="aeo:tldr")
    if primer_p and len(primer_p) < PRIMER_PARRAFO_MIN and palabras > PALABRAS_AEO: add("AEO", "Primer párrafo demasiado corto / sin respuesta", "Medio", "La primera frase tras el H1 no responde la pregunta del lector (answer-first).", "Responder en la primera frase; la elaboración va después.", primer_p, "Bajo", id="aeo:answer-first")
    preguntas = sum(1 for h in p.headings if h[0] in (2, 3) and h[1].strip().endswith("?"))
    faq_ld = any("FAQPage" in t for t in tipos)
    faq_h = any(re.search(r"\b(faq|preguntas frecuentes|preguntas)\b", h[1], re.I) for h in p.headings)
    if palabras > PALABRAS_AEO and not (faq_ld or faq_h or preguntas >= FAQS_MINIMAS): add("AEO", "Sin sección FAQ ni encabezados en forma de pregunta", "Medio", "Los motores de respuesta citan pares pregunta/respuesta; no hay FAQs ni ≥ 3 encabezados como pregunta.", "Añadir ≥ 3 FAQs reales (lo que el lector escribiría) con respuesta ≤ 500 caracteres que conteste en la primera frase, y marcarlas con FAQPage en JSON-LD.", f"preguntas={preguntas}, FAQPage={faq_ld}", "Bajo", id="aeo:faq")
    elif faq_h and not faq_ld: add("AEO", "FAQ visible sin datos estructurados FAQPage", "Bajo", "Hay FAQ en la página pero no está marcada en JSON-LD.", "Añadir schema.org/FAQPage con las mismas preguntas y respuestas.", "", "Bajo", id="aeo:faq")
    anaforas = sum(1 for s in p.ps if re.search(r"\b(como (vimos|mencionamos|dijimos) (arriba|antes|anteriormente)|as (we saw|mentioned) above|como se explicó antes)\b", s, re.I))
    if anaforas: add("AEO", "Secciones que dependen del contexto anterior", "Bajo", f"{anaforas} referencias tipo 'como vimos arriba': la sección no sobrevive si un LLM la extrae sola.", "Hacer cada sección autocontenida: sin referencias a lo dicho antes ni pronombres que apunten a otro encabezado.", "", "Bajo", id="aeo:answer-first")
    return {"tldr": bool(tldr), "preguntas": preguntas, "faq": faq_ld or faq_h}


def _frescura(o, add):
    dm, dp = o.get("dateModified"), o.get("datePublished")
    if not dm:
        add("AEO", "Article sin dateModified", "Medio", "Sin dateModified, un refresco del contenido nunca se refleja: la frescura es una señal fuerte para Google y los LLM.", "Emitir dateModified desde la fecha de última actualización real (updatedDate) y mostrarla también visible.", json.dumps({"datePublished": dp})[:200], "Bajo", id="aeo:fresh")
        return
    try:
        f = datetime.date.fromisoformat(str(dm)[:10]); meses = (datetime.date.today() - f).days / 30
        if meses > MESES_FRESCURA: add("AEO", "Contenido sin actualizar hace más de 12 meses", "Medio", f"dateModified = {dm} ({meses:.0f} meses). Los motores de respuesta ponderan la recencia.", "Revisar y refrescar el contenido; actualizar dateModified solo cuando cambie de verdad.", str(dm), "Medio", id="aeo:fresh")
    except ValueError:
        add("SEO", "dateModified con formato no ISO", "Bajo", "La fecha no es ISO 8601.", "Usar YYYY-MM-DD o fecha-hora ISO.", str(dm), id="aeo:fresh")


def _jsonld(p, add, ld, tipos):
    if any(isinstance(o, dict) and o.get("_invalid") for o in p.jsonld): add("SEO", "JSON-LD inválido", "Alto", "Un bloque application/ld+json no es JSON válido: Google lo ignora.", "Validar en el Rich Results Test y corregir.", "", id="aeo:jsonld")
    if not ld:
        add("AEO", "Sin datos estructurados (JSON-LD)", "Alto", "Sin schema.org Google no obtiene tipo, autor ni fechas; los LLM pierden señales de entidad y frescura.", "Añadir JSON-LD: Article/BlogPosting (headline, author, datePublished, dateModified), Organization/WebSite, y FAQPage/Product/BreadcrumbList cuando aplique.", "", "Medio", id="aeo:jsonld")
        return
    arts = [o for o in ld if any(k in str(o.get("@type")) for k in ("Article", "BlogPosting", "NewsArticle", "TechArticle"))]
    for o in arts[:1]:
        _frescura(o, add)
        if not o.get("author"): add("AEO", "Article sin author", "Bajo", "Sin autor identificable (E-E-A-T) la fuente es menos citable.", "Añadir author (Person/Organization) con nombre y, si existe, URL de perfil.", "", "Bajo", id="aeo:jsonld")
    if not any(k in " ".join(tipos) for k in ("Organization", "WebSite", "Person")): add("AEO", "Sin entidad Organization/WebSite en JSON-LD", "Bajo", "Los LLM asocian contenido a entidades; falta la del sitio/marca.", "Añadir Organization (name, url, logo, sameAs) y WebSite.", ", ".join(tipos)[:200], "Bajo", id="aeo:jsonld")


def analizar_pagina(url, status, body, hdr, url_final, opc):
    """Checks de una página ya descargada. Devuelve (hallazgos, metricas)."""
    hallazgos, add = _recolector(url)
    p = P(); p.feed(body)
    texto = re.sub(r"\s+", " ", " ".join(p.text)).strip(); palabras = len(texto.split())
    ld = flatten_ld(p.jsonld); tipos = [str(o.get("@type")) for o in ld]
    internos = _enlaces_internos(p, url)
    seo = _seo_basico(p, url, opc, add, internos, palabras)
    aeo = _aeo_contenido(p, opc, add, palabras, seo["h2"], tipos)
    _jsonld(p, add, ld, tipos)
    xr = (hdr.get("X-Robots-Tag") or hdr.get("x-robots-tag") or "")
    if "noindex" in xr.lower(): add("SEO", "Cabecera X-Robots-Tag: noindex", "Crítico", "El servidor pide no indexar la página.", "Eliminar la cabecera si la página debe posicionar.", xr, id="aeo:index")
    canon_abs = normalizar(seo["canon"][0], base=url) if seo["canon"] else None
    metricas = {"url": url, "status": status, "url_final": url_final, "title": seo["title"], "title_len": len(seo["title"]),
                "description": seo["description"], "description_len": len(seo["description"]), "lang": p.lang,
                "palabras": palabras, "h1": len(seo["h1"]), "h1_textos": [h[1].strip() for h in seo["h1"]], "h2": len(seo["h2"]),
                "headings_pregunta": aeo["preguntas"], "enlaces_internos": len(internos),
                "enlaces_internos_lista": internos[:MAX_ENLACES_GUARDADOS], "imgs": len(p.imgs), "imgs_sin_alt": len(seo["sin_alt"]),
                "jsonld_tipos": tipos, "tldr_detectado": aeo["tldr"], "faq": aeo["faq"], "canonical": seo["canon"][:1],
                "canonical_abs": canon_abs, "robots_meta": seo["robots_meta"],
                "noindex": "noindex" in seo["robots_meta"] or "noindex" in xr.lower()}
    return hallazgos, metricas


def _bots_bloqueados(robots):
    bloqueados = []
    nombres = [b.lower() for b in BOTS_IA]
    for bloque in re.split(r"(?i)(?=user-agent:)", robots):
        ua = re.findall(r"(?i)user-agent:\s*(\S+)", bloque)
        if any(u.lower() in nombres for u in ua) and re.search(r"(?im)^\s*disallow:\s*/\s*$", bloque):
            bloqueados += [u for u in ua if u.lower() in nombres]
    return sorted(set(bloqueados))


def analizar_sitio(origen, get=get):
    """Checks de rastreabilidad que valen para todo el dominio. Devuelve (hallazgos, metricas)."""
    hallazgos, add = _recolector(origen, alcance="sitio")
    st, robots, _, _ = get(urljoin(origen, "/robots.txt"), TIMEOUT_SITIO_S)
    robots_ok = st == 200 and bool(robots)
    if robots_ok:
        bloqueados = _bots_bloqueados(robots)
        if bloqueados: add("AEO", "robots.txt bloquea bots de IA", "Info", f"Bloqueados: {', '.join(bloqueados)}. Si es intencional (protección de contenido) está bien; si se quiere ser citado por ChatGPT/Perplexity/AI Overviews, no.", "Decidir explícitamente: permitir OAI-SearchBot/PerplexityBot/ClaudeBot (citación) aunque se bloquee el entrenamiento (GPTBot, Google-Extended, CCBot).", ", ".join(bloqueados), "Bajo", id="aeo:robots")
        if not re.search(r"(?i)sitemap:", robots): add("SEO", "robots.txt sin Sitemap:", "Bajo", "No declara la ubicación del sitemap.", "Añadir 'Sitemap: https://…/sitemap.xml'.", "", "Bajo", id="aeo:robots")
    else: add("SEO", "Sin robots.txt accesible", "Bajo", f"robots.txt devolvió {st}.", "Publicar robots.txt (aunque sea permisivo) con la línea Sitemap.", "", "Bajo", id="aeo:robots")
    llms_ok = get(urljoin(origen, "/llms.txt"), TIMEOUT_SITIO_S)[0] == 200
    if not llms_ok: add("AEO", "Sin llms.txt", "Bajo", "No existe /llms.txt: un mapa en Markdown del sitio para agentes y LLM (propuesta llmstxt.org). No garantiza citas, pero es barato.", "Publicar /llms.txt con descripción del sitio y enlaces a las páginas clave; opcionalmente /llms-full.txt.", "", "Bajo", id="aeo:llms")
    candidatos = [s for s in (sitemaps_de_robots(robots) if robots_ok else []) if sitemap_permitido(s, origen)] or [urljoin(origen, s) for s in ("/sitemap.xml", "/sitemap_index.xml")]
    sm_ok = any(get(s, TIMEOUT_SITIO_S)[0] == 200 for s in candidatos)
    if not sm_ok: add("SEO", "Sin sitemap.xml accesible", "Medio", "No se encontró el sitemap declarado en robots.txt ni /sitemap.xml ni /sitemap_index.xml.", "Generar y publicar sitemap con lastmod real.", "", "Bajo", id="aeo:sitemap")
    return hallazgos, {"robots_txt": robots_ok, "llms_txt": llms_ok, "sitemap": sm_ok}


def ejecutar(url, opc, get=get, pagina=True, sitio=True):
    """Corre los alcances pedidos y devuelve el objeto a guardar: {metricas, hallazgos[, error]}."""
    origen = "{0.scheme}://{0.netloc}".format(urlparse(url))
    resultado = {"metricas": {"origen": origen} if not pagina else {}, "hallazgos": []}
    if pagina:
        status, body, hdr, url_final = get(url, TIMEOUT_PAGINA_S)
        if not body or (status and status >= 400) or status is None:
            resultado["error"] = f"No se pudo obtener la página (status={status}): {body[:200]}"
            resultado["metricas"] = {"url": url, "status": status, "url_final": url_final}
        else:
            resultado["hallazgos"], resultado["metricas"] = analizar_pagina(url, status, body, hdr, url_final, opc)
    if sitio:
        h, m = analizar_sitio(origen, get)
        resultado["hallazgos"] += h
        resultado["metricas"]["sitio"] = m
    return resultado


def main():
    ap = argparse.ArgumentParser(description="Comprobaciones SEO/AEO de una URL y/o de su sitio.")
    ap.add_argument("url"); ap.add_argument("--out", default="hallazgos-aeo.json")
    ap.add_argument("--min-words", type=int, default=500); ap.add_argument("--title-max", type=int, default=60)
    ap.add_argument("--desc-max", type=int, default=160); ap.add_argument("--internal-links-min", type=int, default=2)
    alcance = ap.add_mutually_exclusive_group()
    alcance.add_argument("--sin-checks-sitio", action="store_true", help="Solo checks de la página (robots/llms/sitemap aparte)")
    alcance.add_argument("--solo-sitio", action="store_true", help="Solo robots.txt, llms.txt y sitemap (una vez por dominio)")
    args = ap.parse_args()
    r = ejecutar(args.url, args, pagina=not args.solo_sitio, sitio=not args.sin_checks_sitio)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    resumen = {"ok": "error" not in r, "out": args.out, "hallazgos": len(r["hallazgos"])}
    if "error" in r:
        resumen["error"] = r["error"]
    print(json.dumps(resumen, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
