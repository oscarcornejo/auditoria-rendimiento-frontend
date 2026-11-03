#!/usr/bin/env python3
"""
Descubre todas las URLs auditables de un sitio (solo stdlib).

1. Sitemaps declarados en robots.txt; si no hay, /sitemap.xml y /sitemap_index.xml.
   Sigue índices de forma recursiva y admite .xml.gz.
2. Si no hay sitemap con URLs, rastrea enlaces internos desde la home (BFS con
   límite de profundidad), respetando robots.txt.

Normaliza (sin fragmento ni parámetros de tracking), deduplica, deja solo el mismo
sitio y páginas HTML, y asigna una plantilla por path (/producto/*).

Uso:
  python3 discover_urls.py https://ejemplo.com --out out/urls.json \
      [--max 0] [--include REGEX] [--exclude REGEX] [--crawl-depth 3] [--max-crawl 500]
Salida: {origen, fuente, sitemaps, total, omitidas_por_max, excluidas[], urls[{url, fuente, lastmod, plantilla}]}
"""
import argparse
import gzip
import http.client
import json
import re
import sys
import zlib
from collections import deque
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET

from url_utils import ESQUEMAS_WEB, clave_url, es_html_probable, mismo_sitio, normalizar, plantilla

UA = "Mozilla/5.0 (compatible; auditoria-rendimiento-frontend/1.0)"
TIMEOUT_S = 20
MAX_BYTES = 50 * 1024 * 1024          # límite del protocolo sitemaps (50 MB sin comprimir)
MAX_SITEMAPS = 500                    # tope de archivos sitemap a seguir (protege de índices cíclicos o enormes)
SITEMAPS_POR_DEFECTO = ("/sitemap.xml", "/sitemap_index.xml")
AVISO_MUCHAS_URLS = 500


def fetch_http(url):
    """GET con límite de tamaño. Devuelve (status, bytes, url_final); status None si falla la conexión."""
    if urlparse(url).scheme not in ESQUEMAS_WEB:
        print(f"aviso: se ignora {url}: solo se piden URLs http(s)", file=sys.stderr)
        return None, b"", url
    try:
        with urlopen(Request(url, headers={"User-Agent": UA}), timeout=TIMEOUT_S) as r:
            return r.status, r.read(MAX_BYTES), r.geturl()
    except HTTPError as e:
        return e.code, b"", url
    except (URLError, OSError, ValueError, http.client.HTTPException) as e:
        print(f"aviso: no se pudo obtener {url}: {e}", file=sys.stderr)
        return None, b"", url


def _descomprimir(data):
    if data[:2] != b"\x1f\x8b":
        return data
    try:
        d = zlib.decompressobj(zlib.MAX_WBITS | 16)
        return d.decompress(data, MAX_BYTES)
    except (zlib.error, gzip.BadGzipFile):
        return b""


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def parse_sitemap(data):
    """Devuelve (urls[(loc, lastmod)], sitemaps_hijos[loc]) de un urlset o sitemapindex; ([], []) si no es válido."""
    try:
        raiz = ET.fromstring(_descomprimir(data))
    except ET.ParseError:
        return [], []
    urls, hijos = [], []
    for nodo in raiz:
        campos = {_local(c.tag): (c.text or "").strip() for c in nodo}
        loc = campos.get("loc")
        if not loc:
            continue
        if _local(nodo.tag) == "sitemap":
            hijos.append(loc)
        elif _local(nodo.tag) == "url":
            urls.append((loc, campos.get("lastmod", "")))
    return urls, hijos


def sitemaps_de_robots(robots_txt):
    return re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots_txt or "")


