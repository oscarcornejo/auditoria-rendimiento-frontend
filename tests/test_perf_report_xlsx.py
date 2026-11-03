import json
import subprocess
import sys
from pathlib import Path

import pytest
from openpyxl import load_workbook

from perf_report_xlsx import cargar, construir, emparejar_despues
from url_utils import slug_url

A = "https://e.com/producto/a"
B = "https://e.com/producto/b"
SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "perf_report_xlsx.py"


def lh_json(url, ff="mobile", perf=0.4, lcp=4200):
    return {"requestedUrl": url, "finalDisplayedUrl": url + "?redir=1", "fetchTime": "2026-11-03T10:00:00.000Z",
            "lighthouseVersion": "12.0.0", "configSettings": {"formFactor": ff},
            "categories": {"performance": {"score": perf, "auditRefs": [{"id": "largest-contentful-paint"}, {"id": "offscreen-images"}]}},
            "audits": {"largest-contentful-paint": {"score": 0.2, "numericValue": lcp, "scoreDisplayMode": "numeric", "title": "LCP"},
                       "offscreen-images": {"score": 0.3, "scoreDisplayMode": "metricSavings", "title": "Imágenes fuera de pantalla",
                                            "details": {"overallSavingsMs": 400, "items": [{"url": "x.jpg", "totalBytes": 2048}]}},
                       "final-screenshot": {"details": {"data": "x" * 1000}},
                       "network-requests": {"details": {"items": [{"url": url, "resourceType": "Document", "transferSize": 1024}]}}}}


def escribir(ruta, data):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(data))


@pytest.fixture
def carpeta(tmp_path):
    escribir(tmp_path / "urls.json", {"origen": "https://e.com", "fuente": "sitemap", "total": 2,
                                      "excluidas": [{"url": "https://e.com/x.pdf", "motivo": "no es HTML"}],
                                      "urls": [{"url": A, "plantilla": "/producto/*"}, {"url": B, "plantilla": "/producto/*"}]})
    for url in (A, B):
        d = tmp_path / "urls" / slug_url(url)
        escribir(d / "lh-mobile.json", lh_json(url))
        escribir(d / "aeo.json", {"metricas": {"url": url, "status": 200},
                                  "hallazgos": [{"url": url, "id": "aeo:tldr", "categoria": "AEO", "titulo": "Sin TL;DR", "severidad": "Alto"}]})
    escribir(tmp_path / "urls" / slug_url(B) / "lh-desktop.json", {"runtimeError": {"code": "NO_FCP", "message": "sin pintado"}})
    escribir(tmp_path / "sitio-aeo.json", {"hallazgos": [{"url": "https://e.com", "id": "aeo:llms", "titulo": "Sin llms.txt",
                                                          "severidad": "Bajo", "alcance": "sitio"}]})
    escribir(tmp_path / "crosscheck.json", {"hallazgos": [{"url": A, "id": "cross:title-duplicado", "titulo": "Title duplicado", "severidad": "Alto"}]})
    escribir(tmp_path / "cobertura.json", {"sitio": "ok", "urls": [{"url": A, "plantilla": "/producto/*", "pasos": {"aeo": "ok", "lh-mobile": "ok"}},
                                                                   {"url": B, "plantilla": "/producto/*", "pasos": {"aeo": "ok", "lh-desktop": "error: sin pintado"}}]})
    return tmp_path


class TestCargar:
    def test_quita_capturas_y_usa_url_indicada(self, tmp_path):
        escribir(tmp_path / "lh.json", lh_json(A))
        inf = cargar(tmp_path / "lh.json", url=A)
        assert inf["url"] == A and "final-screenshot" not in inf["lh"]["audits"] and inf["ff"] == "Móvil"

    def test_informe_con_error_lanza_value_error(self, tmp_path):
        escribir(tmp_path / "psi.json", {"error": {"code": 429, "message": "Quota exceeded"}})
        with pytest.raises(ValueError, match="Quota"):
            cargar(tmp_path / "psi.json")


class TestEmparejar:
    def test_por_url_y_dispositivo_con_respaldo_por_dispositivo(self):
        d = [{"url": A, "ff": "Móvil"}, {"url": B, "ff": "Móvil"}, {"url": A, "ff": "Escritorio"}]
        assert emparejar_despues({"url": B + "/", "ff": "Móvil"}, d) is d[1]
        assert emparejar_despues({"url": "https://e.com/otra", "ff": "Escritorio"}, d) is d[2]
        assert emparejar_despues({"url": "https://e.com/otra", "ff": "Móvil"}, d) is None


