#!/usr/bin/env python3
"""
Orquesta la auditoría completa de un sitio: corre cada medición sobre TODAS las URLs de
urls.json (salida de discover_urls.py) y deja un registro de cobertura por URL.

Por URL, en out/urls/<slug>/:
  aeo.json                      SEO/AEO de la página (aeo_site_checks.py --sin-checks-sitio), concurrente
  lh-mobile.json lh-desktop.json   Lighthouse, SERIAL (en paralelo las métricas se distorsionan)
  psi-mobile.json psi-desktop.json PageSpeed Insights (--motor psi; usa PSI_API_KEY si existe)
  browser.json browser-hallazgos.json   recolector Playwright (--browser)
Una vez por sitio: out/sitio-aeo.json (robots.txt, llms.txt, sitemap).
Al final: out/cobertura.json, out/errores.json y out/crosscheck.json (site_crosscheck.py).

Reanudable: si una salida ya existe y es válida, no se repite.

Uso:
  python3 audit_site.py --urls out/urls.json --out out [--motor lighthouse|psi|ninguno]
      [--lighthouse-por-plantilla 0] [--solo-movil] [--browser] [--concurrency 4] [--verificar-enlaces 0]
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

import site_crosscheck
from url_utils import slug_url

SCRIPTS = Path(__file__).resolve().parent
CHROME_FLAGS = "--headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage"
PSI_API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
PSI_CATEGORIAS = "&category=performance&category=accessibility&category=best-practices&category=seo"
TIMEOUTS_S = {"aeo": 90, "sitio": 60, "lighthouse": 240, "psi": 180, "browser": 180}
LARGO_ERROR = 300
MOTORES = ("lighthouse", "psi", "ninguno")
SIN_SALIDA = "sin archivo de salida"


@dataclass(frozen=True)
class Paso:
    nombre: str
    url: str
    salida: Path
    cmd: tuple
    timeout: int


def seleccionar_lighthouse(urls, por_plantilla):
    """URLs que reciben Lighthouse/PSI: todas (0) o las primeras N de cada plantilla."""
    if not por_plantilla:
        return {u["url"] for u in urls}
    conteo, elegidas = {}, set()
    for u in urls:
        clave = u.get("plantilla", "")
        if conteo.get(clave, 0) < por_plantilla:
            conteo = {**conteo, clave: conteo.get(clave, 0) + 1}
            elegidas.add(u["url"])
    return elegidas


def _dispositivos(opc):
    return ("mobile",) if opc.solo_movil else ("mobile", "desktop")


def _paso_lighthouse(url, carpeta, disp):
    salida = carpeta / f"lh-{disp}.json"
    cmd = ["npx", "-y", "lighthouse", url, "--output=json", f"--output-path={salida}", "--locale=es",
           f"--chrome-flags={CHROME_FLAGS}", "--quiet"] + (["--preset=desktop"] if disp == "desktop" else [])
    return Paso(f"lh-{disp}", url, salida, tuple(cmd), TIMEOUTS_S["lighthouse"])


def _paso_psi(url, carpeta, disp):
    salida = carpeta / f"psi-{disp}.json"
    clave = os.environ.get("PSI_API_KEY")
    api = f"{PSI_API}?url={quote(url, safe='')}&strategy={disp}{PSI_CATEGORIAS}&locale=es" + (f"&key={clave}" if clave else "")
    return Paso(f"psi-{disp}", url, salida, ("curl", "-sS", "--fail-with-body", api, "-o", str(salida)), TIMEOUTS_S["psi"])


def pasos_de_url(url, out_dir, opc, con_lighthouse):
    """Pasos a ejecutar para una URL, con su archivo de salida en out/urls/<slug>/."""
    carpeta = Path(out_dir) / "urls" / slug_url(url)
    aeo = carpeta / "aeo.json"
    pasos = [Paso("aeo", url, aeo, (sys.executable, str(SCRIPTS / "aeo_site_checks.py"), url, "--out", str(aeo),
                                    "--sin-checks-sitio"), TIMEOUTS_S["aeo"])]
    if con_lighthouse and opc.motor == "lighthouse":
        pasos += [_paso_lighthouse(url, carpeta, d) for d in _dispositivos(opc)]
    elif con_lighthouse and opc.motor == "psi":
        pasos += [_paso_psi(url, carpeta, d) for d in _dispositivos(opc)]
    if opc.browser:
        browser = carpeta / "browser.json"
        pasos.append(Paso("browser", url, browser, ("node", str(SCRIPTS / "run_collect.js"), url, str(browser)), TIMEOUTS_S["browser"]))
    return pasos


def _no_aplica(opc):
    if opc.motor == "ninguno":
        return {}
    prefijo = "lh" if opc.motor == "lighthouse" else "psi"
    return {f"{prefijo}-{d}": "no aplica: fuera de la muestra --lighthouse-por-plantilla" for d in _dispositivos(opc)}


def runner_subproceso(paso):
    """Ejecuta el comando del paso. Devuelve (código, stderr)."""
    paso.salida.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(list(paso.cmd), capture_output=True, text=True, timeout=paso.timeout)
        return r.returncode, r.stderr
    except subprocess.TimeoutExpired:
        return None, f"tiempo agotado ({paso.timeout} s)"
    except FileNotFoundError as e:
        return None, f"comando no encontrado: {e.filename}"


def _error_en_salida(salida):
    """Mensaje de error si la salida falta, no es JSON o declara un error; None si es válida."""
    if not salida.is_file() or salida.stat().st_size == 0:
        return SIN_SALIDA
    try:
        data = json.loads(salida.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return f"salida no es JSON válido: {e}"
    if not isinstance(data, dict):
        return None
    err = data.get("error") or data.get("runtimeError")
    if isinstance(err, dict):
        return err.get("message") or err.get("code") or json.dumps(err)[:LARGO_ERROR]
    return str(err) if err else None


def ejecutar_paso(paso, runner):
    """Estado del paso: 'reutilizado', 'ok' o 'error: …'. Nunca lanza."""
    if _error_en_salida(paso.salida) is None:
        return "reutilizado"
    try:
        codigo, stderr = runner(paso)
    except Exception as e:  # el runner es externo: cualquier fallo queda registrado, no detiene el resto
        return f"error: {type(e).__name__}: {e}"[:LARGO_ERROR]
    error = _error_en_salida(paso.salida)
    if codigo == 0 and error is None:
        return "ok"
    if error is None or error == SIN_SALIDA:
        error = (stderr or "").strip() or error or f"código de salida {codigo}"
    return f"error: {error}"[:LARGO_ERROR]


def _correr(pasos, runner, concurrencia):
    if concurrencia <= 1:
        return [ejecutar_paso(p, runner) for p in pasos]
    with ThreadPoolExecutor(max_workers=concurrencia) as ex:
        return list(ex.map(lambda p: ejecutar_paso(p, runner), pasos))


def _progreso(etiqueta, total):
    print(f"[audit_site] {etiqueta}: {total} paso(s)", file=sys.stderr)


def _leer_urls(ruta):
    data = json.loads(Path(ruta).read_text(encoding="utf-8"))
    urls = data.get("urls") if isinstance(data, dict) else None
    if not urls or not all(isinstance(u, dict) and u.get("url") for u in urls):
        raise ValueError(f"{ruta}: se esperaba {{'urls': [{{'url': ...}}]}} (salida de discover_urls.py)")
    origen = data.get("origen") or "{0.scheme}://{0.netloc}".format(urlparse(urls[0]["url"]))
    return origen, urls


def _paso_sitio(origen, out_dir):
    salida = Path(out_dir) / "sitio-aeo.json"
    cmd = (sys.executable, str(SCRIPTS / "aeo_site_checks.py"), origen, "--out", str(salida), "--solo-sitio")
    return Paso("sitio", origen, salida, cmd, TIMEOUTS_S["sitio"])


def _ejecutar_todo(pasos, runner, opc):
    """HTTP concurrente (aeo, sitio); Lighthouse/PSI y navegador en serie. Devuelve {(nombre, url): estado}."""
    http = [p for p in pasos if p.nombre in ("aeo", "sitio")]
    serie = [p for p in pasos if p not in http]
    _progreso("checks HTTP", len(http))
    estados = dict(zip(((p.nombre, p.url) for p in http), _correr(http, runner, opc.concurrency)))
    _progreso("mediciones en serie", len(serie))
    for i, p in enumerate(serie, 1):
        print(f"[audit_site] {i}/{len(serie)} {p.nombre} {p.url}", file=sys.stderr)
        estados = {**estados, (p.nombre, p.url): ejecutar_paso(p, runner)}
    return estados


def _cobertura(urls, pasos_por_url, estados, con_lh, opc):
    filas = []
    for u in urls:
        url = u["url"]
        pasos = {p.nombre: estados[(p.nombre, url)] for p in pasos_por_url[url]}
        extra = {} if url in con_lh else _no_aplica(opc)
        filas.append({"url": url, "slug": slug_url(url), "plantilla": u.get("plantilla", ""), "pasos": {**pasos, **extra}})
    return filas


def _escribir(ruta, data):
    Path(ruta).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def auditar(urls_json, out_dir, opc, runner=runner_subproceso):
    """Audita todas las URLs; escribe cobertura.json y errores.json y devuelve la cobertura."""
    out_dir = Path(out_dir)
    origen, urls = _leer_urls(urls_json)
    con_lh = seleccionar_lighthouse(urls, opc.lighthouse_por_plantilla)
    pasos_por_url = {u["url"]: pasos_de_url(u["url"], out_dir, opc, u["url"] in con_lh) for u in urls}
    sitio = _paso_sitio(origen, out_dir)
    todos = [sitio] + [p for ps in pasos_por_url.values() for p in ps]
    estados = _ejecutar_todo(todos, runner, opc)
    filas = _cobertura(urls, pasos_por_url, estados, con_lh, opc)
    errores = [{"url": f["url"], "paso": n, "error": e} for f in filas for n, e in f["pasos"].items() if e.startswith("error")]
    cobertura = {"generado": datetime.datetime.now().isoformat(timespec="seconds"), "origen": origen, "total": len(urls),
                 "motor": opc.motor, "lighthouse_por_plantilla": opc.lighthouse_por_plantilla,
                 "sitio": estados[(sitio.nombre, sitio.url)], "urls": filas}
    _escribir(out_dir / "cobertura.json", cobertura)
    _escribir(out_dir / "errores.json", errores)
    if opc.crosscheck:
        site_crosscheck.main_args([str(out_dir), "--verificar-enlaces", str(opc.verificar_enlaces)])
    return cobertura


def main():
    ap = argparse.ArgumentParser(description="Audita todas las URLs descubiertas de un sitio.")
    ap.add_argument("--urls", required=True, help="urls.json de discover_urls.py")
    ap.add_argument("--out", required=True, help="Carpeta de salida")
    ap.add_argument("--motor", choices=MOTORES, default="lighthouse", help="Medición de laboratorio por URL")
    ap.add_argument("--lighthouse-por-plantilla", type=int, default=0,
                    help="Lighthouse/PSI solo en las primeras N URLs de cada plantilla (0 = todas)")
    ap.add_argument("--solo-movil", action="store_true", help="Lighthouse/PSI solo en móvil")
    ap.add_argument("--browser", action="store_true", help="Recolector Playwright por URL (requiere playwright)")
    ap.add_argument("--concurrency", type=int, default=4, help="Checks HTTP en paralelo (Lighthouse siempre en serie)")
    ap.add_argument("--verificar-enlaces", type=int, default=0, help="Verifica hasta N enlaces internos fuera del sitemap")
    ap.add_argument("--sin-crosscheck", dest="crosscheck", action="store_false", help="No ejecutar site_crosscheck.py")
    a = ap.parse_args()
    if a.concurrency < 1 or a.lighthouse_por_plantilla < 0 or a.verificar_enlaces < 0:
        sys.exit("--concurrency debe ser ≥ 1; --lighthouse-por-plantilla y --verificar-enlaces, ≥ 0")
    Path(a.out).mkdir(parents=True, exist_ok=True)
    try:
        cob = auditar(a.urls, a.out, a)
    except (OSError, ValueError) as e:
        sys.exit(f"audit_site: {e}")
    errores = sum(1 for u in cob["urls"] for e in u["pasos"].values() if e.startswith("error"))
    print(json.dumps({"ok": True, "out": a.out, "urls": cob["total"], "pasos_con_error": errores}, ensure_ascii=False))


if __name__ == "__main__":
    main()
