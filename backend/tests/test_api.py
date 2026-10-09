import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app import main


@pytest.fixture(autouse=True)
def restaurar_estado_aplicacao():
    main.tarefas_download.clear()
    main.solicitacoes_por_chave.clear()
    try:
        yield
    finally:
        main.tarefas_download.clear()
        main.solicitacoes_por_chave.clear()


def test_deve_registrar_erro_quando_falhar_remocao_de_diretorio_temporario(
    monkeypatch, tmp_path, caplog
) -> None:
    def simular_erro_permissao(caminho_diretorio: Path) -> None:
        raise PermissionError(f"Acesso negado: {caminho_diretorio}")

    monkeypatch.setattr(main.shutil, "rmtree", simular_erro_permissao)

    with caplog.at_level("ERROR", logger="sapo"):
        main._remover_diretorio_temporario(tmp_path / "download")

    assert "Não foi possível remover uma pasta temporária" in caplog.text


def _metadados_video() -> dict:
    return {
        "id": "abcdefghijk",
        "title": "Vídeo de teste",
        "duration": 120,
        "thumbnail": "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg",
        "formats": [
            {
                "format_id": "18",
                "ext": "mp4",
                "height": 360,
                "vcodec": "avc1",
                "acodec": "mp4a",
            }
        ],
    }


def test_deve_analisar_midia_sem_baixar_quando_url_for_valida(monkeypatch, tmp_path) -> None:
    async def analisar(_: str) -> dict:
        return _metadados_video()

    monkeypatch.setattr(main.servico_ytdlp, "analisar", analisar)
    monkeypatch.setattr(main, "configuracoes", replace(main.configuracoes, diretorio_temporario=tmp_path))

    async def executar_requisicao():
        async with main.gerenciar_ciclo_vida(main.app):
            async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
                return await client.post("/api/media/analyze", json={"url": "https://youtu.be/abcdefghijk"})

    resposta = asyncio.run(executar_requisicao())
    assert resposta.status_code == 200
    assert resposta.json()["title"] == "Vídeo de teste"
    assert resposta.json()["formats"][0]["format_id"] == "18"
    assert resposta.headers["x-content-type-options"] == "nosniff"
    assert resposta.headers["referrer-policy"] == "no-referrer"


def test_deve_exigir_autorizacao_antes_de_baixar_quando_confirmacao_for_falsa(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "configuracoes", replace(main.configuracoes, diretorio_temporario=tmp_path))

    async def executar_requisicao():
        async with main.gerenciar_ciclo_vida(main.app):
            async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
                return await client.post(
                    "/api/downloads",
                    json={
                        "video_id": "abcdefghijk",
                        "format_id": "18",
                        "authorized": False,
                    },
                )

    resposta = asyncio.run(executar_requisicao())
    assert resposta.status_code == 400
    assert "autorização" in resposta.json()["detail"]


def test_deve_rejeitar_corpo_maior_que_limite_quando_requisicao_exceder_limite(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "configuracoes", replace(main.configuracoes, diretorio_temporario=tmp_path))

    async def partes_corpo():
        yield b'{"url":"'
        yield b"x" * main.LIMITE_CORPO_API_BYTES
        yield b'"}'

    async def executar_requisicao():
        async with main.gerenciar_ciclo_vida(main.app):
            async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
                return await client.post(
                    "/api/media/analyze",
                    content=partes_corpo(),
                    headers={"content-type": "application/json"},
                )

    resposta = asyncio.run(executar_requisicao())
    assert resposta.status_code == 413, resposta.text
    assert resposta.json()["detail"] == "Solicitação muito grande."
    assert resposta.headers["x-content-type-options"] == "nosniff"


def test_deve_entregar_e_remover_arquivo_quando_transferencia_terminar(tmp_path, monkeypatch) -> None:
    async def analisar(_: str) -> dict:
        return _metadados_video()

    async def baixar(_, __, diretorio_tarefa: Path, callback_progresso, ___) -> Path:
        callback_progresso(50, 100)
        arquivo_saida = diretorio_tarefa / "abcdefghijk.mp4"
        arquivo_saida.write_bytes(b"video")
        return arquivo_saida

    monkeypatch.setattr(main.servico_ytdlp, "analisar", analisar)
    monkeypatch.setattr(main.servico_ytdlp, "baixar", baixar)
    monkeypatch.setattr(main, "configuracoes", replace(main.configuracoes, diretorio_temporario=tmp_path))
    main.tarefas_download.clear()

    async def executar_requisicoes():
        async with main.gerenciar_ciclo_vida(main.app):
            async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
                criado = await client.post(
                    "/api/downloads",
                    json={"video_id": "abcdefghijk", "format_id": "18", "authorized": True},
                )
                download_id = criado.json()["download_id"]
                for _ in range(10):
                    status_http = await client.get(f"/api/downloads/{download_id}")
                    if status_http.json()["status"] in {"completed", "failed"}:
                        break
                    await asyncio.sleep(0.01)
                resposta_arquivo = await client.get(f"/api/downloads/{download_id}/file")
                inexistente = await client.get(f"/api/downloads/{download_id}")
                return criado, status_http, resposta_arquivo, inexistente

    criado, status_http, resposta_arquivo, inexistente = asyncio.run(executar_requisicoes())
    assert criado.status_code == 202
    assert status_http.json()["status"] == "completed"
    assert status_http.json()["progress"] == 100
    assert resposta_arquivo.content == b"video"
    assert inexistente.status_code == 404
    assert not list(tmp_path.iterdir())


