import asyncio
import logging
import re
import shutil
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import carregar_configuracoes
from .schemas import (
    DownloadAceito,
    OpcaoFormato,
    PreviaMidia,
    SolicitacaoAnalise,
    SolicitacaoDownload,
    StatusDownload,
)
from .security import normalizar_url_youtube
from .ytdlp import ErroYtDlp, ServicoYtDlp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
registrador = logging.getLogger("sapo")
configuracoes = carregar_configuracoes()
servico_ytdlp = ServicoYtDlp(configuracoes)
vagas_download = asyncio.Semaphore(configuracoes.limite_downloads_simultaneos)
vagas_analise = asyncio.Semaphore(configuracoes.limite_downloads_simultaneos)


@dataclass
class TarefaDownload:
    download_id: str
    diretorio_tarefa: Path
    situacao: Literal["queued", "processing", "completed", "failed", "expired"] = "queued"
    progresso: float | None = None
    mensagem: str = "Aguardando processamento."
    caminho_arquivo: Path | None = None
    criada_em: float = field(default_factory=lambda: asyncio.get_running_loop().time())
    arquivo_em_transferencia: bool = False
    tarefa_async: asyncio.Task[None] | None = None


tarefas_download: dict[str, TarefaDownload] = {}
solicitacoes_por_chave: dict[str, deque[float]] = {}
bloqueio_tarefas = asyncio.Lock()
LIMITE_CORPO_API_BYTES = 16_384
LIMITE_CHAVES_CONTROLE_REQUISICOES = 4_096
JANELA_CONTROLE_REQUISICOES_SEGUNDOS = 60


class LimiteCorpoApiMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return

        tamanho_cabecalho = next(
            (
                valor
                for nome_cabecalho, valor in scope["headers"]
                if nome_cabecalho.lower() == b"content-length"
            ),
            b"",
        )
        if tamanho_cabecalho.isdigit() and int(tamanho_cabecalho) > LIMITE_CORPO_API_BYTES:
            resposta = JSONResponse(status_code=413, content={"detail": "Solicitação muito grande."})
            await resposta(scope, receive, send)
            return

        mensagens_corpo: list[Message] = []
        bytes_recebidos = 0
        while True:
            mensagem = await receive()
            if mensagem["type"] == "http.request":
                bytes_recebidos += len(mensagem.get("body", b""))
                if bytes_recebidos > LIMITE_CORPO_API_BYTES:
                    resposta = JSONResponse(status_code=413, content={"detail": "Solicitação muito grande."})
                    await resposta(scope, receive, send)
                    return
                mensagens_corpo.append(mensagem)
                if not mensagem.get("more_body", False):
                    break
            elif mensagem["type"] == "http.disconnect":
                mensagens_corpo.append(mensagem)
                break
            else:
                mensagens_corpo.append(mensagem)
                break

        proxima_mensagem = 0

        async def repetir_recebimento() -> Message:
            nonlocal proxima_mensagem
            if proxima_mensagem < len(mensagens_corpo):
                mensagem = mensagens_corpo[proxima_mensagem]
                proxima_mensagem += 1
                return mensagem
            return await receive()

        await self.app(scope, repetir_recebimento, send)


def _sanitizar_titulo(titulo_original: object) -> str:
    titulo = re.sub(r"[\x00-\x1f\x7f]", "", str(titulo_original or "Vídeo do YouTube"))
    return titulo.strip()[:200] or "Vídeo do YouTube"


def _combinar_codec_conteiner(codec_video: object, codec_audio: object) -> str | None:
    codec_video = str(codec_video or "").lower()
    codec_audio = str(codec_audio or "").lower()
    if codec_video.startswith(("avc1", "avc3")) and codec_audio.startswith("mp4a"):
        return "mp4"
    if codec_video.startswith(("vp8", "vp9", "av01")) and codec_audio.startswith(("opus", "vorbis")):
        return "webm"
    return None


