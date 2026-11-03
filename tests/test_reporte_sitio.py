import json

from reporte_sitio import (PREFIJO_SITIO, cargar_directorio, matriz_checklist, no_cumplen_por_punto, patrones,
                           resumen_por_plantilla, resumen_por_url)
from url_utils import slug_url

H = "https://e.com/"
A = "https://e.com/producto/a"
B = "https://e.com/producto/b"
PLANTILLAS = {H: "home", A: "/producto/*", B: "/producto/*"}


def fila(url, aid, sev="Alto", titulo=None, ff="Móvil", ms="", kb=""):
    """Fila posicional como las de perf_report_xlsx.construir."""
    return ["H-1", url, ff, "Rendimiento", "Imágenes", aid, titulo or aid, sev, 2, 50, ms, kb, "", "", "", 0, "Bajo", "Pendiente", ""]


def informe(url, ff="Móvil", perf=0.5, lcp=3000):
    lh = {"categories": {"performance": {"score": perf}},
          "audits": {"largest-contentful-paint": {"numericValue": lcp, "scoreDisplayMode": "numeric"},
                     "cumulative-layout-shift": {"numericValue": 0.2, "scoreDisplayMode": "numeric"},
                     "total-blocking-time": {"numericValue": 100, "scoreDisplayMode": "numeric"},
                     "image-alt": {"score": 1, "scoreDisplayMode": "binary"}}}
    return {"lh": lh, "url": url, "ff": ff}


class TestResumenPorUrl:
    def test_cuenta_por_severidad_y_ordena_peores_primero(self):
        hs = [fila(A, "x", "Crítico"), fila(A, "y", "Alto"), fila(B, "x", "Medio"), fila(PREFIJO_SITIO + H, "aeo:llms", "Bajo")]
        filas = resumen_por_url(hs, [informe(A, perf=0.3), informe(B, perf=0.9)], [H, A, B], PLANTILLAS, {})
        assert [f["url"] for f in filas] == [A, B, H]
        fa = filas[0]
        assert (fa["Crítico"], fa["Alto"], fa["total"], fa["perf_movil"], fa["lcp_movil"]) == (1, 1, 2, 30, 3000)
        assert filas[2]["total"] == 0

    def test_incluye_pasos_con_error_de_cobertura(self):
        cob = {"urls": [{"url": A, "pasos": {"aeo": "ok", "lh-mobile": "error: boom"}}]}
        filas = resumen_por_url([], [], [A], PLANTILLAS, cob)
        assert filas[0]["errores"] == "lh-mobile"


class TestPatrones:
    def test_agrupa_por_auditoria_con_urls_distintas_y_plantillas(self):
        hs = [fila(A, "offscreen-images", ms=100), fila(A, "offscreen-images", ff="Escritorio", ms=300),
              fila(B, "offscreen-images", ms=200), fila(H, "lcp-lazy-loaded", "Crítico"),
              fila(PREFIJO_SITIO + H, "aeo:llms")]
        p = patrones(hs, 3, PLANTILLAS)
        primero = p[0]
        assert primero["aid"] == "offscreen-images" and primero["urls"] == 2
        assert primero["pct"] == 66.7 and primero["plantillas"] == "/producto/* (2)"
        assert primero["ms_medio"] == 200
        assert all(x["aid"] != "aeo:llms" for x in p)

    def test_ids_genericos_se_separan_por_titulo(self):
        hs = [fila(A, "manual", titulo="Carrusel"), fila(B, "manual", titulo="Iframe")]
        assert len(patrones(hs, 2, PLANTILLAS)) == 2


class TestPorPlantilla:
    def test_agrega_urls_de_cada_plantilla(self):
        filas = [{"url": A, "plantilla": "/producto/*", "perf_movil": 40, "Crítico": 2, "Alto": 1, "total": 5},
                 {"url": B, "plantilla": "/producto/*", "perf_movil": 60, "Crítico": 0, "Alto": 1, "total": 1},
                 {"url": H, "plantilla": "home", "perf_movil": None, "Crítico": 0, "Alto": 0, "total": 0}]
        r = {x["plantilla"]: x for x in resumen_por_plantilla(filas)}
        assert r["/producto/*"] == {"plantilla": "/producto/*", "urls": 2, "perf_medio": 50, "Crítico": 2, "Alto": 2,
                                    "hallazgos_por_url": 3.0, "peor": A}
        assert r["home"]["perf_medio"] is None


CHECK = [("SEO", "Alt en imágenes", ["image-alt", "aeo:alt"]), ("LCP", "LCP", ["largest-contentful-paint"]),
         ("Manual", "Sin ids", []), ("Sitio", "robots", ["aeo:robots"])]


class TestChecklist:
    def test_matriz_por_url(self):
        hs = [fila(A, "aeo:alt"), fila(B, "largest-contentful-paint")]
        m = matriz_checklist(hs, CHECK, [A, B], [informe(A), informe(B)], aeo_por_url={A}, ids_sitio={"aeo:robots"})
        assert [p for p, _ in m["puntos"]] == ["Alt en imágenes", "LCP"]
        assert m["filas"][0] == [A, "No cumple", "Cumple"]
        assert m["filas"][1] == [B, "Cumple", "No cumple"]

    def test_no_cumplen_por_punto_cuenta_urls_y_sitio(self):
        hs = [fila(A, "aeo:alt"), fila(A, "aeo:alt", ff="Escritorio"), fila(B, "image-alt"), fila(PREFIJO_SITIO + H, "aeo:robots")]
        assert no_cumplen_por_punto(hs, ["image-alt", "aeo:alt"]) == "2"
        assert no_cumplen_por_punto(hs, ["aeo:robots"]) == "sitio"
        assert no_cumplen_por_punto(hs, ["x"]) == ""


class TestCargarDirectorio:
    def test_clasifica_archivos_y_asigna_url_por_slug(self, tmp_path):
        (tmp_path / "urls.json").write_text(json.dumps({"origen": "https://e.com", "urls": [{"url": A, "plantilla": "/producto/*"}]}))
        carpeta = tmp_path / "urls" / slug_url(A)
        carpeta.mkdir(parents=True)
        for nombre in ("lh-mobile.json", "psi-desktop.json", "aeo.json", "browser.json", "browser-hallazgos.json"):
            (carpeta / nombre).write_text("{}")
        for nombre in ("sitio-aeo.json", "crosscheck.json", "cobertura.json", "manual.json", "lh-base-mobile.json"):
            (tmp_path / nombre).write_text("{}")
        d = cargar_directorio(tmp_path)
        assert sorted(p.name for p, _ in d["informes"]) == ["lh-mobile.json", "psi-desktop.json"]
        assert all(u == A for _, u in d["informes"])
        nombres = {p.name: u for p, u in d["manuales"]}
        assert set(nombres) == {"aeo.json", "browser-hallazgos.json", "sitio-aeo.json", "crosscheck.json", "manual.json"}
        assert nombres["aeo.json"] == A and nombres["manual.json"] is None
        assert d["cobertura"] == {} and d["urls"]["origen"] == "https://e.com" and d["crosscheck"] is True
