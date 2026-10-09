import asyncio
from collections import deque

import pytest
from fastapi import HTTPException, Request

from app import main


@pytest.fixture(autouse=True)
def restaurar_controle_requisicoes():
    main.solicitacoes_por_chave.clear()
    yield
    main.solicitacoes_por_chave.clear()


def _criar_requisicao(endereco_cliente: str, endereco_encaminhado: str = "") -> Request:
    cabecalhos = []
    if endereco_encaminhado:
        cabecalhos.append((b"x-forwarded-for", endereco_encaminhado.encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": "/api/media/analyze",
            "raw_path": b"/api/media/analyze",
            "query_string": b"",
            "headers": cabecalhos,
            "client": (endereco_cliente, 5000),
            "server": ("testserver", 80),
        }
    )


def test_deve_limitar_novas_chaves_quando_capacidade_de_memoria_for_atingida(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "LIMITE_CHAVES_CONTROLE_REQUISICOES", 2)

    async def validar_requisicoes() -> None:
        main._validar_limite_requisicoes(_criar_requisicao("192.0.2.1"), "analyze")
        main._validar_limite_requisicoes(_criar_requisicao("192.0.2.2"), "analyze")
        with pytest.raises(HTTPException) as erro:
            main._validar_limite_requisicoes(_criar_requisicao("192.0.2.3"), "analyze")
        assert erro.value.status_code == 429

    asyncio.run(validar_requisicoes())
    assert len(main.solicitacoes_por_chave) == 2


def test_deve_remover_chaves_expiradas_antes_de_recusar_novo_cliente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "LIMITE_CHAVES_CONTROLE_REQUISICOES", 2)

    async def validar_requisicao() -> None:
        agora = asyncio.get_running_loop().time()
        instante_expirado = agora - main.JANELA_CONTROLE_REQUISICOES_SEGUNDOS - 1
        main.solicitacoes_por_chave["192.0.2.1:analyze"] = deque([instante_expirado])
        main.solicitacoes_por_chave["192.0.2.2:analyze"] = deque([instante_expirado])

        main._validar_limite_requisicoes(_criar_requisicao("192.0.2.3"), "analyze")

    asyncio.run(validar_requisicao())
    assert set(main.solicitacoes_por_chave) == {"192.0.2.3:analyze"}


def test_deve_ignorar_cabecalho_encaminhado_na_identificacao_do_cliente() -> None:
    async def validar_requisicoes() -> None:
        for _ in range(12):
            main._validar_limite_requisicoes(_criar_requisicao("192.0.2.1", "198.51.100.1"), "analyze")

        with pytest.raises(HTTPException) as erro:
            main._validar_limite_requisicoes(_criar_requisicao("192.0.2.1", "203.0.113.99"), "analyze")
        assert erro.value.status_code == 429

    asyncio.run(validar_requisicoes())
    assert set(main.solicitacoes_por_chave) == {"192.0.2.1:analyze"}
