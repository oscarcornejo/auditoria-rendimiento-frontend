import json

from site_crosscheck import cargar_paginas, cruzar, main_args
from url_utils import slug_url


def pagina(url, **kw):
    base = {"url": url, "status": 200, "url_final": url, "title": f"Título {url}", "description": f"Desc {url}",
            "h1_textos": [f"H1 {url}"], "canonical_abs": url, "enlaces_internos_lista": [], "noindex": False}
    return {**base, **kw}


def ids_por_url(hallazgos):
    out = {}
    for h in hallazgos:
        out.setdefault(h["url"], set()).add(h["id"])
    return out


H = "https://e.com/"
A = "https://e.com/a"
B = "https://e.com/b"


class TestDuplicados:
    def test_title_duplicado_marca_cada_url_afectada(self):
        r = cruzar([pagina(H, enlaces_internos_lista=[A, B]), pagina(A, title="Igual"), pagina(B, title="Igual")])
        ids = ids_por_url(r["hallazgos"])
        assert "cross:title-duplicado" in ids[A] and "cross:title-duplicado" in ids[B]
        assert "cross:title-duplicado" not in ids.get(H, set())
        ev = next(h for h in r["hallazgos"] if h["url"] == A and h["id"] == "cross:title-duplicado")["evidencia"]
        assert B in ev

    def test_description_y_h1_duplicados(self):
        r = cruzar([pagina(H, enlaces_internos_lista=[A, B]), pagina(A, description="D", h1_textos=["X"]),
                    pagina(B, description="d ", h1_textos=["x"])])
        ids = ids_por_url(r["hallazgos"])
        assert {"cross:description-duplicada", "cross:h1-duplicado"} <= ids[A]

    def test_vacios_no_cuentan_como_duplicados(self):
        r = cruzar([pagina(H, enlaces_internos_lista=[A, B]), pagina(A, title="", description=""), pagina(B, title="", description="")])
        assert not any(h["id"] in ("cross:title-duplicado", "cross:description-duplicada") for h in r["hallazgos"])


class TestEstadoEnSitemap:
    def test_url_con_error_http(self):
        r = cruzar([pagina(H, enlaces_internos_lista=[A]), {"url": A, "status": 404, "url_final": A}])
        assert "cross:sitemap-error" in ids_por_url(r["hallazgos"])[A]

    def test_url_que_redirige(self):
        r = cruzar([pagina(H, enlaces_internos_lista=[A]), pagina(A, url_final="https://e.com/nueva")])
        assert "cross:sitemap-redireccion" in ids_por_url(r["hallazgos"])[A]

    def test_barra_final_no_es_redireccion(self):
        r = cruzar([pagina(H, enlaces_internos_lista=[A]), pagina(A, url_final=A + "/")])
        assert "cross:sitemap-redireccion" not in ids_por_url(r["hallazgos"]).get(A, set())

    def test_url_con_noindex(self):
        r = cruzar([pagina(H, enlaces_internos_lista=[A]), pagina(A, noindex=True)])
        assert "cross:sitemap-noindex" in ids_por_url(r["hallazgos"])[A]

    def test_canonical_a_url_desconocida(self):
        r = cruzar([pagina(H, enlaces_internos_lista=[A]), pagina(A, canonical_abs="https://e.com/otra")])
        assert "cross:canonical-externo" in ids_por_url(r["hallazgos"])[A]

    def test_canonical_a_url_con_error(self):
        r = cruzar([pagina(H, enlaces_internos_lista=[A, B]), pagina(A, canonical_abs=B), {"url": B, "status": 500, "url_final": B}])
        assert "cross:canonical-roto" in ids_por_url(r["hallazgos"])[A]


class TestEnlaces:
    def test_enlace_interno_a_url_con_error(self):
        r = cruzar([pagina(H, enlaces_internos_lista=[A]), {"url": A, "status": 404, "url_final": A}])
        h = next(x for x in r["hallazgos"] if x["id"] == "cross:enlace-roto")
        assert h["url"] == H and A in h["evidencia"]

    def test_verifica_enlaces_desconocidos_con_tope(self):
        consultadas = []
        def estado(url):
            consultadas.append(url)
            return 404
        desconocidos = [f"https://e.com/x{i}" for i in range(5)]
        r = cruzar([pagina(H, enlaces_internos_lista=desconocidos)], estado=estado, max_verificar=2)
        assert len(consultadas) == 2
        assert sum(1 for h in r["hallazgos"] if h["id"] == "cross:enlace-roto") == 1
        assert r["metricas"]["enlaces_sin_verificar"] == 3

    def test_pagina_huerfana(self):
        r = cruzar([pagina(H, enlaces_internos_lista=[A]), pagina(A, enlaces_internos_lista=[H]), pagina(B)])
        ids = ids_por_url(r["hallazgos"])
        assert "cross:huerfana" in ids[B]
        assert "cross:huerfana" not in ids.get(H, set()) and "cross:huerfana" not in ids.get(A, set())

    def test_autoenlace_no_salva_de_huerfana(self):
        r = cruzar([pagina(H, enlaces_internos_lista=[A]), pagina(A), pagina(B, enlaces_internos_lista=[B])])
        assert "cross:huerfana" in ids_por_url(r["hallazgos"])[B]


class TestFormato:
    def test_hallazgos_con_formato_manual(self):
        r = cruzar([pagina(H), pagina(A, title="Igual"), pagina(B, title="Igual")])
        claves = {"url", "id", "categoria", "titulo", "severidad", "descripcion", "recomendacion", "evidencia", "esfuerzo", "form_factor"}
        assert r["hallazgos"] and all(claves <= set(h) for h in r["hallazgos"])
        assert r["metricas"]["paginas"] == 3


class TestCargarPaginas:
    def test_lee_aeo_json_de_cada_url_y_omite_faltantes(self, tmp_path):
        (tmp_path / "urls.json").write_text(json.dumps({"urls": [{"url": H}, {"url": A}]}))
        carpeta = tmp_path / "urls" / slug_url(H)
        carpeta.mkdir(parents=True)
        (carpeta / "aeo.json").write_text(json.dumps({"metricas": pagina(H), "hallazgos": []}))
        paginas = cargar_paginas(tmp_path)
        assert [p["url"] for p in paginas] == [H]

    def test_main_escribe_crosscheck(self, tmp_path):
        (tmp_path / "urls.json").write_text(json.dumps({"urls": [{"url": H}]}))
        carpeta = tmp_path / "urls" / slug_url(H)
        carpeta.mkdir(parents=True)
        (carpeta / "aeo.json").write_text(json.dumps({"metricas": pagina(H), "hallazgos": []}))
        main_args([str(tmp_path)])
        data = json.loads((tmp_path / "crosscheck.json").read_text())
        assert data["metricas"]["paginas"] == 1 and data["hallazgos"] == []
