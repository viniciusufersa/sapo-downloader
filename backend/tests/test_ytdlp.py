import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from app.config import carregar_configuracoes
from app.ytdlp import ErroYtDlp, ServicoYtDlp


class SaidaSimulada:
    def __init__(self, linhas: list[bytes] | None = None) -> None:
        self.linhas = iter(linhas or [])

    async def readline(self) -> bytes:
        return next(self.linhas, b"")


class ProcessoSimulado:
    def __init__(self, returncode: int = 0, linhas: list[bytes] | None = None) -> None:
        self.returncode = returncode
        self.stdout = SaidaSimulada(linhas)

    async def communicate(self) -> tuple[bytes, bytes]:
        return b'{"id":"abcdefghijk"}', b""

    async def wait(self) -> int:
        return self.returncode


def test_deve_desativar_componentes_remotos_ao_consultar_metadados(monkeypatch) -> None:
    argumentos_executados: list[str] = []

    async def criar_processo(*argumentos: str, **opcoes) -> ProcessoSimulado:
        argumentos_executados.extend(argumentos)
        return ProcessoSimulado()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", criar_processo)
    servico = ServicoYtDlp(carregar_configuracoes())

    metadados = asyncio.run(servico._consultar_metadados("https://www.youtube.com/watch?v=abcdefghijk"))

    assert metadados["id"] == "abcdefghijk"
    assert "--no-remote-components" in argumentos_executados


def test_deve_desativar_componentes_remotos_ao_baixar_midia(monkeypatch, tmp_path: Path) -> None:
    argumentos_executados: list[str] = []

    async def criar_processo(*argumentos: str, **opcoes) -> ProcessoSimulado:
        argumentos_executados.extend(argumentos)
        caminho_modelo = Path(argumentos[argumentos.index("--output") + 1])
        (caminho_modelo.parent / "abcdefghijk.mp4").write_bytes(b"video")
        return ProcessoSimulado()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", criar_processo)

    async def validar_midia(_servico: ServicoYtDlp, _caminho_arquivo: Path, _extensao_esperada: str) -> None:
        return None

    monkeypatch.setattr(ServicoYtDlp, "_validar_midia", validar_midia)
    configuracoes = replace(carregar_configuracoes(), tamanho_maximo_download_bytes=1024)
    servico = ServicoYtDlp(configuracoes)

    arquivo = asyncio.run(
        servico.baixar(
            "https://www.youtube.com/watch?v=abcdefghijk",
            "18",
            tmp_path,
            lambda _bytes_baixados, _bytes_totais: None,
            "mp4",
        )
    )

    assert arquivo.read_bytes() == b"video"
    assert "--no-remote-components" in argumentos_executados


def test_deve_solicitar_remux_compativel_quando_formatos_separados_fore_selecionados(
    monkeypatch, tmp_path: Path
) -> None:
    argumentos_executados: list[str] = []
    progresso_reportado: list[tuple[int, int | None]] = []

    async def criar_processo(*argumentos: str, **opcoes) -> ProcessoSimulado:
        argumentos_executados.extend(argumentos)
        caminho_modelo = Path(argumentos[argumentos.index("--output") + 1])
        (caminho_modelo.parent / "abcdefghijk.webm").write_bytes(b"video")
        return ProcessoSimulado(
            linhas=[
                b"SAPO_PROGRESS:243:100:200:NA\n",
                b"SAPO_PROGRESS:251:50:100:NA\n",
            ]
        )

    async def validar_midia(_servico: ServicoYtDlp, _caminho_arquivo: Path, _extensao_esperada: str) -> None:
        return None

    monkeypatch.setattr(asyncio, "create_subprocess_exec", criar_processo)
    monkeypatch.setattr(ServicoYtDlp, "_validar_midia", validar_midia)
    configuracoes = replace(carregar_configuracoes(), tamanho_maximo_download_bytes=1024)
    servico = ServicoYtDlp(configuracoes)

    arquivo = asyncio.run(
        servico.baixar(
            "https://www.youtube.com/watch?v=abcdefghijk",
            "243+251",
            tmp_path,
            lambda bytes_baixados, bytes_totais: progresso_reportado.append((bytes_baixados, bytes_totais)),
            "webm",
        )
    )

    assert arquivo.suffix == ".webm"
    assert argumentos_executados[argumentos_executados.index("--format") + 1] == "243+251"
    assert argumentos_executados[argumentos_executados.index("--merge-output-format") + 1] == "webm"
    assert progresso_reportado == [(100, None), (150, 300)]


def test_deve_rejeitar_identificador_de_formato_comando_quando_selecao_for_invalida(
    tmp_path: Path,
) -> None:
    servico = ServicoYtDlp(carregar_configuracoes())

    with pytest.raises(ErroYtDlp, match="Formato indisponível"):
        asyncio.run(
            servico.baixar(
                "https://www.youtube.com/watch?v=abcdefghijk",
                "18;--exec=calc",
                tmp_path,
                lambda _bytes_baixados, _bytes_totais: None,
                "mp4",
            )
        )