def _tamanho_formato(formato_midia: dict) -> int | None:
    tamanho = formato_midia.get("filesize") or formato_midia.get("filesize_approx")
    return int(tamanho) if isinstance(tamanho, (int, float)) and tamanho > 0 else None


def _altura_formato(formato_midia: dict) -> int | None:
    altura = formato_midia.get("height")
    return int(altura) if isinstance(altura, (int, float)) and altura > 0 else None


def _criar_opcao_formato(
    id_formato: str,
    extensao: str,
    altura: int | None,
    tamanho: int | None,
    quadros_por_segundo: int | None = None,
) -> OpcaoFormato:
    qualidade = f"{altura}p" if altura else "Qualidade padrão"
    if quadros_por_segundo and quadros_por_segundo > 30:
        qualidade += f" {quadros_por_segundo} fps"
    return OpcaoFormato(
        format_id=id_formato,
        label=f"{qualidade} · {extensao.upper()}",
        ext=extensao,
        height=altura,
        filesize=tamanho,
    )


def _montar_previa_midia(
    video_id: str, metadados_video: dict, duracao_maxima: int, tamanho_maximo: int
) -> PreviaMidia:
    if (
        metadados_video.get("id") != video_id
        or metadados_video.get("is_live") is True
        or metadados_video.get("live_status") in {"is_live", "is_upcoming"}
    ):
        raise HTTPException(
            status_code=422, detail="Este link não corresponde a um vídeo individual disponível."
        )
    duracao = metadados_video.get("duration")
    if not isinstance(duracao, (int, float)) or duracao <= 0 or duracao > duracao_maxima:
        raise HTTPException(status_code=422, detail="A duração deste vídeo está fora do limite permitido.")

    thumbnail = metadados_video.get("thumbnail")
    if not isinstance(thumbnail, str) or not thumbnail.startswith(
        ("https://i.ytimg.com/", "https://img.youtube.com/")
    ):
        thumbnail = None

    formatos_disponiveis: list[OpcaoFormato] = []
    formatos_video: list[dict] = []
    formatos_audio: dict[str, list[dict]] = {"mp4": [], "webm": []}
    formatos_recebidos = metadados_video.get("formats")
    if not isinstance(formatos_recebidos, list):
        formatos_recebidos = []

    for formato_midia in formatos_recebidos:
        if not isinstance(formato_midia, dict):
            continue
        id_formato = str(formato_midia.get("format_id", ""))
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", id_formato):
            continue

        codec_video = formato_midia.get("vcodec")
        codec_audio = formato_midia.get("acodec")
        tem_video = isinstance(codec_video, str) and codec_video != "none"
        tem_audio = isinstance(codec_audio, str) and codec_audio != "none"
        if tem_video and tem_audio:
            extensao = _combinar_codec_conteiner(codec_video, codec_audio)
            if extensao != formato_midia.get("ext"):
                continue
            formatos_video.append(formato_midia)
        elif tem_video and not tem_audio:
            for extensao in ("mp4", "webm"):
                if (
                    _combinar_codec_conteiner(codec_video, "mp4a" if extensao == "mp4" else "opus")
                    == extensao
                ):
                    formatos_video.append({**formato_midia, "sapo_ext": extensao})
        elif tem_audio and not tem_video:
            for extensao in ("mp4", "webm"):
                if _combinar_codec_conteiner("avc1" if extensao == "mp4" else "vp9", codec_audio) == extensao:
                    formatos_audio[extensao].append(formato_midia)

    for formato_video in formatos_video:
        id_video = str(formato_video.get("format_id", ""))
        extensao = formato_video.get("sapo_ext", formato_video.get("ext"))
        if extensao not in {"mp4", "webm"}:
            continue
        codec_video = formato_video.get("vcodec")
        codec_audio = formato_video.get("acodec")
        altura = _altura_formato(formato_video)
        tamanho_video = _tamanho_formato(formato_video)
        if codec_audio is not None and codec_audio != "none":
            tamanho_saida = tamanho_video
            if tamanho_saida is not None and tamanho_saida > tamanho_maximo:
                continue
            formatos_disponiveis.append(
                _criar_opcao_formato(
                    id_video,
                    extensao,
                    altura,
                    tamanho_saida,
                    int(formato_video["fps"]) if isinstance(formato_video.get("fps"), (int, float)) else None,
                )
            )
            continue

        for formato_audio in formatos_audio[extensao]:
            id_audio = str(formato_audio.get("format_id", ""))
            tamanho_audio = _tamanho_formato(formato_audio)
            tamanho_saida = (
                tamanho_video + tamanho_audio
                if tamanho_video is not None and tamanho_audio is not None
                else None
            )
            if tamanho_saida is not None and tamanho_saida > tamanho_maximo:
                continue
            formatos_disponiveis.append(
                _criar_opcao_formato(
                    f"{id_video}+{id_audio}",
                    extensao,
                    altura,
                    tamanho_saida,
                    int(formato_video["fps"]) if isinstance(formato_video.get("fps"), (int, float)) else None,
                )
            )

    formatos_disponiveis = list(
        {opcao_formato.format_id: opcao_formato for opcao_formato in formatos_disponiveis}.values()
    )
    formatos_disponiveis = [
        opcao_formato
        for opcao_formato in formatos_disponiveis
        if opcao_formato.filesize is None or opcao_formato.filesize <= tamanho_maximo
    ]
    melhores_formatos: dict[tuple[str, int | None, str], OpcaoFormato] = {}
    for opcao_formato in formatos_disponiveis:
        chave_formato = (opcao_formato.ext, opcao_formato.height, opcao_formato.label)
        formato_atual = melhores_formatos.get(chave_formato)
        if formato_atual is None or (opcao_formato.filesize or 0) > (formato_atual.filesize or 0):
            melhores_formatos[chave_formato] = opcao_formato
    formatos_disponiveis = list(melhores_formatos.values())

    formatos_disponiveis.sort(
        key=lambda opcao_formato: (opcao_formato.height or 0, opcao_formato.ext == "mp4"),
        reverse=True,
    )
    if not formatos_disponiveis:
        raise HTTPException(
            status_code=422, detail="Não há formatos de vídeo compatíveis e disponíveis para este link."
        )
    return PreviaMidia(
        video_id=video_id,
        title=_sanitizar_titulo(metadados_video.get("title")),
        thumbnail=thumbnail,
        duration_seconds=int(duracao),
        formats=formatos_disponiveis,
    )


