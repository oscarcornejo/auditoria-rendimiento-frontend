"""
Vistas de sitio completo para el reporte Excel (las usa perf_report_xlsx.py):

  Por URL            una fila por URL: puntajes, LCP/CLS/TBT móvil, hallazgos por severidad, pasos con error
  Por plantilla      agregado por tipo de página (/producto/*, home…) con la peor URL de cada una
  Patrones           el mismo problema repetido en muchas URLs: cuántas, qué % del sitio, en qué plantillas
  Checklist por URL  matriz URL × punto de control (Cumple / No cumple / —)
  Cobertura          qué se midió en cada URL, qué falló y qué URLs se excluyeron del descubrimiento

Además `cargar_directorio` reúne los JSON de una carpeta de audit_site.py.
Los hallazgos llegan como filas posicionales de perf_report_xlsx.construir.
"""
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import mean

from openpyxl.utils import get_column_letter

from url_utils import clave_url, plantilla as plantilla_por_path, slug_url
from xlsx_estilos import COLORES, COLORES_CHECK, pintar_estado, tabla

I_URL, I_FF, I_AREA, I_AID, I_TITULO, I_SEV, I_MS, I_KB = 1, 2, 4, 5, 6, 7, 10, 11
PREFIJO_SITIO = "(sitio) "
SEVERIDADES = ("Crítico", "Alto", "Medio", "Bajo", "Info")
ORDEN_SEV = {s: i for i, s in enumerate(SEVERIDADES)}
IDS_GENERICOS = {"manual", "aeo:otro", ""}
MAX_EJEMPLOS = 3
SIN_EVALUAR = "—"
MODOS_NO_EVALUADOS = ("notApplicable", "manual", "error")
INFORMES = ("lh-*.json", "psi-*.json")
MANUALES_POR_URL = ("aeo.json", "browser-hallazgos.json")
MANUALES_SITIO = ("sitio-aeo.json", "crosscheck.json")


def es_de_sitio(fila):
    return str(fila[I_URL]).startswith(PREFIJO_SITIO)


def _por_url(hallazgos):
    grupos = {}
    for h in hallazgos:
        if not es_de_sitio(h):
            grupos.setdefault(clave_url(h[I_URL]), []).append(h)
    return grupos


def _mapa_plantillas(urls, plantillas):
    por_clave = {clave_url(u): p for u, p in plantillas.items()}
    return {clave_url(u): por_clave.get(clave_url(u)) or plantilla_por_path(u) for u in urls}


def _metricas_informe(informes):
    """{(clave, ff): {perf, lcp, cls, tbt}} a partir de los informes de Lighthouse/PSI."""
    out = {}
    for inf in informes:
        lh, audits = inf["lh"], inf["lh"].get("audits", {})
        score = (lh.get("categories", {}).get("performance") or {}).get("score")
        valor = lambda aid: (audits.get(aid) or {}).get("numericValue")
        out[(clave_url(inf["url"]), inf["ff"])] = {"perf": None if score is None else round(score * 100),
                                                   "lcp": valor("largest-contentful-paint"),
                                                   "cls": valor("cumulative-layout-shift"), "tbt": valor("total-blocking-time")}
    return out


def _errores_cobertura(cobertura):
    return {clave_url(u["url"]): ", ".join(n for n, e in u.get("pasos", {}).items() if str(e).startswith("error"))
            for u in (cobertura or {}).get("urls", [])}


def _redondear(v, dec=0):
    if v is None:
        return None
    return round(v, dec) if dec else round(v)


