from types import SimpleNamespace

from aeo_site_checks import analizar_pagina, analizar_sitio, ejecutar

OPC = SimpleNamespace(min_words=500, title_max=60, desc_max=160, internal_links_min=2)

HTML_OK = """<!doctype html><html lang="es"><head>
<title>Zapatillas de running para principiantes</title>
<meta name="description" content="Cómo elegir zapatillas de running si estás empezando: amortiguación, drop y talla, explicado sin rodeos.">
<link rel="canonical" href="https://e.com/guia">
<meta property="og:title" content="Guía">
</head><body>
<h1>Guía de zapatillas</h1>
<p>Respuesta corta: elige amortiguación media y drop de 8-10 mm si estás empezando a correr.</p>
<h2>Amortiguación</h2><p>Texto.</p><h2>Drop</h2><p>Texto.</p>
<a href="/producto/a">A</a><a href="https://e.com/producto/b#x">B</a><a href="https://otro.com/">O</a>
</body></html>"""


def titulos(hallazgos):
    return {h["titulo"] for h in hallazgos}


class TestAnalizarPagina:
    def test_metricas_incluyen_datos_para_el_cruce_entre_urls(self):
        _, m = analizar_pagina("https://e.com/guia", 200, HTML_OK, {}, "https://e.com/guia", OPC)
        assert m["title"] == "Zapatillas de running para principiantes"
        assert m["description"].startswith("Cómo elegir")
        assert m["h1_textos"] == ["Guía de zapatillas"]
        assert m["canonical_abs"] == "https://e.com/guia"
        assert m["enlaces_internos_lista"] == ["https://e.com/producto/a", "https://e.com/producto/b"]
        assert m["noindex"] is False
        assert m["url_final"] == "https://e.com/guia"

    def test_no_incluye_checks_de_sitio(self):
        h, _ = analizar_pagina("https://e.com/guia", 200, HTML_OK, {}, "https://e.com/guia", OPC)
        ids = {x["id"] for x in h}
        assert not ids & {"aeo:robots", "aeo:llms", "aeo:sitemap"}

    def test_detecta_falta_de_title_y_noindex_en_cabecera(self):
        html = "<html><head></head><body><h1>x</h1></body></html>"
        h, m = analizar_pagina("https://e.com/x", 200, html, {"X-Robots-Tag": "noindex"}, "https://e.com/x", OPC)
        assert {"Falta <title>", "Cabecera X-Robots-Tag: noindex"} <= titulos(h)
        assert m["noindex"] is True

    def test_hallazgos_llevan_url_y_formato_manual(self):
        h, _ = analizar_pagina("https://e.com/x", 200, "<html><body></body></html>", {}, "https://e.com/x", OPC)
        claves = {"url", "id", "categoria", "titulo", "severidad", "descripcion", "recomendacion", "evidencia", "esfuerzo", "form_factor"}
        assert h and all(claves <= set(x) and x["url"] == "https://e.com/x" for x in h)


def fake_get(rutas):
    def get(url, timeout=20):
        if url in rutas:
            return 200, rutas[url], {}, url
        return 404, "", {}, url
    return get


class TestAnalizarSitio:
    def test_sin_robots_llms_ni_sitemap(self):
        h, m = analizar_sitio("https://e.com", fake_get({}))
        assert {"Sin robots.txt accesible", "Sin llms.txt", "Sin sitemap.xml accesible"} <= titulos(h)
        assert all(x["alcance"] == "sitio" and x["url"] == "https://e.com" for x in h)
        assert m == {"robots_txt": False, "llms_txt": False, "sitemap": False}

    def test_usa_sitemap_declarado_en_robots(self):
        get = fake_get({"https://e.com/robots.txt": "User-agent: *\nSitemap: https://e.com/sm.xml",
                        "https://e.com/sm.xml": "<urlset/>", "https://e.com/llms.txt": "# e"})
        h, m = analizar_sitio("https://e.com", get)
        assert h == []
        assert m == {"robots_txt": True, "llms_txt": True, "sitemap": True}

    def test_detecta_bots_de_ia_bloqueados(self):
        get = fake_get({"https://e.com/robots.txt": "User-agent: GPTBot\nDisallow: /\nSitemap: https://e.com/sitemap.xml",
                        "https://e.com/sitemap.xml": "<urlset/>", "https://e.com/llms.txt": "x"})
        h, _ = analizar_sitio("https://e.com", get)
        assert "robots.txt bloquea bots de IA" in titulos(h)