def _validar_limite_requisicoes(requisicao: Request, tipo_solicitacao: str) -> None:
    endereco_cliente = requisicao.client.host if requisicao.client else "desconhecido"
    agora = asyncio.get_running_loop().time()
    chave_solicitacao = f"{endereco_cliente}:{tipo_solicitacao}"
    instantes_requisicao = solicitacoes_por_chave.get(chave_solicitacao)
    if instantes_requisicao is None:
        if len(solicitacoes_por_chave) >= LIMITE_CHAVES_CONTROLE_REQUISICOES:
            limite_expiracao = agora - JANELA_CONTROLE_REQUISICOES_SEGUNDOS
            chaves_expiradas = [
                chave
                for chave, instantes in solicitacoes_por_chave.items()
                if not instantes or instantes[-1] <= limite_expiracao
            ]
            for chave in chaves_expiradas:
                solicitacoes_por_chave.pop(chave, None)
        if len(solicitacoes_por_chave) >= LIMITE_CHAVES_CONTROLE_REQUISICOES:
            raise HTTPException(
                status_code=429,
                detail="O limite temporário de clientes foi atingido. Tente novamente em breve.",
            )
        instantes_requisicao = deque()
        solicitacoes_por_chave[chave_solicitacao] = instantes_requisicao

    limite_requisicoes = 12 if tipo_solicitacao == "analyze" else 4
    while instantes_requisicao and instantes_requisicao[0] <= agora - JANELA_CONTROLE_REQUISICOES_SEGUNDOS:
        instantes_requisicao.popleft()
    if len(instantes_requisicao) >= limite_requisicoes:
        raise HTTPException(
            status_code=429, detail="Muitas solicitações. Aguarde um minuto e tente novamente."
        )
    instantes_requisicao.append(agora)