def resumen_por_url(hallazgos, informes, urls, plantillas, cobertura):
    """Una fila por URL auditada, ordenadas de peor a mejor."""
    grupos, mets, errores = _por_url(hallazgos), _metricas_informe(informes), _errores_cobertura(cobertura)
    mapa = _mapa_plantillas(urls, plantillas)
    filas = []
    for url in urls:
        clave = clave_url(url)
        hs, movil, escritorio = grupos.get(clave, []), mets.get((clave, "Móvil"), {}), mets.get((clave, "Escritorio"), {})
        conteo = {s: sum(1 for h in hs if h[I_SEV] == s) for s in SEVERIDADES}
        filas.append({"url": url, "plantilla": mapa[clave], "perf_movil": movil.get("perf"), "perf_escritorio": escritorio.get("perf"),
                      "lcp_movil": _redondear(movil.get("lcp")), "cls_movil": _redondear(movil.get("cls"), 3),
                      "tbt_movil": _redondear(movil.get("tbt")), **conteo, "total": len(hs), "errores": errores.get(clave, "")})
    return sorted(filas, key=lambda f: (-f["Crítico"], -f["Alto"], -f["total"],
                                        f["perf_movil"] if f["perf_movil"] is not None else 101))


def _clave_patron(h):
    aid = str(h[I_AID] or "")
    return (aid, h[I_TITULO]) if aid in IDS_GENERICOS else (aid, None)


def _numeros(valores):
    return [v for v in valores if isinstance(v, (int, float)) and not isinstance(v, bool)]


def _fila_patron(clave, hs, total_urls, mapa):
    urls = list(dict.fromkeys(clave_url(h[I_URL]) for h in hs))
    conteo = Counter(mapa.get(u) or plantilla_por_path(u) for u in urls)
    ms, kb = _numeros(h[I_MS] for h in hs), _numeros(h[I_KB] for h in hs)
    return {"aid": clave[0], "titulo": hs[0][I_TITULO], "area": hs[0][I_AREA],
            "severidad": min((h[I_SEV] for h in hs), key=lambda s: ORDEN_SEV.get(s, 9)),
            "urls": len(urls), "pct": round(len(urls) / total_urls * 100, 1) if total_urls else 0,
            "plantillas": ", ".join(f"{p} ({n})" for p, n in conteo.most_common()),
            "ms_medio": round(mean(ms)) if ms else None, "kb_medio": round(mean(kb)) if kb else None,
            "ejemplos": "\n".join(urls[:MAX_EJEMPLOS])}


def patrones(hallazgos, total_urls, plantillas):
    """Problemas agrupados por auditoría con el nº de URLs distintas afectadas (excluye los de sitio)."""
    grupos = {}
    for h in hallazgos:
        if not es_de_sitio(h):
            grupos.setdefault(_clave_patron(h), []).append(h)
    mapa = {clave_url(u): p for u, p in plantillas.items()}
    filas = [_fila_patron(k, hs, total_urls, mapa) for k, hs in grupos.items()]
    return sorted(filas, key=lambda f: (-f["urls"], ORDEN_SEV.get(f["severidad"], 9), -(f["ms_medio"] or 0)))


def resumen_por_plantilla(filas_url):
    """Agrega las filas de resumen_por_url por plantilla; `peor` es la primera (ya vienen ordenadas)."""
    grupos = {}
    for f in filas_url:
        grupos.setdefault(f["plantilla"], []).append(f)
    out = []
    for p, fs in grupos.items():
        perfs = [f["perf_movil"] for f in fs if f["perf_movil"] is not None]
        out.append({"plantilla": p, "urls": len(fs), "perf_medio": round(mean(perfs)) if perfs else None,
                    "Crítico": sum(f["Crítico"] for f in fs), "Alto": sum(f["Alto"] for f in fs),
                    "hallazgos_por_url": round(sum(f["total"] for f in fs) / len(fs), 1), "peor": fs[0]["url"]})
    return sorted(out, key=lambda x: (-x["Crítico"], -x["Alto"], -x["urls"]))


def _evaluados_por_url(informes, urls, aeo_por_url, crosscheck):
    evaluados = {clave_url(u): set() for u in urls}
    for inf in informes:
        ids = {aid for aid, a in inf["lh"].get("audits", {}).items() if a.get("scoreDisplayMode") not in MODOS_NO_EVALUADOS}
        evaluados.setdefault(clave_url(inf["url"]), set()).update(ids)
    aeo = {clave_url(u) for u in aeo_por_url}
    return {c: ids | ({"aeo:*"} if c in aeo else set()) | ({"cross:*"} if crosscheck else set()) for c, ids in evaluados.items()}


