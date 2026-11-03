import gzip
import sys

import pytest

from discover_urls import descubrir, extraer_enlaces, parse_sitemap, sitemaps_de_robots

ORIGEN = "https://e.com"

URLSET = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://e.com/</loc><lastmod>2026-01-01</lastmod></url>
  <url><loc>https://e.com/producto/a</loc></url>
  <url><loc> https://e.com/producto/b?utm_source=x </loc></url>
</urlset>"""

INDICE = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://e.com/sitemap-productos.xml.gz</loc></sitemap>
  <sitemap><loc>https://e.com/sitemap-blog.xml</loc></sitemap>
</sitemapindex>"""

BLOG = b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://e.com/blog/post-1</loc></url>
  <url><loc>https://e.com/guia.pdf</loc></url>
  <url><loc>https://otro.com/externo</loc></url>
</urlset>"""


def fake_fetch(rutas):
    """fetch(url) → (status, bytes, url_final) a partir de un dict url → bytes; 404 si no existe."""
    def fetch(url):
        if url in rutas:
            return 200, rutas[url], url
        return 404, b"", url
    return fetch


class TestParseSitemap:
    def test_urlset_devuelve_locs_y_lastmod(self):
        urls, hijos = parse_sitemap(URLSET)
        assert urls[0] == ("https://e.com/", "2026-01-01")
        assert ("https://e.com/producto/a", "") in urls
        assert hijos == []

    def test_indice_devuelve_sitemaps_hijos(self):
        urls, hijos = parse_sitemap(INDICE)
        assert urls == []
        assert hijos == ["https://e.com/sitemap-productos.xml.gz", "https://e.com/sitemap-blog.xml"]

    def test_descomprime_gzip(self):
        urls, _ = parse_sitemap(gzip.compress(URLSET))
        assert len(urls) == 3

    def test_xml_invalido_no_revienta(self):
        assert parse_sitemap(b"<html>no es xml") == ([], [])


class TestSitemapsDeRobots:
    def test_lee_lineas_sitemap_sin_importar_mayusculas(self):
        robots = "User-agent: *\nDisallow: /admin\nsitemap: https://e.com/s1.xml\nSitemap: https://e.com/s2.xml\n"
        assert sitemaps_de_robots(robots) == ["https://e.com/s1.xml", "https://e.com/s2.xml"]


class TestExtraerEnlaces:
    def test_resuelve_y_normaliza_hrefs(self):
        html = '<a href="/a#x">A</a><a href="b?utm_source=1">B</a><a href="mailto:x@y.z">M</a>'
        assert extraer_enlaces(html, "https://e.com/dir/") == ["https://e.com/a", "https://e.com/dir/b"]


class TestDescubrir:
    def test_sigue_indice_gzip_y_filtra_otros_sitios_y_archivos(self):
        fetch = fake_fetch({
            "https://e.com/robots.txt": b"Sitemap: https://e.com/sitemap_index.xml",
            "https://e.com/sitemap_index.xml": INDICE,
            "https://e.com/sitemap-productos.xml.gz": gzip.compress(URLSET),
            "https://e.com/sitemap-blog.xml": BLOG,
        })
        r = descubrir(ORIGEN, fetch)
        urls = [u["url"] for u in r["urls"]]
        assert r["fuente"] == "sitemap"
        assert urls == ["https://e.com/", "https://e.com/producto/a", "https://e.com/producto/b", "https://e.com/blog/post-1"]
        motivos = {e["url"]: e["motivo"] for e in r["excluidas"]}
        assert motivos["https://e.com/guia.pdf"] == "no es HTML"
        assert motivos["https://otro.com/externo"] == "otro sitio"

    def test_asigna_plantilla_y_lastmod(self):
        fetch = fake_fetch({"https://e.com/sitemap.xml": URLSET})
        r = descubrir(ORIGEN, fetch)
        home = r["urls"][0]
        assert home["plantilla"] == "home" and home["lastmod"] == "2026-01-01" and home["fuente"] == "sitemap"
        assert r["urls"][1]["plantilla"] == "/producto/*"

    def test_elimina_duplicados(self):
        dup = URLSET.replace(b"</urlset>", b"<url><loc>https://e.com/producto/a</loc></url></urlset>")
        r = descubrir(ORIGEN, fake_fetch({"https://e.com/sitemap.xml": dup}))
        assert [u["url"] for u in r["urls"]].count("https://e.com/producto/a") == 1

    def test_include_y_exclude(self):
        fetch = fake_fetch({"https://e.com/sitemap.xml": URLSET})
        r = descubrir(ORIGEN, fetch, include=r"/producto/", exclude=r"/b$")
        assert [u["url"] for u in r["urls"]] == ["https://e.com/producto/a"]

    def test_max_corta_y_reporta_omitidas(self):
        r = descubrir(ORIGEN, fake_fetch({"https://e.com/sitemap.xml": URLSET}), max_urls=2)
        assert len(r["urls"]) == 2
        assert r["omitidas_por_max"] == 1

    def test_no_entra_en_bucle_con_indices_ciclicos(self):
        ciclo = b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://e.com/sitemap.xml</loc></sitemap></sitemapindex>'
        r = descubrir(ORIGEN, fake_fetch({"https://e.com/sitemap.xml": ciclo}))
        assert r["urls"] == [] or r["fuente"] == "crawl"

    def test_sin_sitemap_rastrea_enlaces_internos_respetando_robots(self):
        fetch = fake_fetch({
            "https://e.com/robots.txt": b"User-agent: *\nDisallow: /privado",
            "https://e.com/": b'<a href="/a">a</a><a href="/privado/x">p</a><a href="https://otro.com/">o</a>',
            "https://e.com/a": b'<a href="/a/b">b</a><a href="/">home</a>',
            "https://e.com/a/b": b'<a href="/a/b/c">c</a>',
        })
        r = descubrir(ORIGEN, fetch, crawl_depth=2)
        urls = [u["url"] for u in r["urls"]]
        assert r["fuente"] == "crawl"
        assert urls == ["https://e.com/", "https://e.com/a", "https://e.com/a/b"]
        assert all(u["fuente"] == "crawl" for u in r["urls"])
        assert any(e["motivo"] == "bloqueada por robots.txt" for e in r["excluidas"])

    @pytest.mark.parametrize("status", [404, 500])
    def test_rastreo_omite_paginas_con_error(self, status):
        def fetch(url):
            if url == "https://e.com/":
                return 200, b'<a href="/roto">x</a>', url
            return status, b"", url
        r = descubrir(ORIGEN, fetch, crawl_depth=1)
        assert [u["url"] for u in r["urls"]] == ["https://e.com/"]
        assert {"url": "https://e.com/roto", "motivo": f"HTTP {status}"} in r["excluidas"]


class TestDeduplicacion:
    def test_barra_final_no_duplica(self):
        sm = b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://e.com/a</loc></url><url><loc>https://e.com/a/</loc></url></urlset>'
        r = descubrir(ORIGEN, fake_fetch({"https://e.com/sitemap.xml": sm}))
        assert [u["url"] for u in r["urls"]] == ["https://e.com/a"]

    def test_rastreo_registra_url_final_y_resuelve_enlaces_desde_ella(self):
        def fetch(url):
            paginas = {"https://e.com/": (b'<a href="/uv">uv</a>', url),
                       "https://e.com/uv": (b'<a href="guia">g</a>', "https://e.com/uv/"),
                       "https://e.com/uv/": (b'<a href="guia">g</a>', url),
                       "https://e.com/uv/guia": (b"", url)}
            if url in paginas:
                body, final = paginas[url]
                return 200, body, final
            return 404, b"", url
        r = descubrir(ORIGEN, fetch, crawl_depth=3)
        assert [u["url"] for u in r["urls"]] == ["https://e.com/", "https://e.com/uv/", "https://e.com/uv/guia"]


class TestSeguridad:
    def test_sitemaps_hijos_de_otro_host_o_esquema_no_se_piden(self):
        indice = (b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                  b'<sitemap><loc>file:///etc/passwd</loc></sitemap>'
                  b'<sitemap><loc>http://169.254.169.254/latest</loc></sitemap>'
                  b'<sitemap><loc>https://e.com/s2.xml</loc></sitemap></sitemapindex>')
        hijo = b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://e.com/a</loc></url></urlset>'
        pedidas = []
        base = fake_fetch({"https://e.com/sitemap.xml": indice, "https://e.com/s2.xml": hijo})
        def fetch(url):
            pedidas.append(url)
            return base(url)
        r = descubrir(ORIGEN, fetch)
        assert [u["url"] for u in r["urls"]] == ["https://e.com/a"]
        assert not any(u.startswith(("file:", "http://169.254")) for u in pedidas)

    def test_fetch_http_rechaza_esquemas_no_http(self):
        from discover_urls import fetch_http
        assert fetch_http("file:///etc/passwd") == (None, b"", "file:///etc/passwd")

    def test_fetch_http_captura_lectura_incompleta(self, monkeypatch):
        import http.client
        import discover_urls
        def boom(*a, **k):
            raise http.client.IncompleteRead(b"x")
        monkeypatch.setattr(discover_urls, "urlopen", boom)
        assert discover_urls.fetch_http("https://e.com/")[0] is None

    def test_enlace_malformado_no_aborta(self):
        assert extraer_enlaces('<a href="http://[bad">x</a><a href="/ok">ok</a>', "https://e.com/") == ["https://e.com/ok"]


class TestCli:
    def test_crea_la_carpeta_de_salida(self, tmp_path, monkeypatch):
        import discover_urls
        monkeypatch.setattr(discover_urls, "descubrir", lambda *a, **k: {"fuente": "sitemap", "total": 0, "omitidas_por_max": 0,
                                                                          "excluidas": [], "urls": []})
        destino = tmp_path / "a" / "b" / "urls.json"
        monkeypatch.setattr(sys, "argv", ["discover_urls.py", "https://e.com", "--out", str(destino)])
        discover_urls.main()
        assert destino.exists()