async def _limpar_tarefas_expiradas() -> None:
    while True:
        await asyncio.sleep(60)
        agora = asyncio.get_running_loop().time()
        async with bloqueio_tarefas:
            tarefas_expiradas = [
                tarefa_download
                for tarefa_download in tarefas_download.values()
                if tarefa_download.situacao in {"completed", "failed"}
                and not tarefa_download.arquivo_em_transferencia
                and agora - tarefa_download.criada_em > configuracoes.validade_temporario_segundos
            ]
            for tarefa_download in tarefas_expiradas:
                tarefas_download.pop(tarefa_download.download_id, None)
                tarefa_download.situacao = "expired"
        for tarefa_download in tarefas_expiradas:
            _remover_diretorio_temporario(tarefa_download.diretorio_tarefa)


def _remover_diretorio_temporario(diretorio: Path) -> None:
    try:
        shutil.rmtree(diretorio)
    except FileNotFoundError:
        return
    except OSError:
        registrador.exception("Não foi possível remover uma pasta temporária")


@asynccontextmanager
async def gerenciar_ciclo_vida(_: FastAPI):
    configuracoes.diretorio_temporario.mkdir(parents=True, exist_ok=True)
    for pasta_antiga in configuracoes.diretorio_temporario.iterdir():
        if pasta_antiga.is_dir() and re.fullmatch(r"[a-f0-9]{32}", pasta_antiga.name):
            try:
                if pasta_antiga.stat().st_mtime < time.time() - configuracoes.validade_temporario_segundos:
                    _remover_diretorio_temporario(pasta_antiga)
            except OSError:
                registrador.warning("Não foi possível verificar uma pasta temporária antiga")
    tarefa_limpeza = asyncio.create_task(_limpar_tarefas_expiradas())
    yield
    tarefa_limpeza.cancel()
    with suppress(asyncio.CancelledError):
        await tarefa_limpeza
    tarefas_ativas = [
        tarefa_download.tarefa_async
        for tarefa_download in tarefas_download.values()
        if tarefa_download.tarefa_async and not tarefa_download.tarefa_async.done()
    ]
    for tarefa_async in tarefas_ativas:
        tarefa_async.cancel()
    if tarefas_ativas:
        await asyncio.gather(*tarefas_ativas, return_exceptions=True)
    for tarefa_download in tarefas_download.values():
        _remover_diretorio_temporario(tarefa_download.diretorio_tarefa)


app = FastAPI(
    title="Sapo Downloader API", version="0.1.0", lifespan=gerenciar_ciclo_vida, docs_url=None, redoc_url=None
)
app.add_middleware(LimiteCorpoApiMiddleware)


@app.middleware("http")
async def adicionar_cabecalhos_seguranca(requisicao: Request, call_next):
    resposta = await call_next(requisicao)
    resposta.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: https://i.ytimg.com https://img.youtube.com; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )
    resposta.headers["Referrer-Policy"] = "no-referrer"
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    resposta.headers["X-Frame-Options"] = "DENY"
    resposta.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=()"
    return resposta