def _evaluado(aid, ids):
    return aid in ids or f"{aid.split(':', 1)[0]}:*" in ids


def matriz_checklist(hallazgos, check, urls, informes, aeo_por_url=(), ids_sitio=(), crosscheck=False):
    """Puntos del checklist evaluables por URL (sin los que solo aplican al sitio) × URL."""
    puntos = [(punto, ids) for _, punto, ids in check if ids and not set(ids) <= set(ids_sitio)]
    fallidos = {c: {h[I_AID] for h in hs} for c, hs in _por_url(hallazgos).items()}
    evaluados = _evaluados_por_url(informes, urls, aeo_por_url, crosscheck)
    filas = []
    for url in urls:
        c = clave_url(url)
        celdas = ["No cumple" if set(ids) & fallidos.get(c, set()) else
                  "Cumple" if any(_evaluado(i, evaluados.get(c, set())) for i in ids) else SIN_EVALUAR for _, ids in puntos]
        filas.append([url] + celdas)
    return {"puntos": puntos, "filas": filas}


def no_cumplen_por_punto(hallazgos, ids):
    """Texto para la columna 'URLs que no cumplen' del Checklist global: 'N', 'sitio', 'N + sitio' o ''."""
    ids = set(ids)
    urls = {clave_url(h[I_URL]) for h in hallazgos if h[I_AID] in ids and not es_de_sitio(h)}
    sitio = any(h[I_AID] in ids and es_de_sitio(h) for h in hallazgos)
    partes = ([str(len(urls))] if urls else []) + (["sitio"] if sitio else [])
    return " + ".join(partes)


def _leer_json(ruta):
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"aviso: no se pudo leer {ruta}: {e}", file=sys.stderr)
        return None


def _es_base(ruta):
    return "-base-" in ruta.name or ruta.name.startswith(("lh-base", "psi-base"))


def cargar_directorio(directorio):
    """Clasifica los JSON de una carpeta de audit_site.py. Las rutas bajo urls/<slug>/ se asocian a su URL."""
    d = Path(directorio)
    urls_meta = _leer_json(d / "urls.json") if (d / "urls.json").is_file() else None
    por_slug = {}
    if urls_meta:
        por_slug = {slug_url(u["url"]): u["url"] for u in urls_meta.get("urls", []) if u.get("url")}
    url_de = lambda ruta: por_slug.get(ruta.parent.name) if ruta.parent.parent.name == "urls" else None
    informes = [(r, url_de(r)) for patron in INFORMES for r in sorted(d.rglob(patron)) if not _es_base(r)]
    manuales = [(r, url_de(r)) for nombre in MANUALES_POR_URL for r in sorted(d.glob(f"urls/*/{nombre}"))]
    manuales += [(d / n, None) for n in MANUALES_SITIO if (d / n).is_file()]
    manuales += [(r, None) for r in sorted(d.glob("manual*.json"))]
    cobertura = _leer_json(d / "cobertura.json") if (d / "cobertura.json").is_file() else None
    return {"informes": informes, "manuales": manuales, "cobertura": cobertura, "urls": urls_meta,
            "crosscheck": (d / "crosscheck.json").is_file()}


# ---------- Hojas ----------
def _hoja_por_url(wb, filas):
    cols = ["URL", "Plantilla", "Rend. móvil", "Rend. escritorio", "LCP móvil (ms)", "CLS móvil", "TBT móvil (ms)",
            *SEVERIDADES, "Total hallazgos", "Pasos con error"]
    tabla(wb.create_sheet("Por URL"), cols, ([f["url"], f["plantilla"], f["perf_movil"], f["perf_escritorio"], f["lcp_movil"],
                                              f["cls_movil"], f["tbt_movil"], *(f[s] for s in SEVERIDADES), f["total"], f["errores"]]
                                             for f in filas), [60, 18, 10, 10, 12, 10, 12, 8, 8, 8, 8, 8, 10, 24])


