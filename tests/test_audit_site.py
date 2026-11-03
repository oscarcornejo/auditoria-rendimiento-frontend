import json
from types import SimpleNamespace

import pytest

from audit_site import auditar, pasos_de_url, seleccionar_lighthouse
from url_utils import slug_url

H = "https://e.com/"
P1 = "https://e.com/producto/a"
P2 = "https://e.com/producto/b"
P3 = "https://e.com/producto/c"
URLS = [{"url": H, "plantilla": "home"}] + [{"url": u, "plantilla": "/producto/*"} for u in (P1, P2, P3)]


def opciones(**kw):
    base = dict(motor="lighthouse", lighthouse_por_plantilla=0, solo_movil=False, browser=False,
                concurrency=2, verificar_enlaces=0, crosscheck=False)
    return SimpleNamespace(**{**base, **kw})


def escribir_urls(tmp_path, urls=URLS):
    ruta = tmp_path / "urls.json"
    ruta.write_text(json.dumps({"origen": "https://e.com", "urls": urls}))
    return ruta


class FakeRunner:
    """Escribe la salida esperada de cada paso; permite forzar fallos por (paso, url)."""

    def __init__(self, fallos=(), contenido=None):
        self.fallos, self.llamadas, self.contenido = set(fallos), [], contenido or {}

    def __call__(self, paso):
        self.llamadas.append((paso.nombre, paso.url))
        if (paso.nombre, paso.url) in self.fallos:
            return 1, "boom"
        paso.salida.parent.mkdir(parents=True, exist_ok=True)
        cuerpo = self.contenido.get((paso.nombre, paso.url), {"metricas": {"url": paso.url, "status": 200}, "hallazgos": []})
        paso.salida.write_text(json.dumps(cuerpo))
        return 0, ""


class TestSeleccionarLighthouse:
    def test_cero_significa_todas(self):
        assert seleccionar_lighthouse(URLS, 0) == {H, P1, P2, P3}

    def test_n_por_plantilla(self):
        assert seleccionar_lighthouse(URLS, 2) == {H, P1, P2}


class TestPasosDeUrl:
    def test_lighthouse_movil_y_escritorio_en_carpeta_por_slug(self, tmp_path):
        pasos = pasos_de_url(P1, tmp_path, opciones(), con_lighthouse=True)
        nombres = [p.nombre for p in pasos]
        assert nombres == ["aeo", "lh-mobile", "lh-desktop"]
        assert all(p.salida.parent == tmp_path / "urls" / slug_url(P1) for p in pasos)
        assert "--preset=desktop" in pasos[2].cmd and "--sin-checks-sitio" in pasos[0].cmd

    def test_psi_solo_movil_y_browser(self, tmp_path):
        pasos = pasos_de_url(P1, tmp_path, opciones(motor="psi", solo_movil=True, browser=True), con_lighthouse=True)
        assert [p.nombre for p in pasos] == ["aeo", "psi-mobile", "browser"]
        assert any("strategy=mobile" in c for c in pasos[1].cmd)

    def test_motor_ninguno(self, tmp_path):
        assert [p.nombre for p in pasos_de_url(P1, tmp_path, opciones(motor="ninguno"), True)] == ["aeo"]


class TestAuditar:
    def test_audita_todas_las_urls_y_escribe_cobertura(self, tmp_path):
        runner = FakeRunner()
        cob = auditar(escribir_urls(tmp_path), tmp_path, opciones(), runner)
        assert cob["total"] == 4
        assert all(u["pasos"] == {"aeo": "ok", "lh-mobile": "ok", "lh-desktop": "ok"} for u in cob["urls"])
        assert ("sitio", "https://e.com") in runner.llamadas
        assert json.loads((tmp_path / "cobertura.json").read_text())["total"] == 4
        assert json.loads((tmp_path / "errores.json").read_text()) == []

    def test_lighthouse_por_plantilla_marca_no_aplica(self, tmp_path):
        cob = auditar(escribir_urls(tmp_path), tmp_path, opciones(lighthouse_por_plantilla=1), FakeRunner())
        por_url = {u["url"]: u["pasos"] for u in cob["urls"]}
        assert por_url[P1]["lh-mobile"] == "ok"
        assert por_url[P2]["lh-mobile"].startswith("no aplica")
        assert por_url[P2]["aeo"] == "ok"

    def test_lighthouse_es_serial(self, tmp_path):
        runner = FakeRunner()
        auditar(escribir_urls(tmp_path), tmp_path, opciones(concurrency=4), runner)
        lh = [i for i, (n, _) in enumerate(runner.llamadas) if n.startswith("lh-")]
        assert lh == list(range(lh[0], lh[0] + len(lh)))

    def test_registra_errores_sin_detener_el_resto(self, tmp_path):
        cob = auditar(escribir_urls(tmp_path), tmp_path, opciones(), FakeRunner(fallos={("lh-mobile", P1)}))
        por_url = {u["url"]: u["pasos"] for u in cob["urls"]}
        assert por_url[P1]["lh-mobile"].startswith("error")
        assert por_url[P2]["lh-mobile"] == "ok"
        errores = json.loads((tmp_path / "errores.json").read_text())
        assert errores == [{"url": P1, "paso": "lh-mobile", "error": por_url[P1]["lh-mobile"]}]

    def test_salida_con_error_interno_cuenta_como_error(self, tmp_path):
        runner = FakeRunner(contenido={("aeo", P1): {"error": "No se pudo obtener la página (status=404)", "metricas": {}, "hallazgos": []},
                                       ("lh-mobile", P2): {"runtimeError": {"code": "NO_FCP", "message": "sin pintado"}}})
        cob = auditar(escribir_urls(tmp_path), tmp_path, opciones(), runner)
        por_url = {u["url"]: u["pasos"] for u in cob["urls"]}
        assert "404" in por_url[P1]["aeo"] and por_url[P1]["aeo"].startswith("error")
        assert "sin pintado" in por_url[P2]["lh-mobile"]

    def test_reanuda_sin_repetir_salidas_validas(self, tmp_path):
        ruta = escribir_urls(tmp_path)
        auditar(ruta, tmp_path, opciones(), FakeRunner(fallos={("aeo", P3)}))
        segundo = FakeRunner()
        cob = auditar(ruta, tmp_path, opciones(), segundo)
        assert [l for l in segundo.llamadas if l[0] != "sitio"] == [("aeo", P3)]
        assert {u["url"]: u["pasos"]["aeo"] for u in cob["urls"]}[H] == "reutilizado"

    def test_runner_que_lanza_no_rompe_la_auditoria(self, tmp_path):
        def runner(paso):
            raise OSError("sin lighthouse")
        cob = auditar(escribir_urls(tmp_path, URLS[:1]), tmp_path, opciones(), runner)
        assert cob["urls"][0]["pasos"]["aeo"].startswith("error")

    def test_crosscheck_genera_archivo(self, tmp_path):
        auditar(escribir_urls(tmp_path), tmp_path, opciones(crosscheck=True, motor="ninguno"), FakeRunner())
        assert (tmp_path / "crosscheck.json").is_file()

    def test_urls_json_invalido(self, tmp_path):
        ruta = tmp_path / "urls.json"
        ruta.write_text("{}")
        with pytest.raises(ValueError, match="urls"):
            auditar(ruta, tmp_path, opciones(), FakeRunner())
