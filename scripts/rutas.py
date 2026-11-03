#!/usr/bin/env python3
"""
Carpeta de salida de una auditoría: <Documentos>/auditorias-rendimiento/<dominio>-<fecha>/.

Uso:
  OUT="$(python3 rutas.py https://ejemplo.com)"   # crea la carpeta e imprime su ruta absoluta

<Documentos> es, en orden: $AUDITORIA_OUT_BASE, la carpeta de documentos de XDG (Linux),
~/Documents o ~/Documentos si existe, y si no ~/Documents. Solo stdlib.
"""
import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

CARPETA_RAIZ = "auditorias-rendimiento"
NOMBRES_DOCUMENTOS = ("Documents", "Documentos")
VARIABLE_BASE = "AUDITORIA_OUT_BASE"
TIMEOUT_XDG_S = 5


def _xdg_documentos():
    """Ruta de documentos según xdg-user-dir (Linux con escritorio); None si no está disponible."""
    if not shutil.which("xdg-user-dir"):
        return None
    try:
        r = subprocess.run(["xdg-user-dir", "DOCUMENTS"], capture_output=True, text=True, timeout=TIMEOUT_XDG_S)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() or None


def carpeta_documentos(home=None, xdg=_xdg_documentos):
    """Carpeta base donde se guardan las auditorías."""
    if os.environ.get(VARIABLE_BASE):
        return Path(os.environ[VARIABLE_BASE]).expanduser()
    home = Path(home) if home else Path.home()
    desde_xdg = xdg()
    # xdg-user-dir devuelve el propio home cuando la carpeta no está configurada
    if desde_xdg and Path(desde_xdg) != home and Path(desde_xdg).is_dir():
        return Path(desde_xdg)
    existentes = [home / n for n in NOMBRES_DOCUMENTOS if (home / n).is_dir()]
    return existentes[0] if existentes else home / NOMBRES_DOCUMENTOS[0]


def _nombre_sitio(url):
    p = urlparse(url if "://" in url else "https://" + url)
    try:
        host, puerto = (p.hostname or "").lower(), p.port
    except ValueError as e:
        raise ValueError(f"URL no válida: {url}") from e
    if not host:
        raise ValueError(f"URL no válida: {url}")
    host = host[4:] if host.startswith("www.") else host
    return f"{host}-{puerto}" if puerto else host


def carpeta_auditoria(url, base=None, fecha=None):
    """<base>/auditorias-rendimiento/<dominio>-<AAAA-MM-DD> (no la crea)."""
    base = Path(base) if base else carpeta_documentos()
    fecha = fecha or datetime.date.today()
    return base / CARPETA_RAIZ / f"{_nombre_sitio(url)}-{fecha.isoformat()}"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        sys.exit("Uso: rutas.py <url-del-sitio>")
    try:
        ruta = carpeta_auditoria(argv[0]).resolve()
        ruta.mkdir(parents=True, exist_ok=True)
    except (ValueError, OSError) as e:
        sys.exit(f"No se pudo preparar la carpeta de salida: {e}")
    print(ruta)


if __name__ == "__main__":
    main()
