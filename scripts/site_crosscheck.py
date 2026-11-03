#!/usr/bin/env python3
"""
Cruce entre todas las URLs auditadas de un sitio (solo stdlib): problemas que no se ven
mirando una página aislada.

  - title / meta description / H1 duplicados entre URLs (posible canibalización)
  - URLs del sitemap que responden con error, redirigen o tienen noindex
  - canonical que apunta a una URL fuera del conjunto conocido o con error
  - enlaces internos rotos (status conocido; opcionalmente verifica los desconocidos con tope)
  - páginas huérfanas: ninguna otra página auditada las enlaza

Lee out/urls.json y out/urls/<slug>/aeo.json (salida de aeo_site_checks.py --sin-checks-sitio).

Uso:
  python3 site_crosscheck.py out [--verificar-enlaces 200]
Salida: out/crosscheck.json con {metricas, hallazgos} en el formato de --manual de perf_report_xlsx.py.
"""
import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from url_utils import clave_url, slug_url

UA = "Mozilla/5.0 (compatible; auditoria-rendimiento-frontend/1.0)"
TIMEOUT_S = 15
MAX_EJEMPLOS = 10
HTTP_ERROR = 400
CAMPOS_DUPLICABLES = (
    ("title", "cross:title-duplicado", "Title duplicado en varias URLs", "Alto",
     "Varias URLs comparten el mismo <title>: Google no sabe cuál posicionar y compiten entre sí (canibalización).",
     "Dar a cada URL un title único con su término objetivo; si cubren lo mismo, consolidar y redirigir (301)."),
    ("description", "cross:description-duplicada", "Meta description duplicada en varias URLs", "Medio",
     "Varias URLs comparten la misma meta description: el snippet no diferencia las páginas.",
     "Escribir una description única por URL que responda a su intención concreta."),
    ("h1", "cross:h1-duplicado", "H1 duplicado en varias URLs", "Medio",
     "Varias URLs comparten el mismo H1: señal de contenido duplicado o plantillas sin personalizar.",
     "Usar un H1 único por URL con el tema principal de esa página."),
)


def _hallazgo(url, id, titulo, sev, desc, rec, ev="", esf="Bajo", cat="SEO"):
    return {"url": url, "id": id, "categoria": cat, "titulo": titulo, "severidad": sev, "descripcion": desc,
            "recomendacion": rec, "evidencia": str(ev)[:400], "esfuerzo": esf, "form_factor": "Ambos"}


def _es_error(status):
    return status is None or status >= HTTP_ERROR


def _texto_normalizado(p, campo):
    if campo == "h1":
        valores = p.get("h1_textos") or []
        valor = valores[0] if len(valores) == 1 else ""
    else:
        valor = p.get(campo) or ""
    return " ".join(valor.split()).lower()


def _duplicados(paginas):
    hallazgos = []
    for campo, id, titulo, sev, desc, rec in CAMPOS_DUPLICABLES:
        grupos = {}
        for p in paginas:
            valor = _texto_normalizado(p, campo)
            if valor:
                grupos.setdefault(valor, []).append(p["url"])
        for urls in (g for g in grupos.values() if len(g) > 1):
            for url in urls:
                otras = [u for u in urls if u != url]
                ev = f"También en {len(otras)} URL(s): " + ", ".join(otras[:MAX_EJEMPLOS])
                hallazgos.append(_hallazgo(url, id, titulo, sev, desc, rec, ev, "Medio"))
    return hallazgos


def _estado_en_sitemap(p, estados):
    url, status = p["url"], p.get("status")
    if _es_error(status):
        return [_hallazgo(url, "cross:sitemap-error", "URL del sitemap con error HTTP", "Alto",
                          f"La URL figura en el sitemap pero responde {status or 'sin respuesta'}: Google gasta rastreo en una página inexistente.",
                          "Quitarla del sitemap o restaurar la página; si se movió, redirigir 301 y actualizar el sitemap.", f"status={status}")]
    out = []
    final = p.get("url_final") or url
    if clave_url(final) != clave_url(url):
        out.append(_hallazgo(url, "cross:sitemap-redireccion", "URL del sitemap redirige", "Medio",
                             "El sitemap lista una URL que redirige: debe listar solo URLs finales (200, canónicas).",
                             "Reemplazar en el sitemap la URL por su destino final.", f"→ {final}"))
    if p.get("noindex"):
        out.append(_hallazgo(url, "cross:sitemap-noindex", "URL del sitemap con noindex", "Alto",
                             "La URL está en el sitemap pero pide no ser indexada: señales contradictorias para Google.",
                             "Decidir: si debe posicionar, quitar noindex; si no, sacarla del sitemap.", ""))
    out += _canonical(p, estados)
    return out


def _canonical(p, estados):
    url, canon = p["url"], p.get("canonical_abs")
    if not canon or clave_url(canon) == clave_url(url):
        return []
    clave = clave_url(canon)
    if clave not in estados:
        return [_hallazgo(url, "cross:canonical-externo", "Canonical apunta a una URL fuera del sitemap", "Medio",
                          "El canonical declara como definitiva una URL que no está en el sitemap: o el sitemap está incompleto o el canonical es erróneo.",
                          "Alinear canonical y sitemap: la URL canónica debe estar en el sitemap y viceversa.", canon)]
    if _es_error(estados[clave]):
        return [_hallazgo(url, "cross:canonical-roto", "Canonical apunta a una URL con error", "Alto",
                          f"El canonical apunta a una URL que responde {estados[clave]}: Google puede ignorar ambas.",
                          "Corregir el canonical para que apunte a una URL que responda 200.", canon)]
    return []


