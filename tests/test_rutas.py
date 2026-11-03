import datetime
import subprocess
import sys
from pathlib import Path

import pytest

from rutas import CARPETA_RAIZ, carpeta_auditoria, carpeta_documentos

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "rutas.py"
FECHA = datetime.date(2026, 11, 3)


class TestCarpetaDocumentos:
    def test_variable_de_entorno_tiene_prioridad(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUDITORIA_OUT_BASE", str(tmp_path / "otra"))
        assert carpeta_documentos(home=tmp_path) == tmp_path / "otra"

    def test_usa_documents_si_existe(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AUDITORIA_OUT_BASE", raising=False)
        (tmp_path / "Documents").mkdir()
        assert carpeta_documentos(home=tmp_path, xdg=lambda: None) == tmp_path / "Documents"

    def test_usa_documentos_en_espanol_si_es_la_que_existe(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AUDITORIA_OUT_BASE", raising=False)
        (tmp_path / "Documentos").mkdir()
        assert carpeta_documentos(home=tmp_path, xdg=lambda: None) == tmp_path / "Documentos"

    def test_respeta_xdg_en_linux(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AUDITORIA_OUT_BASE", raising=False)
        (tmp_path / "Docs").mkdir()
        assert carpeta_documentos(home=tmp_path, xdg=lambda: str(tmp_path / "Docs")) == tmp_path / "Docs"

    def test_xdg_que_apunta_al_home_se_ignora(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AUDITORIA_OUT_BASE", raising=False)
        assert carpeta_documentos(home=tmp_path, xdg=lambda: str(tmp_path)) == tmp_path / "Documents"


class TestCarpetaAuditoria:
    def test_nombre_por_dominio_y_fecha_sin_www(self, tmp_path):
        r = carpeta_auditoria("https://www.Ejemplo.com/blog?x=1", base=tmp_path, fecha=FECHA)
        assert r == tmp_path / CARPETA_RAIZ / "ejemplo.com-2026-11-03"

    def test_puerto_local_queda_en_el_nombre(self, tmp_path):
        r = carpeta_auditoria("http://localhost:3000", base=tmp_path, fecha=FECHA)
        assert r.name == "localhost-3000-2026-11-03"

    def test_dominio_sin_esquema(self, tmp_path):
        assert carpeta_auditoria("ejemplo.com", base=tmp_path, fecha=FECHA).name == "ejemplo.com-2026-11-03"

    def test_url_invalida_lanza_value_error(self, tmp_path):
        with pytest.raises(ValueError):
            carpeta_auditoria("https://", base=tmp_path, fecha=FECHA)


class TestCli:
    def test_crea_la_carpeta_e_imprime_ruta_absoluta(self, tmp_path):
        env = {"AUDITORIA_OUT_BASE": str(tmp_path), "PATH": "/usr/bin:/bin"}
        r = subprocess.run([sys.executable, str(SCRIPT), "https://ejemplo.com"], capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr
        ruta = Path(r.stdout.strip())
        assert ruta.is_absolute() and ruta.is_dir() and ruta.parent == tmp_path / CARPETA_RAIZ


class TestEnProceso:
    def test_main_crea_carpeta_e_imprime(self, tmp_path, monkeypatch, capsys):
        import rutas
        monkeypatch.setenv("AUDITORIA_OUT_BASE", str(tmp_path))
        rutas.main(["https://e.com"])
        assert Path(capsys.readouterr().out.strip()).is_dir()

    @pytest.mark.parametrize("argv", [[], ["https://"]])
    def test_main_con_argumentos_invalidos_termina_con_error(self, argv, tmp_path, monkeypatch):
        import rutas
        monkeypatch.setenv("AUDITORIA_OUT_BASE", str(tmp_path))
        with pytest.raises(SystemExit) as e:
            rutas.main(argv)
        assert e.value.code

    def test_xdg_ausente_devuelve_none(self, monkeypatch):
        import rutas
        monkeypatch.setattr(rutas.shutil, "which", lambda _: None)
        assert rutas._xdg_documentos() is None

    def test_xdg_presente_devuelve_su_salida(self, monkeypatch):
        import rutas
        monkeypatch.setattr(rutas.shutil, "which", lambda _: "/usr/bin/xdg-user-dir")
        monkeypatch.setattr(rutas.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "/home/u/Documentos\n", ""))
        assert rutas._xdg_documentos() == "/home/u/Documentos"

    def test_sin_base_usa_documentos_del_usuario(self, tmp_path, monkeypatch):
        import rutas
        monkeypatch.setenv("AUDITORIA_OUT_BASE", str(tmp_path))
        assert carpeta_auditoria("e.com", fecha=FECHA).parent == tmp_path / CARPETA_RAIZ