class _Enlaces(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def extraer_enlaces(html, base):
    """Hrefs de <a> resueltos y normalizados, sin repetir y en orden de aparición."""
    p = _Enlaces()
    p.feed(html)
    vistos, out = set(), []
    for href in p.hrefs:
        n = normalizar(href, base=base)
        if n and n not in vistos:
            vistos.add(n)
            out.append(n)
    return out


class _Coleccion:
    """Acumula URLs aceptadas y excluidas aplicando filtros en un solo lugar."""

    def __init__(self, origen, include, exclude):
        self.origen, self.urls, self.excluidas, self._vistas = origen, [], [], set()
        self.include = re.compile(include) if include else None
        self.exclude = re.compile(exclude) if exclude else None

    def motivo_rechazo(self, url):
        if not mismo_sitio(url, self.origen):
            return "otro sitio"
        if not es_html_probable(url):
            return "no es HTML"
        if self.include and not self.include.search(url):
            return "no coincide con --include"
        if self.exclude and self.exclude.search(url):
            return "coincide con --exclude"
        return None

    def agregar(self, loc, fuente, lastmod=""):
        url = normalizar(loc.strip())
        clave = clave_url(url)
        if not url or clave in self._vistas:
            return False
        self._vistas.add(clave)
        motivo = self.motivo_rechazo(url)
        if motivo:
            self.excluir(url, motivo)
            return False
        self.urls.append({"url": url, "fuente": fuente, "lastmod": lastmod, "plantilla": plantilla(url)})
        return True

    def excluir(self, url, motivo):
        self.excluidas.append({"url": url, "motivo": motivo})


def sitemap_permitido(url, origen):
    """Solo sitemaps http(s) del mismo sitio: el protocolo no admite otros hosts y así no se piden
    file://, IPs internas ni dominios ajenos declarados en un sitemap o robots.txt no confiable."""
    return urlparse(url).scheme in ESQUEMAS_WEB and mismo_sitio(url, origen)


def _leer_sitemaps(iniciales, fetch, col):
    permitidos = [s for s in iniciales if sitemap_permitido(s, col.origen)]
    pendientes, visitados = deque(permitidos), set()
    while pendientes and len(visitados) < MAX_SITEMAPS:
        sm = pendientes.popleft()
        if sm in visitados:
            continue
        visitados.add(sm)
        status, data, _ = fetch(sm)
        if status != 200:
            continue
        urls, hijos = parse_sitemap(data)
        pendientes.extend(h for h in hijos if h not in visitados and sitemap_permitido(h, col.origen))
        for loc, lastmod in urls:
            col.agregar(loc, "sitemap", lastmod)
    return sorted(visitados)


def _robots(origen, fetch):
    status, data, _ = fetch(origen + "/robots.txt")
    texto = data.decode("utf-8", "ignore") if status == 200 else ""
    rp = RobotFileParser()
    rp.parse(texto.splitlines())
    return texto, rp


def _rastrear(origen, fetch, col, rp, crawl_depth, max_crawl):
    home = normalizar(origen + "/")
    cola, encolados = deque([(home, 0)]), {clave_url(home)}
    while cola and len(col.urls) < max_crawl:
        url, prof = cola.popleft()
        if not rp.can_fetch(UA, url):
            col.excluir(url, "bloqueada por robots.txt")
            continue
        status, data, url_final = fetch(url)
        if status != 200:
            col.excluir(url, f"HTTP {status}" if status else "sin respuesta")
            continue
        final = normalizar(url_final or url) or url
        encolados.add(clave_url(final))
        if not col.agregar(final, "crawl") or prof >= crawl_depth:
            continue
        for enlace in extraer_enlaces(data.decode("utf-8", "ignore"), final):
            if clave_url(enlace) not in encolados and col.motivo_rechazo(enlace) is None:
                encolados.add(clave_url(enlace))
                cola.append((enlace, prof + 1))


def descubrir(origen, fetch=fetch_http, max_urls=0, include=None, exclude=None, crawl_depth=3, max_crawl=500):
    """Descubre las URLs del sitio. `fetch(url) -> (status, bytes, url_final)` es inyectable para tests."""
    origen = origen.rstrip("/")
    col = _Coleccion(origen, include, exclude)
    robots_txt, rp = _robots(origen, fetch)
    iniciales = sitemaps_de_robots(robots_txt) or [origen + s for s in SITEMAPS_POR_DEFECTO]
    sitemaps = _leer_sitemaps(iniciales, fetch, col)
    fuente = "sitemap"
    if not col.urls:
        fuente = "crawl"
        _rastrear(origen, fetch, col, rp, crawl_depth, max_crawl)
    omitidas = max(0, len(col.urls) - max_urls) if max_urls else 0
    urls = col.urls[:max_urls] if max_urls else col.urls
    return {"origen": origen, "fuente": fuente, "sitemaps": sitemaps, "total": len(urls),
            "omitidas_por_max": omitidas, "excluidas": col.excluidas, "urls": urls}


def main():
    ap = argparse.ArgumentParser(description="Descubre todas las URLs auditables de un sitio.")
    ap.add_argument("url", help="Origen o cualquier URL del sitio")
    ap.add_argument("--out", default="urls.json")
    ap.add_argument("--max", type=int, default=0, help="Tope de URLs (0 = todas)")
    ap.add_argument("--include", help="Regex: solo URLs que coincidan")
    ap.add_argument("--exclude", help="Regex: descartar URLs que coincidan")
    ap.add_argument("--crawl-depth", type=int, default=3, help="Profundidad del rastreo si no hay sitemap")
    ap.add_argument("--max-crawl", type=int, default=500, help="Páginas máximas a rastrear si no hay sitemap")
    a = ap.parse_args()
    p = urlparse(a.url if "://" in a.url else "https://" + a.url)
    if not p.hostname:
        sys.exit(f"URL no válida: {a.url}")
    r = descubrir(f"{p.scheme}://{p.netloc}", max_urls=a.max, include=a.include, exclude=a.exclude,
                  crawl_depth=a.crawl_depth, max_crawl=a.max_crawl)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    if r["total"] > AVISO_MUCHAS_URLS:
        print(f"aviso: {r['total']} URLs; Lighthouse tarda ~1 min por URL (móvil + escritorio). "
              "Considera --lighthouse-por-plantilla en audit_site.py.", file=sys.stderr)
    print(json.dumps({"ok": True, "out": a.out, "fuente": r["fuente"], "total": r["total"],
                      "omitidas_por_max": r["omitidas_por_max"], "excluidas": len(r["excluidas"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