@app.get("/api/health")
async def verificar_saude() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/media/analyze", response_model=PreviaMidia)
async def analisar(requisicao: Request, solicitacao: SolicitacaoAnalise) -> PreviaMidia:
    _validar_limite_requisicoes(requisicao, "analyze")
    video_id, url_video = normalizar_url_youtube(solicitacao.url)
    try:
        async with vagas_analise:
            metadados_video = await servico_ytdlp.analisar(url_video)
    except ErroYtDlp as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from erro
    return _montar_previa_midia(
        video_id,
        metadados_video,
        configuracoes.duracao_maxima_midia_segundos,
        configuracoes.tamanho_maximo_download_bytes,
    )


async def _processar_download(
    tarefa_download: TarefaDownload, solicitacao: SolicitacaoDownload, url_video: str
) -> None:
    async with vagas_download:
        tarefa_download.situacao = "processing"
        tarefa_download.progresso = None
        tarefa_download.mensagem = "Verificando disponibilidade do formato."
        try:
            metadados_video = await servico_ytdlp.analisar(url_video)
            previa_video = _montar_previa_midia(
                solicitacao.video_id,
                metadados_video,
                configuracoes.duracao_maxima_midia_segundos,
                configuracoes.tamanho_maximo_download_bytes,
            )
            formato_selecionado = next(
                (
                    opcao_formato
                    for opcao_formato in previa_video.formats
                    if opcao_formato.format_id == solicitacao.format_id
                ),
                None,
            )
            if formato_selecionado is None:
                raise ErroYtDlp("O formato selecionado não está mais disponível.")

            tarefa_download.mensagem = "Preparando o arquivo."

            def atualizar_progresso(bytes_baixados: int, bytes_totais: int | None) -> None:
                tarefa_download.progresso = (
                    min(bytes_baixados / bytes_totais * 100, 99.0) if bytes_totais else None
                )
                tarefa_download.mensagem = "Baixando o arquivo autorizado."

            tarefa_download.caminho_arquivo = await servico_ytdlp.baixar(
                url_video,
                formato_selecionado.format_id,
                tarefa_download.diretorio_tarefa,
                atualizar_progresso,
                formato_selecionado.ext,
            )
            tarefa_download.situacao = "completed"
            tarefa_download.progresso = 100
            tarefa_download.mensagem = "Arquivo pronto para baixar."
        except (ErroYtDlp, HTTPException) as erro:
            tarefa_download.situacao = "failed"
            tarefa_download.mensagem = erro.detail if isinstance(erro, HTTPException) else str(erro)
            _remover_diretorio_temporario(tarefa_download.diretorio_tarefa)
        except asyncio.CancelledError:
            tarefa_download.situacao = "failed"
            tarefa_download.mensagem = "O processamento foi interrompido."
            _remover_diretorio_temporario(tarefa_download.diretorio_tarefa)
            raise
        except Exception:
            registrador.exception("Falha inesperada ao processar download")
            tarefa_download.situacao = "failed"
            tarefa_download.mensagem = "Ocorreu uma falha inesperada durante o processamento."
            _remover_diretorio_temporario(tarefa_download.diretorio_tarefa)


@app.post("/api/downloads", response_model=DownloadAceito, status_code=202)
async def criar_download(requisicao: Request, solicitacao: SolicitacaoDownload) -> DownloadAceito:
    _validar_limite_requisicoes(requisicao, "download")
    if not solicitacao.authorized:
        raise HTTPException(status_code=400, detail="Confirme que tem autorização para baixar esta mídia.")
    async with bloqueio_tarefas:
        quantidade_tarefas_ativas = sum(
            tarefa_download.situacao in {"queued", "processing"}
            for tarefa_download in tarefas_download.values()
        )
        quantidade_arquivos_prontos = sum(
            tarefa_download.situacao == "completed" for tarefa_download in tarefas_download.values()
        )
        if quantidade_tarefas_ativas >= configuracoes.limite_downloads_simultaneos:
            raise HTTPException(
                status_code=429, detail="Já existe um processamento em andamento. Tente novamente em breve."
            )
        if quantidade_arquivos_prontos >= configuracoes.limite_arquivos_prontos:
            raise HTTPException(
                status_code=429,
                detail="Baixe o arquivo pronto antes de iniciar outro processamento.",
            )
        download_id = uuid.uuid4().hex
        diretorio_tarefa = configuracoes.diretorio_temporario / download_id
        diretorio_tarefa.mkdir(mode=0o700, parents=True, exist_ok=False)
        tarefa_download = TarefaDownload(download_id=download_id, diretorio_tarefa=diretorio_tarefa)
        tarefas_download[download_id] = tarefa_download
        url_video = f"https://www.youtube.com/watch?v={solicitacao.video_id}"
        tarefa_download.tarefa_async = asyncio.create_task(
            _processar_download(tarefa_download, solicitacao, url_video)
        )
    return DownloadAceito(download_id=download_id, status="queued")