class TestDirectorio:
    def test_genera_hojas_de_sitio_completo(self, carpeta):
        out = carpeta / "reporte.xlsx"
        r = subprocess.run([sys.executable, str(SCRIPT), "--out", str(out), "--dir", str(carpeta)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "se omite" in r.stderr and "sin pintado" in r.stderr
        wb = load_workbook(out)
        assert {"Por URL", "Por plantilla", "Patrones", "Checklist por URL", "Cobertura"} <= set(wb.sheetnames)
        por_url = [row for row in wb["Por URL"].iter_rows(min_row=2, values_only=True)]
        assert {row[0] for row in por_url} == {A, B}
        assert next(row for row in por_url if row[0] == B)[-1] == "lh-desktop"
        hallazgos = [row for row in wb["Hallazgos"].iter_rows(min_row=2, values_only=True)]
        assert any(str(row[1]).startswith("(sitio) ") for row in hallazgos)
        assert all("redir=1" not in str(row[1]) for row in hallazgos)
        patrones = {row[0]: row for row in wb["Patrones"].iter_rows(min_row=2, values_only=True)}
        assert patrones["aeo:tldr"][4] == 2 and "aeo:llms" not in patrones
        checklist = {row[1]: row for row in wb["Checklist"].iter_rows(min_row=2, values_only=True)}
        fila_title = next(v for k, v in checklist.items() if k.startswith("Title 15–60"))
        assert fila_title[3] == "No cumple" and fila_title[5] == "1"
        cobertura = [row[0] for row in wb["Cobertura"].iter_rows(values_only=True)]
        assert "https://e.com/x.pdf" in cobertura

    def test_sin_datos_termina_con_error(self, tmp_path):
        r = subprocess.run([sys.executable, str(SCRIPT), "--out", str(tmp_path / "r.xlsx"),
                            "--dir", str(tmp_path)], capture_output=True, text=True)
        assert r.returncode != 0 and "No hay informes" in r.stderr


class TestUnaUrl:
    def test_reporte_de_una_url_no_agrega_hojas_de_sitio(self, tmp_path):
        escribir(tmp_path / "lh.json", lh_json(A))
        construir([cargar(tmp_path / "lh.json")], [], tmp_path / "r.xlsx", "Sitio")
        assert "Por URL" not in load_workbook(tmp_path / "r.xlsx").sheetnames

    def test_antes_vs_despues_incluye_url(self, tmp_path):
        escribir(tmp_path / "lh.json", lh_json(A, lcp=2000))
        escribir(tmp_path / "base.json", lh_json(A, lcp=4000))
        construir([cargar(tmp_path / "lh.json")], [], tmp_path / "r.xlsx", "Sitio", antes=[cargar(tmp_path / "base.json")])
        filas = list(load_workbook(tmp_path / "r.xlsx")["Antes vs Después"].iter_rows(min_row=2, values_only=True))
        lcp = next(f for f in filas if f[2].startswith("LCP"))
        assert lcp[0].startswith(A) and lcp[3] == 4000 and lcp[4] == 2000 and lcp[6] == 50.0


class TestConstruirEnProceso:
    def test_contexto_de_directorio_genera_todas_las_hojas(self, carpeta):
        from perf_report_xlsx import cargar_informes, cargar_manuales
        from reporte_sitio import cargar_directorio
        d = cargar_directorio(carpeta)
        informes, manuales = cargar_informes(d["informes"]), cargar_manuales(d["manuales"])
        construir(informes, manuales, carpeta / "r.xlsx", "Sitio", contexto={k: d[k] for k in ("urls", "cobertura", "crosscheck")})
        wb = load_workbook(carpeta / "r.xlsx")
        matriz = list(wb["Checklist por URL"].iter_rows(values_only=True))
        assert matriz[0][0] == "URL" and {r[0] for r in matriz[1:]} == {A, B}
        assert "No cumple" in matriz[1] and "Cumple" in matriz[1]
        plantillas = list(wb["Por plantilla"].iter_rows(min_row=2, values_only=True))
        assert plantillas[0][:2] == ("/producto/*", 2)

    def test_manual_json_invalido_se_omite_con_aviso(self, tmp_path, capsys):
        from perf_report_xlsx import cargar_manuales
        (tmp_path / "m.json").write_text("{roto")
        assert cargar_manuales([(tmp_path / "m.json", None)]) == []
        assert "se omite" in capsys.readouterr().err