def test_deve_falhar_e_remover_pasta_quando_formato_nao_estiver_disponivel(tmp_path, monkeypatch) -> None:
    async def analisar(_: str) -> dict:
        return _metadados_video()

    monkeypatch.setattr(main.servico_ytdlp, "analisar", analisar)
    monkeypatch.setattr(main, "configuracoes", replace(main.configuracoes, diretorio_temporario=tmp_path))
    main.tarefas_download.clear()

    async def executar_requisicoes():
        async with main.gerenciar_ciclo_vida(main.app):
            async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
                criado = await client.post(
                    "/api/downloads",
                    json={"video_id": "abcdefghijk", "format_id": "999", "authorized": True},
                )
                download_id = criado.json()["download_id"]
                for _ in range(10):
                    status_http = await client.get(f"/api/downloads/{download_id}")
                    if status_http.json()["status"] in {"completed", "failed"}:
                        break
                    await asyncio.sleep(0.01)
                return criado, status_http

    criado, status_http = asyncio.run(executar_requisicoes())
    assert criado.status_code == 202
    assert status_http.json()["status"] == "failed"
    assert "não está mais disponível" in status_http.json()["message"]
    assert not list(tmp_path.iterdir())


def test_deve_limitar_arquivos_concluidos_quando_arquivo_anterior_estiver_pendente(
    tmp_path, monkeypatch
) -> None:
    async def analisar(_: str) -> dict:
        return _metadados_video()

    async def baixar(_, __, diretorio_tarefa: Path, ___, ____) -> Path:
        arquivo_saida = diretorio_tarefa / "abcdefghijk.mp4"
        arquivo_saida.write_bytes(b"video")
        return arquivo_saida

    monkeypatch.setattr(main.servico_ytdlp, "analisar", analisar)
    monkeypatch.setattr(main.servico_ytdlp, "baixar", baixar)
    monkeypatch.setattr(main, "configuracoes", replace(main.configuracoes, diretorio_temporario=tmp_path))
    main.tarefas_download.clear()

    async def executar_requisicoes():
        async with main.gerenciar_ciclo_vida(main.app):
            async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
                criado = await client.post(
                    "/api/downloads",
                    json={"video_id": "abcdefghijk", "format_id": "18", "authorized": True},
                )
                download_id = criado.json()["download_id"]
                for _ in range(10):
                    status_http = await client.get(f"/api/downloads/{download_id}")
                    if status_http.json()["status"] == "completed":
                        break
                    await asyncio.sleep(0.01)
                segunda_solicitacao = await client.post(
                    "/api/downloads",
                    json={"video_id": "abcdefghijk", "format_id": "18", "authorized": True},
                )
                return criado, status_http, segunda_solicitacao

    criado, status_http, segunda_solicitacao = asyncio.run(executar_requisicoes())
    assert criado.status_code == 202
    assert status_http.json()["status"] == "completed"
    assert segunda_solicitacao.status_code == 429
    assert "Baixe o arquivo pronto" in segunda_solicitacao.json()["detail"]


def test_deve_cancelar_processamento_e_remover_arquivos_quando_solicitado(tmp_path, monkeypatch) -> None:
    async def analisar(_: str) -> dict:
        return _metadados_video()

    async def baixar(_, __, ___, ____, _____):
        await asyncio.Event().wait()

    monkeypatch.setattr(main.servico_ytdlp, "analisar", analisar)
    monkeypatch.setattr(main.servico_ytdlp, "baixar", baixar)
    monkeypatch.setattr(main, "configuracoes", replace(main.configuracoes, diretorio_temporario=tmp_path))

    async def executar_requisicoes():
        async with main.gerenciar_ciclo_vida(main.app):
            async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
                criado = await client.post(
                    "/api/downloads",
                    json={"video_id": "abcdefghijk", "format_id": "18", "authorized": True},
                )
                download_id = criado.json()["download_id"]
                await asyncio.sleep(0.02)
                cancelado = await client.delete(f"/api/downloads/{download_id}")
                status_http = await client.get(f"/api/downloads/{download_id}")
                return criado, cancelado, status_http

    criado, cancelado, status_http = asyncio.run(executar_requisicoes())
    assert criado.status_code == 202
    assert cancelado.status_code == 204
    assert status_http.status_code == 404
    assert not list(tmp_path.iterdir())
