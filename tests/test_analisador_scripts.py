import os

import pytest

import analisador_scripts as a


def which_com(*instalados):
    """Simula shutil.which: só 'encontra' os programas listados."""
    return lambda nome: f"/usr/bin/{nome}" if nome in instalados else None


def criar(tmp_path, nome, conteudo, modo="w"):
    arquivo = tmp_path / nome
    if modo == "wb":
        arquivo.write_bytes(conteudo)
    else:
        arquivo.write_text(conteudo, encoding="utf-8")
    return str(arquivo)


def test_python_por_extensao_no_linux(tmp_path):
    caminho = criar(tmp_path, "app.py", "print('oi')\n")
    r = a.analisar(caminho, "linux", which_com("python3"))
    assert r.linguagem is a.PYTHON
    assert r.origem == "extensão .py"
    assert r.comandos == [f"python3 {caminho}"]
    assert not r.avisos


def test_python_no_windows_prefere_py_launcher(tmp_path):
    caminho = criar(tmp_path, "app.py", "print('oi')\n")
    r = a.analisar(caminho, "windows", which_com("py", "python"))
    assert r.comandos[0].startswith("py ")


def test_shell_no_unix_inclui_chmod(tmp_path):
    caminho = criar(tmp_path, "deploy.sh", "#!/bin/bash\necho oi\n")
    os.chmod(caminho, 0o644)
    r = a.analisar(caminho, "linux", which_com("bash"))
    assert r.comandos == [f"chmod +x {caminho}", caminho]


def test_shell_ja_executavel_dispensa_chmod(tmp_path):
    caminho = criar(tmp_path, "deploy.sh", "#!/bin/bash\necho oi\n")
    os.chmod(caminho, 0o755)
    r = a.analisar(caminho, "macos", which_com("bash"))
    assert r.comandos == [caminho]


def test_shell_sem_shebang_gera_aviso(tmp_path):
    caminho = criar(tmp_path, "x.sh", "echo oi\n")
    r = a.analisar(caminho, "linux", which_com("bash"))
    assert any("shebang" in aviso for aviso in r.avisos)


def test_caminho_relativo_ganha_ponto_barra(tmp_path, monkeypatch):
    criar(tmp_path, "rodar.sh", "#!/bin/sh\n")
    monkeypatch.chdir(tmp_path)
    r = a.analisar("rodar.sh", "linux", which_com("bash"))
    assert r.comandos == ["chmod +x rodar.sh", "./rodar.sh"]


def test_shell_no_windows_usa_bash(tmp_path):
    caminho = criar(tmp_path, "x.sh", "#!/bin/bash\n")
    r = a.analisar(caminho, "windows", which_com("bash"))
    assert r.comandos[0].startswith("bash ")
    assert any("Git Bash" in aviso for aviso in r.avisos)


@pytest.mark.parametrize("shebang, linguagem", [
    ("#!/bin/bash", a.SHELL),
    ("#!/usr/bin/env node", a.NODE),
    ("#!/usr/bin/env -S deno run --allow-all", a.TYPESCRIPT),
    ("#!/usr/bin/python3.11", a.PYTHON),
    ("#!/usr/bin/env ruby", a.RUBY),
    ("#!/usr/bin/perl -w", a.PERL),
])
def test_sem_extensao_usa_shebang(tmp_path, shebang, linguagem):
    caminho = criar(tmp_path, "ferramenta", shebang + "\n")
    assert a.analisar(caminho, "linux", which_com()).linguagem is linguagem


def test_shebang_python_sem_extensao_roda_com_interpretador(tmp_path):
    caminho = criar(tmp_path, "ferramenta", "#!/usr/bin/env python3\n")
    r = a.analisar(caminho, "linux", which_com("python3"))
    assert r.comandos == [f"python3 {caminho}"]


def test_powershell_no_windows(tmp_path):
    caminho = criar(tmp_path, "setup.ps1", "Write-Host oi\n")
    r = a.analisar(caminho, "windows", which_com("powershell"))
    assert r.comandos == [f"powershell -ExecutionPolicy Bypass -File {caminho}"]


def test_powershell_utf16_nao_e_binario(tmp_path):
    caminho = criar(tmp_path, "setup.ps1", "Write-Host oi\n".encode("utf-16"), "wb")
    assert a.analisar(caminho, "windows", which_com("powershell")).linguagem is a.POWERSHELL


