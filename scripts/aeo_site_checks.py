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