def _hoja_por_plantilla(wb, filas):
    cols = ["Plantilla", "URLs", "Rend. móvil medio", "Crítico", "Alto", "Hallazgos por URL", "Peor URL"]
    tabla(wb.create_sheet("Por plantilla"), cols, ([f["plantilla"], f["urls"], f["perf_medio"], f["Crítico"], f["Alto"],
                                                    f["hallazgos_por_url"], f["peor"]] for f in filas), [24, 8, 14, 9, 9, 14, 60])


def _hoja_patrones(wb, filas):
    ws = wb.create_sheet("Patrones")
    cols = ["Auditoría (id)", "Hallazgo", "Área", "Severidad máx.", "URLs afectadas", "% del sitio", "Plantillas",
            "Ahorro medio (ms)", "Ahorro medio (KB)", "Ejemplos"]
    tabla(ws, cols, ([f["aid"], f["titulo"], f["area"], f["severidad"], f["urls"], f["pct"], f["plantillas"],
                      f["ms_medio"], f["kb_medio"], f["ejemplos"]] for f in filas), [26, 42, 14, 12, 10, 10, 30, 12, 12, 60])
    pintar_estado(ws, "D", ws.max_row, colores=COLORES)


def _hoja_checklist_por_url(wb, matriz):
    ws = wb.create_sheet("Checklist por URL")
    tabla(ws, ["URL"] + [p for p, _ in matriz["puntos"]], matriz["filas"], [60] + [18] * len(matriz["puntos"]))
    for i in range(2, len(matriz["puntos"]) + 2):
        pintar_estado(ws, get_column_letter(i), ws.max_row, colores=COLORES_CHECK)


def _hoja_cobertura(wb, cobertura, urls_meta):
    ws = wb.create_sheet("Cobertura")
    filas_cob = (cobertura or {}).get("urls", [])
    pasos = list(dict.fromkeys(n for u in filas_cob for n in u.get("pasos", {})))
    tabla(ws, ["URL", "Plantilla", *pasos], ([u["url"], u.get("plantilla", ""), *(u["pasos"].get(p, "") for p in pasos)]
                                             for u in filas_cob), [60, 18] + [22] * len(pasos))
    meta = urls_meta or {}
    ws.append([])
    ws.append(["Descubrimiento", f"fuente={meta.get('fuente', '?')}", f"URLs={meta.get('total', len(filas_cob))}",
               f"omitidas por --max={meta.get('omitidas_por_max', 0)}", f"checks de sitio={(cobertura or {}).get('sitio', '?')}"])
    excluidas = meta.get("excluidas", [])
    if excluidas:
        ws.append([]); ws.append(["URL excluida", "Motivo"])
        for e in excluidas:
            ws.append([e.get("url", ""), e.get("motivo", "")])


def agregar_hojas(wb, hallazgos, informes, check, contexto):
    """Añade las vistas de sitio completo. `contexto`: {urls (urls.json), cobertura, crosscheck, ids_sitio}."""
    urls_meta, cobertura = contexto.get("urls") or {}, contexto.get("cobertura") or {}
    lista = [u["url"] for u in urls_meta.get("urls", [])] or list(dict.fromkeys(
        [h[I_URL] for h in hallazgos if not es_de_sitio(h) and h[I_URL]] + [inf["url"] for inf in informes]))
    plantillas = {u["url"]: u.get("plantilla") for u in urls_meta.get("urls", [])}
    aeo_ok = [u["url"] for u in cobertura.get("urls", []) if u.get("pasos", {}).get("aeo") in ("ok", "reutilizado")] or \
             [h[I_URL] for h in hallazgos if str(h[I_AID]).startswith("aeo:")]
    filas = resumen_por_url(hallazgos, informes, lista, plantillas, cobertura)
    _hoja_por_url(wb, filas)
    _hoja_por_plantilla(wb, resumen_por_plantilla(filas))
    _hoja_patrones(wb, patrones(hallazgos, len(lista), plantillas))
    _hoja_checklist_por_url(wb, matriz_checklist(hallazgos, check, lista, informes, aeo_ok,
                                                 contexto.get("ids_sitio", ()), contexto.get("crosscheck", False)))
    if cobertura or urls_meta:
        _hoja_cobertura(wb, cobertura, urls_meta)
    return filas