def test_batch_fora_do_windows_avisa(tmp_path):
    caminho = criar(tmp_path, "run.bat", "@echo off\n")
    r = a.analisar(caminho, "linux", which_com())
    assert r.comandos == []
    assert "só roda no Windows" in r.avisos[0]


def test_batch_no_windows_com_espaco_no_caminho(tmp_path):
    pasta = tmp_path / "Meus Scripts"
    pasta.mkdir()
    caminho = criar(pasta, "run.bat", "@echo off\n")
    r = a.analisar(caminho, "windows", which_com("cmd"))
    assert r.comandos == [f'cmd /c "{caminho}"']


def test_interpretador_ausente_avisa_e_mostra_comando(tmp_path):
    caminho = criar(tmp_path, "app.rb", "puts 1\n")
    r = a.analisar(caminho, "linux", which_com())
    assert r.interpretador is None
    assert r.comandos == [f"ruby {caminho}"]
    assert "não foi encontrado" in r.avisos[0]


def test_typescript_com_deno(tmp_path):
    caminho = criar(tmp_path, "app.ts", "console.log(1)\n")
    r = a.analisar(caminho, "linux", which_com("deno"))
    assert r.comandos == [f"deno run {caminho}"]


def test_php_por_conteudo(tmp_path):
    caminho = criar(tmp_path, "pagina", "<?php echo 1;\n")
    assert a.analisar(caminho, "linux", which_com()).linguagem is a.PHP


def test_arquivo_inexistente(tmp_path):
    with pytest.raises(a.ErroAnalise, match="não encontrado"):
        a.analisar(str(tmp_path / "nada.py"), "linux")


def test_pasta_de_projeto_autotools(tmp_path):
    (tmp_path / "configure").write_text("#!/bin/sh\n")
    (tmp_path / "Makefile.am").write_text("")
    r = a.analisar(str(tmp_path), "linux", which_com("make"))
    assert r.eh_pasta
    assert r.linguagem.nome == "Projeto C/C++ (Autotools)"
    assert r.comandos == [f"cd {tmp_path}", "./configure", "make"]
    assert any("compilado" in aviso for aviso in r.avisos)


def test_pasta_de_projeto_prioriza_configure_sobre_makefile(tmp_path):
    (tmp_path / "configure").write_text("")
    (tmp_path / "Makefile").write_text("all:\n")
    r = a.analisar(str(tmp_path), "linux", which_com("make"))
    assert r.linguagem.nome == "Projeto C/C++ (Autotools)"


def test_pasta_makefile_puro(tmp_path):
    (tmp_path / "Makefile").write_text("all:\n")
    r = a.analisar(str(tmp_path), "linux", which_com("make"))
    assert r.comandos == [f"cd {tmp_path}", "make"]


def test_pasta_python_requirements(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests\n")
    r = a.analisar(str(tmp_path), "linux", which_com("pip"))
    assert r.comandos == [f"cd {tmp_path}", "pip install -r requirements.txt"]


def test_pasta_ferramenta_ausente_avisa(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]\n")
    r = a.analisar(str(tmp_path), "linux", which_com())
    assert r.interpretador is None
    assert any("cargo" in aviso for aviso in r.avisos)


def test_pasta_sem_marcador_conhecido(tmp_path):
    (tmp_path / "leiame.txt").write_text("nada\n")
    with pytest.raises(a.ErroAnalise, match="não reconheci o tipo de projeto"):
        a.analisar(str(tmp_path), "linux")


def test_binario(tmp_path):
    caminho = criar(tmp_path, "programa", b"\x7fELF\x02\x01\x01\x00\x00", "wb")
    with pytest.raises(a.ErroAnalise, match="binário"):
        a.analisar(caminho, "linux")


def test_sem_extensao_nem_shebang(tmp_path):
    caminho = criar(tmp_path, "misterio", "algum texto\n")
    with pytest.raises(a.ErroAnalise, match="extensão nem shebang"):
        a.analisar(caminho, "linux")


def test_main_mostra_saida_e_codigo_de_erro(tmp_path, capsys):
    ok = criar(tmp_path, "app.py", "print(1)\n")
    assert a.main([ok]) == 0
    assert "Python" in capsys.readouterr().out
    assert a.main([str(tmp_path / "nada.py")]) == 1
    assert "Erro:" in capsys.readouterr().err