class TestEjecutar:
    def test_solo_sitio_no_pide_la_pagina(self):
        llamadas = []
        def get(url, timeout=20):
            llamadas.append(url)
            return 404, "", {}, url
        r = ejecutar("https://e.com/x", OPC, get, pagina=False, sitio=True)
        assert "https://e.com/x" not in llamadas
        assert r["hallazgos"] and r["metricas"]["sitio"]["robots_txt"] is False

    def test_sin_checks_sitio_no_pide_robots(self):
        llamadas = []
        def get(url, timeout=20):
            llamadas.append(url)
            return 200, HTML_OK, {}, url
        ejecutar("https://e.com/guia", OPC, get, pagina=True, sitio=False)
        assert llamadas == ["https://e.com/guia"]

    def test_error_http_queda_registrado_sin_hallazgos_de_contenido(self):
        r = ejecutar("https://e.com/roto", OPC, fake_get({}), pagina=True, sitio=False)
        assert r["error"].startswith("No se pudo obtener la página")
        assert r["metricas"] == {"url": "https://e.com/roto", "status": 404, "url_final": "https://e.com/roto"}
        assert r["hallazgos"] == []


def html_con_jsonld(ld):
    import json as _json
    return f'<html lang="es"><head><title>Título suficientemente largo</title><script type="application/ld+json">{_json.dumps(ld)}</script></head><body><h1>x</h1></body></html>'


class TestJsonLd:
    def test_article_sin_date_modified_ni_author(self):
        h, m = analizar_pagina("https://e.com/x", 200, html_con_jsonld({"@type": "Article", "headline": "x"}), {}, "https://e.com/x", OPC)
        assert {"Article sin dateModified", "Article sin author", "Sin entidad Organization/WebSite en JSON-LD"} <= titulos(h)
        assert m["jsonld_tipos"] == ["Article"]

    def test_contenido_viejo_y_fecha_no_iso(self):
        viejo = analizar_pagina("https://e.com/x", 200, html_con_jsonld({"@type": "BlogPosting", "dateModified": "2020-01-01", "author": "A"}), {}, "https://e.com/x", OPC)[0]
        assert "Contenido sin actualizar hace más de 12 meses" in titulos(viejo)
        raro = analizar_pagina("https://e.com/x", 200, html_con_jsonld({"@type": "Article", "dateModified": "ayer", "author": "A"}), {}, "https://e.com/x", OPC)[0]
        assert "dateModified con formato no ISO" in titulos(raro)

    def test_jsonld_invalido(self):
        html = '<html><head><script type="application/ld+json">{no json</script></head><body></body></html>'
        assert "JSON-LD inválido" in titulos(analizar_pagina("https://e.com/x", 200, html, {}, "https://e.com/x", OPC)[0])


class TestGetRobusto:
    def test_get_rechaza_file_y_captura_charset_desconocido(self, monkeypatch):
        import aeo_site_checks
        assert aeo_site_checks.get("file:///etc/passwd")[0] is None
        class R:
            status, headers = 200, None
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, *a): return b"hola"
            def geturl(self): return "https://e.com/"
        class H(dict):
            def get_content_charset(self): return "charset-inexistente"
        r = R(); r.headers = H()
        monkeypatch.setattr(aeo_site_checks, "urlopen", lambda *a, **k: r)
        assert aeo_site_checks.get("https://e.com/")[0] is None
