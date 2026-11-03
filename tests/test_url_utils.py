import pytest

from url_utils import clave_url, es_html_probable, mismo_sitio, normalizar, plantilla, slug_url


class TestNormalizar:
    def test_quita_fragmento_y_parametros_de_tracking(self):
        assert normalizar("https://Ejemplo.com/a?utm_source=x&id=3&gclid=9#top") == "https://ejemplo.com/a?id=3"

    def test_raiz_sin_path_queda_con_barra(self):
        assert normalizar("https://ejemplo.com") == "https://ejemplo.com/"

    def test_resuelve_relativas_contra_base(self):
        assert normalizar("../b", base="https://ejemplo.com/x/y/") == "https://ejemplo.com/x/b"

    def test_descarta_esquemas_no_http(self):
        for href in ("mailto:a@b.c", "tel:123", "javascript:void(0)", "#seccion", ""):
            assert normalizar(href, base="https://ejemplo.com/") is None

    def test_quita_puerto_por_defecto(self):
        assert normalizar("https://ejemplo.com:443/a") == "https://ejemplo.com/a"


class TestClaveUrl:
    def test_ignora_barra_final_y_mayusculas_del_host(self):
        assert clave_url("https://EJEMPLO.com/blog/") == clave_url("https://ejemplo.com/blog")

    def test_raiz_es_estable(self):
        assert clave_url("https://ejemplo.com") == clave_url("https://ejemplo.com/")

    def test_none_devuelve_cadena_vacia(self):
        assert clave_url(None) == ""


class TestMismoSitio:
    def test_www_y_sin_www_son_el_mismo_sitio(self):
        assert mismo_sitio("https://www.ejemplo.com/a", "https://ejemplo.com")

    def test_otro_dominio_no_es_el_mismo_sitio(self):
        assert not mismo_sitio("https://cdn.otro.com/a", "https://ejemplo.com")


class TestEsHtmlProbable:
    @pytest.mark.parametrize("url", ["https://e.com/a.pdf", "https://e.com/img/x.JPG", "https://e.com/f.zip"])
    def test_descarta_archivos(self, url):
        assert not es_html_probable(url)

    @pytest.mark.parametrize("url", ["https://e.com/", "https://e.com/producto/x", "https://e.com/p.html"])
    def test_acepta_paginas(self, url):
        assert es_html_probable(url)


class TestPlantilla:
    @pytest.mark.parametrize("url,esperada", [
        ("https://e.com/", "home"),
        ("https://e.com/contacto", "/contacto"),
        ("https://e.com/producto/zapato-rojo", "/producto/*"),
        ("https://e.com/blog/2024/05/post", "/blog/*"),
        ("https://e.com/es/producto/zapato", "/es/producto/*"),
        ("https://e.com/en-us/about", "/en-us/about"),
    ])
    def test_agrupa_por_primer_segmento(self, url, esperada):
        assert plantilla(url) == esperada


class TestSlugUrl:
    def test_es_seguro_para_nombres_de_carpeta(self):
        s = slug_url("https://e.com/producto/zapato rojo?x=1")
        assert "/" not in s and " " not in s and "?" not in s

    def test_urls_distintas_no_colisionan(self):
        assert slug_url("https://e.com/a?x=1") != slug_url("https://e.com/a?x=2")

    def test_home_tiene_slug_legible(self):
        assert slug_url("https://e.com/").startswith("home-")


class TestEntradasHostiles:
    @pytest.mark.parametrize("href", ["http://x.com:99999/", "http://x.com:abc/", "http://[bad/"])
    def test_url_malformada_devuelve_none_sin_lanzar(self, href):
        assert normalizar(href) is None and clave_url(href) == ""

    def test_clave_une_www_y_esquema_como_mismo_sitio(self):
        assert clave_url("http://www.e.com/a/") == clave_url("https://e.com/a")
        assert clave_url("https://e.com/a") != clave_url("https://e.com/b")
