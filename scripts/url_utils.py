"""
Utilidades de URL compartidas por los scripts de auditoría de sitio completo
(discover_urls, audit_site, site_crosscheck, perf_report_xlsx). Solo stdlib.
"""
import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

PARAMS_TRACKING = re.compile(r"^(utm_\w+|gclid|fbclid|msclkid|dclid|yclid|mc_cid|mc_eid|_ga|_gl|ref|igshid)$", re.I)
EXT_NO_HTML = re.compile(
    r"\.(pdf|jpe?g|png|gif|webp|avif|svg|ico|bmp|tiff?|mp4|webm|mov|mp3|wav|ogg|zip|gz|rar|7z|tar|"
    r"docx?|xlsx?|pptx?|csv|txt|xml|json|js|css|woff2?|ttf|eot|exe|dmg|apk)$", re.I)
LOCALE = re.compile(r"^[a-z]{2}(-[a-z]{2})?$", re.I)
PUERTOS_POR_DEFECTO = {"http": 80, "https": 443}
ESQUEMAS_WEB = ("http", "https")
LARGO_SLUG = 60
LARGO_HASH = 8


def normalizar(href, base=None):
    """URL absoluta y canónica para comparar (sin fragmento ni tracking); None si no es http(s)."""
    if not href or href.startswith("#"):
        return None
    try:
        p = urlparse(urljoin(base, href) if base else href)
        if p.scheme not in ESQUEMAS_WEB or not p.hostname:
            return None
        host, puerto = p.hostname.lower(), p.port
    except ValueError:  # puerto fuera de rango o no numérico, IPv6 mal cerrada
        return None
    if puerto and puerto != PUERTOS_POR_DEFECTO.get(p.scheme):
        host = f"{host}:{puerto}"
    query = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not PARAMS_TRACKING.match(k)])
    return urlunparse((p.scheme, host, p.path or "/", "", query, ""))


def clave_url(url):
    """Clave para unir datos de la misma página que llegan con distinta forma.

    Ignora barra final, mayúsculas del host, esquema http/https y el prefijo www., igual que `mismo_sitio`.
    Es solo una clave de comparación: no se muestra ni se usa para pedir la URL.
    """
    n = normalizar(url) if url else None
    if not n:
        return ""
    p = urlparse(n)
    host = p.netloc[4:] if p.netloc.startswith("www.") else p.netloc
    path = p.path.rstrip("/") or "/"
    return urlunparse(("https", host, path, "", p.query, ""))


def _host_base(url):
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def mismo_sitio(url, origen):
    """True si `url` pertenece al mismo sitio que `origen` (www y sin www cuentan igual)."""
    return bool(_host_base(url)) and _host_base(url) == _host_base(origen)


def es_html_probable(url):
    """Descarta por extensión recursos que no son páginas (imágenes, PDF, assets)."""
    return not EXT_NO_HTML.search(urlparse(url).path)


def plantilla(url):
    """Agrupa URLs por tipo de página según su path: /producto/x → /producto/*; respeta prefijos de idioma."""
    segmentos = [s for s in urlparse(url).path.split("/") if s]
    if not segmentos:
        return "home"
    prefijo = []
    if LOCALE.match(segmentos[0]) and len(segmentos) > 1:
        prefijo, segmentos = [segmentos[0]], segmentos[1:]
    raiz = "/" + "/".join(prefijo + [segmentos[0]])
    return raiz + "/*" if len(segmentos) > 1 else raiz


def slug_url(url):
    """Nombre de carpeta legible y sin colisiones para guardar los resultados de una URL."""
    p = urlparse(url)
    legible = re.sub(r"[^a-zA-Z0-9]+", "-", p.path).strip("-").lower()[:LARGO_SLUG] or "home"
    huella = hashlib.sha1(url.encode("utf-8")).hexdigest()[:LARGO_HASH]
    return f"{legible}-{huella}"