def status_http(url):
    """Status de una URL (HEAD y, si no se admite, GET); None si no hay respuesta."""
    for metodo in ("HEAD", "GET"):
        try:
            with urlopen(Request(url, method=metodo, headers={"User-Agent": UA}), timeout=TIMEOUT_S) as r:
                return r.status
        except HTTPError as e:
            if metodo == "HEAD" and e.code in (403, 405, 501):
                continue
            return e.code
        except (URLError, OSError, ValueError):
            return None
    return None


def _verificar_desconocidos(paginas, estados, estado, max_verificar):
    desconocidos = []
    for p in paginas:
        for enlace in p.get("enlaces_internos_lista") or []:
            clave = clave_url(enlace)
            if clave not in estados and clave not in desconocidos:
                desconocidos.append(clave)
    a_verificar = desconocidos[:max_verificar] if estado else []
    verificados = {clave: estado(clave) for clave in a_verificar}
    return verificados, len(desconocidos) - len(a_verificar)


def _enlaces_rotos(paginas, estados):
    out = []
    for p in paginas:
        rotos = sorted({e for e in p.get("enlaces_internos_lista") or []
                        if clave_url(e) in estados and _es_error(estados[clave_url(e)])})
        if rotos:
            out.append(_hallazgo(p["url"], "cross:enlace-roto", "Enlaces internos rotos", "Alto",
                                 f"{len(rotos)} enlace(s) interno(s) llevan a páginas con error: mala experiencia y rastreo desperdiciado.",
                                 "Corregir o quitar cada enlace; si la página se movió, enlazar al destino nuevo.",
                                 "\n".join(rotos[:MAX_EJEMPLOS]), "Bajo"))
    return out


def _huerfanas(paginas):
    if not any(p.get("enlaces_internos_lista") for p in paginas):
        return []
    enlazadas = {clave_url(e) for p in paginas for e in p.get("enlaces_internos_lista") or []
                 if clave_url(e) != clave_url(p["url"])}
    out = []
    for p in paginas:
        clave = clave_url(p["url"])
        if urlparse(clave).path == "/" or _es_error(p.get("status")) or clave in enlazadas:
            continue
        out.append(_hallazgo(p["url"], "cross:huerfana", "Página huérfana (sin enlaces internos entrantes)", "Medio",
                             "Ninguna otra página auditada enlaza a esta URL: Google la descubre solo por el sitemap y le asigna poca autoridad.",
                             "Enlazarla desde páginas relacionadas por tema (categoría, artículos afines, menú o breadcrumbs).", "", "Bajo"))
    return out


def cruzar(paginas, estado=None, max_verificar=0):
    """Cruza las métricas de todas las páginas. `estado(url) -> status` verifica enlaces desconocidos."""
    estados = {clave_url(p["url"]): p.get("status") for p in paginas}
    verificados, sin_verificar = _verificar_desconocidos(paginas, estados, estado, max_verificar)
    estados_enlaces = {**estados, **verificados}
    hallazgos = _duplicados(paginas)
    for p in paginas:
        hallazgos += _estado_en_sitemap(p, estados)
    hallazgos += _enlaces_rotos(paginas, estados_enlaces) + _huerfanas(paginas)
    metricas = {"paginas": len(paginas), "enlaces_verificados": len(verificados), "enlaces_sin_verificar": sin_verificar}
    return {"metricas": metricas, "hallazgos": hallazgos}


def cargar_paginas(out_dir):
    """Métricas de aeo.json por cada URL de urls.json; omite las que no se auditaron."""
    out_dir = Path(out_dir)
    urls = json.loads((out_dir / "urls.json").read_text(encoding="utf-8")).get("urls", [])
    paginas = []
    for u in urls:
        ruta = out_dir / "urls" / slug_url(u["url"]) / "aeo.json"
        if not ruta.is_file():
            continue
        try:
            metricas = json.loads(ruta.read_text(encoding="utf-8")).get("metricas") or {}
        except json.JSONDecodeError as e:
            print(f"aviso: {ruta} no es JSON válido: {e}", file=sys.stderr)
            continue
        paginas.append({**metricas, "url": u["url"]})
    return paginas


def main_args(argv=None):
    ap = argparse.ArgumentParser(description="Cruza los resultados de todas las URLs auditadas de un sitio.")
    ap.add_argument("out", help="Carpeta de salida de audit_site.py (con urls.json y urls/)")
    ap.add_argument("--verificar-enlaces", type=int, default=0,
                    help="Verifica por HTTP hasta N enlaces internos que no están en el sitemap (0 = no)")
    a = ap.parse_args(argv)
    paginas = cargar_paginas(a.out)
    r = cruzar(paginas, estado=status_http if a.verificar_enlaces else None, max_verificar=a.verificar_enlaces)
    destino = Path(a.out) / "crosscheck.json"
    destino.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(destino), **r["metricas"], "hallazgos": len(r["hallazgos"])}, ensure_ascii=False))
    return r


if __name__ == "__main__":
    main_args()