@app.get("/api/downloads/{download_id}", response_model=StatusDownload)
async def consultar_status_download(download_id: str) -> StatusDownload:
    tarefa_download = tarefas_download.get(download_id)
    if tarefa_download is None:
        raise HTTPException(status_code=404, detail="Este processamento não existe ou expirou.")
    return StatusDownload(
        download_id=tarefa_download.download_id,
        status=tarefa_download.situacao,
        progress=tarefa_download.progresso,
        message=tarefa_download.mensagem,
        download_url=f"/api/downloads/{tarefa_download.download_id}/file"
        if tarefa_download.situacao == "completed"
        else None,
    )


@app.delete("/api/downloads/{download_id}", status_code=204)
async def cancelar_download(download_id: str, requisicao: Request) -> Response:
    _validar_limite_requisicoes(requisicao, "cancel")
    async with bloqueio_tarefas:
        tarefa_download = tarefas_download.get(download_id)
        if tarefa_download is None:
            raise HTTPException(status_code=404, detail="Este processamento não existe ou expirou.")
        if tarefa_download.arquivo_em_transferencia:
            raise HTTPException(status_code=409, detail="O arquivo já está sendo transferido.")
        tarefa_async = tarefa_download.tarefa_async
        if tarefa_async is not None and not tarefa_async.done():
            tarefa_async.cancel()

    if tarefa_async is not None and not tarefa_async.done():
        with suppress(asyncio.CancelledError):
            await tarefa_async
    await _finalizar_transferencia_arquivo(download_id)
    return Response(status_code=204)


async def _finalizar_transferencia_arquivo(download_id: str) -> None:
    async with bloqueio_tarefas:
        tarefa_download = tarefas_download.pop(download_id, None)
        if tarefa_download:
            tarefa_download.situacao = "expired"
    if tarefa_download:
        _remover_diretorio_temporario(tarefa_download.diretorio_tarefa)


@app.get("/api/downloads/{download_id}/file")
async def entregar_arquivo_download(download_id: str) -> FileResponse:
    tarefa_download = tarefas_download.get(download_id)
    if (
        tarefa_download is None
        or tarefa_download.situacao != "completed"
        or tarefa_download.caminho_arquivo is None
    ):
        raise HTTPException(status_code=409, detail="O arquivo ainda não está pronto ou expirou.")
    async with bloqueio_tarefas:
        if tarefa_download.arquivo_em_transferencia:
            raise HTTPException(status_code=409, detail="Este arquivo já está sendo transferido.")
        tarefa_download.arquivo_em_transferencia = True
    nome_arquivo = f"sapo-{tarefa_download.caminho_arquivo.name}"
    return FileResponse(
        tarefa_download.caminho_arquivo,
        filename=nome_arquivo,
        media_type="application/octet-stream",
        background=BackgroundTask(_finalizar_transferencia_arquivo, download_id),
    )


if configuracoes.diretorio_build_frontend.is_dir():
    app.mount("/", StaticFiles(directory=configuracoes.diretorio_build_frontend, html=True), name="frontend")
