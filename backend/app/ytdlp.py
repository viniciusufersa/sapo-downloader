import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict

from .config import Configuracoes

PADRAO_PROGRESSO = re.compile(r"SAPO_PROGRESS:([A-Za-z0-9._+-]+):(\d+):(?:(\d+)|NA):(?:(\d+)|NA)")
PADRAO_ID_FORMATO = re.compile(r"^[A-Za-z0-9._-]{1,80}(?:\+[A-Za-z0-9._-]{1,80})?$")
FATOR_RESERVA_DISCO = 3


class OpcoesGrupoProcesso(TypedDict, total=False):
    creationflags: int
    start_new_session: bool


class ErroYtDlp(Exception):
    pass


class ServicoYtDlp:
    def __init__(self, configuracoes: Configuracoes) -> None:
        self.configuracoes = configuracoes

    def _criar_ambiente(self, diretorio_tarefa: Path | None = None) -> dict[str, str]:
        ambiente = {
            nome_variavel: valor
            for nome_variavel, valor in os.environ.items()
            if nome_variavel.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
        }
        ambiente["PYTHONUTF8"] = "1"
        ambiente["PYTHONDONTWRITEBYTECODE"] = "1"
        if diretorio_tarefa is not None:
            ambiente["HOME"] = str(diretorio_tarefa)
            ambiente["USERPROFILE"] = str(diretorio_tarefa)
        return ambiente

    @staticmethod
    def _opcoes_grupo_processo() -> OpcoesGrupoProcesso:
        if os.name == "nt":
            return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        return {"start_new_session": True}

    @staticmethod
    async def _encerrar_processo(processo: asyncio.subprocess.Process) -> None:
        if processo.returncode is not None:
            return
        if os.name == "nt":
            try:
                processo_taskkill = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/PID",
                    str(processo.pid),
                    "/T",
                    "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(processo_taskkill.wait(), timeout=5)
                if processo_taskkill.returncode != 0 and processo.returncode is None:
                    processo.kill()
            except (OSError, TimeoutError):
                processo.kill()
        else:
            encerrar_grupo = getattr(os, "killpg", None)
            sinal_encerramento = getattr(signal, "SIGKILL", None)
            if encerrar_grupo is None or sinal_encerramento is None:
                processo.kill()
                await processo.wait()
                return
            try:
                encerrar_grupo(processo.pid, sinal_encerramento)
            except ProcessLookupError:
                pass
        await processo.wait()

    async def _consultar_metadados(self, url_video: str) -> dict[str, Any]:
        comando = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--ignore-config",
            "--dump-single-json",
            "--no-warnings",
            "--no-playlist",
            "--no-call-home",
            "--no-cache-dir",
            "--no-remote-components",
            "--js-runtimes",
            "node",
            url_video,
        ]
        try:
            processo = await asyncio.create_subprocess_exec(
                *comando,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._criar_ambiente(),
                **self._opcoes_grupo_processo(),
            )
            saida_padrao, _ = await asyncio.wait_for(
                processo.communicate(),
                timeout=self.configuracoes.tempo_limite_requisicao_segundos,
            )
        except (TimeoutError, OSError, asyncio.CancelledError) as erro:
            if "processo" in locals() and processo.returncode is None:
                await self._encerrar_processo(processo)
            if isinstance(erro, asyncio.CancelledError):
                raise
            raise ErroYtDlp("Não foi possível analisar o vídeo agora.") from erro

        if processo.returncode != 0:
            raise ErroYtDlp("O vídeo está indisponível ou não pode ser analisado.")
        try:
            metadados_video = json.loads(saida_padrao)
        except (json.JSONDecodeError, UnicodeDecodeError) as erro:
            raise ErroYtDlp("O serviço retornou informações inválidas sobre o vídeo.") from erro
        if not isinstance(metadados_video, dict):
            raise ErroYtDlp("O serviço retornou informações inválidas sobre o vídeo.")
        return metadados_video

    async def analisar(self, url_video: str) -> dict[str, Any]:
        return await self._consultar_metadados(url_video)

    async def baixar(
        self,
        url_video: str,
        id_formato: str,
        diretorio_tarefa: Path,
        callback_progresso: Callable[[int, int | None], None],
        extensao_saida: str,
    ) -> Path:
        if not PADRAO_ID_FORMATO.fullmatch(id_formato):
            raise ErroYtDlp("Formato indisponível para este vídeo.")
        if extensao_saida not in {"mp4", "webm"}:
            raise ErroYtDlp("Formato indisponível para este vídeo.")
        try:
            espaco_disponivel = shutil.disk_usage(diretorio_tarefa).free
        except OSError as erro:
            raise ErroYtDlp("Não foi possível verificar o espaço disponível para o processamento.") from erro
        espaco_reservado = self.configuracoes.tamanho_maximo_download_bytes * FATOR_RESERVA_DISCO
        if espaco_disponivel < espaco_reservado:
            raise ErroYtDlp("Não há espaço livre suficiente para processar este vídeo com segurança.")
        formatos_selecionados = id_formato.split("+")
        comando = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--ignore-config",
            "--no-warnings",
            "--no-playlist",
            "--no-call-home",
            "--no-cache-dir",
            "--no-remote-components",
            "--js-runtimes",
            "node",
            "--format",
            id_formato,
            "--max-filesize",
            str(self.configuracoes.tamanho_maximo_download_bytes),
            "--output",
            str(diretorio_tarefa / "%(id)s.%(ext)s"),
            "--newline",
            "--progress-template",
            "download:SAPO_PROGRESS:%(info.format_id)s:%(progress.downloaded_bytes)s:%(progress.total_bytes_estimate)s:%(progress.total_bytes)s",
            url_video,
        ]
        if "+" in id_formato:
            comando[comando.index("--max-filesize") : comando.index("--max-filesize")] = [
                "--merge-output-format",
                extensao_saida,
            ]
        try:
            processo = await asyncio.create_subprocess_exec(
                *comando,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=self._criar_ambiente(diretorio_tarefa),
                **self._opcoes_grupo_processo(),
            )
        except OSError as erro:
            raise ErroYtDlp("Não foi possível iniciar o processamento do vídeo.") from erro

        linhas_saida: list[str] = []
        progresso_por_formato: dict[str, tuple[int, int | None]] = {}
        if processo.stdout is None:
            await self._encerrar_processo(processo)
            raise ErroYtDlp("Não foi possível acompanhar o processamento do vídeo.")
        try:
            async with asyncio.timeout(self.configuracoes.tempo_limite_requisicao_segundos * 10):
                while linha := await processo.stdout.readline():
                    linha_decodificada = linha.decode("utf-8", errors="replace").strip()
                    correspondencia = PADRAO_PROGRESSO.search(linha_decodificada)
                    if correspondencia:
                        id_formato_atual = correspondencia.group(1)
                        bytes_atuais = int(correspondencia.group(2))
                        bytes_totais_atuais = (
                            int(correspondencia.group(4) or correspondencia.group(3))
                            if (correspondencia.group(3) or correspondencia.group(4))
                            else None
                        )
                        if id_formato_atual in formatos_selecionados:
                            progresso_por_formato[id_formato_atual] = (
                                bytes_atuais,
                                bytes_totais_atuais,
                            )
                        elif id_formato_atual == id_formato:
                            progresso_por_formato[id_formato_atual] = (
                                bytes_atuais,
                                bytes_totais_atuais,
                            )
                        else:
                            continue
                        bytes_baixados = sum(progresso[0] for progresso in progresso_por_formato.values())
                        tamanhos_totais = [progresso[1] for progresso in progresso_por_formato.values()]
                        bytes_totais = (
                            sum(tamanho for tamanho in tamanhos_totais if tamanho is not None)
                            if len(progresso_por_formato) == len(formatos_selecionados)
                            and all(tamanho is not None for tamanho in tamanhos_totais)
                            else None
                        )
                        if bytes_baixados > self.configuracoes.tamanho_maximo_download_bytes:
                            await self._encerrar_processo(processo)
                            raise ErroYtDlp("O arquivo excede o limite permitido de tamanho.")
                        callback_progresso(bytes_baixados, bytes_totais)
                    elif linha_decodificada and not linha_decodificada.startswith(("[debug]", "[youtube]")):
                        linhas_saida.append(linha_decodificada[-300:])
                        linhas_saida = linhas_saida[-8:]
                await processo.wait()
        except TimeoutError as erro:
            await self._encerrar_processo(processo)
            raise ErroYtDlp("O processamento excedeu o tempo permitido.") from erro
        except asyncio.CancelledError:
            await self._encerrar_processo(processo)
            raise

        if processo.returncode != 0:
            saida_compactada = " ".join(linhas_saida).lower()
            if "filesize" in saida_compactada or "file size" in saida_compactada:
                raise ErroYtDlp("O arquivo excede o limite permitido de tamanho.")
            if "requested format is not available" in saida_compactada:
                raise ErroYtDlp("O formato selecionado não está mais disponível.")
            raise ErroYtDlp("Não foi possível concluir o download autorizado.")

        arquivos_gerados = [
            caminho_arquivo
            for caminho_arquivo in diretorio_tarefa.iterdir()
            if caminho_arquivo.is_file() and not caminho_arquivo.name.endswith(".part")
        ]
        if (
            len(arquivos_gerados) != 1
            or arquivos_gerados[0].stat().st_size > self.configuracoes.tamanho_maximo_download_bytes
        ):
            raise ErroYtDlp("O arquivo gerado não passou pela verificação de tamanho.")
        arquivo_final = arquivos_gerados[0]
        await self._validar_midia(arquivo_final, extensao_saida)
        return arquivo_final

    async def _validar_midia(self, caminho_arquivo: Path, extensao_esperada: str) -> None:
        comando = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=format_name:stream=codec_type,codec_name",
            "-of",
            "json",
            str(caminho_arquivo),
        ]
        if extensao_esperada not in {"mp4", "webm"}:
            raise ErroYtDlp("O contêiner selecionado não é compatível.")
        try:
            processo = await asyncio.create_subprocess_exec(
                *comando,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._criar_ambiente(),
                **self._opcoes_grupo_processo(),
            )
            saida_padrao, _ = await asyncio.wait_for(
                processo.communicate(),
                timeout=self.configuracoes.tempo_limite_requisicao_segundos,
            )
        except FileNotFoundError as erro:
            raise ErroYtDlp("FFmpeg e ffprobe precisam estar instalados para validar a mídia.") from erro
        except (TimeoutError, OSError, asyncio.CancelledError) as erro:
            if "processo" in locals() and processo.returncode is None:
                await self._encerrar_processo(processo)
            if isinstance(erro, asyncio.CancelledError):
                raise
            raise ErroYtDlp("Não foi possível validar o arquivo de mídia gerado.") from erro

        if processo.returncode != 0:
            raise ErroYtDlp("O arquivo gerado não é uma mídia reproduzível.")
        try:
            metadados_midia = json.loads(saida_padrao)
        except (json.JSONDecodeError, UnicodeDecodeError) as erro:
            raise ErroYtDlp("O arquivo gerado retornou informações de mídia inválidas.") from erro

        if not isinstance(metadados_midia, dict):
            raise ErroYtDlp("O arquivo gerado retornou informações de mídia inválidas.")
        formatos = metadados_midia.get("format", {})
        nomes_formatos = formatos.get("format_name", "") if isinstance(formatos, dict) else ""
        extensao = caminho_arquivo.suffix.lower()
        contêiner_valido = extensao == f".{extensao_esperada}" and (
            extensao == ".mp4"
            and isinstance(nomes_formatos, str)
            and "mp4" in nomes_formatos
            or extensao == ".webm"
            and isinstance(nomes_formatos, str)
            and "webm" in nomes_formatos
        )
        faixas = metadados_midia.get("streams", [])
        if not isinstance(faixas, list):
            raise ErroYtDlp("O arquivo gerado retornou informações de mídia inválidas.")
        codecs_video = {
            str(faixa.get("codec_name", "")).lower()
            for faixa in faixas
            if isinstance(faixa, dict) and faixa.get("codec_type") == "video"
        }
        codecs_audio = {
            str(faixa.get("codec_name", "")).lower()
            for faixa in faixas
            if isinstance(faixa, dict) and faixa.get("codec_type") == "audio"
        }
        codecs_compativeis = (
            extensao == ".mp4" and bool(codecs_video & {"h264"}) and bool(codecs_audio & {"aac"})
        ) or (
            extensao == ".webm"
            and bool(codecs_video & {"vp8", "vp9", "av1"})
            and bool(codecs_audio & {"opus", "vorbis"})
        )
        if not contêiner_valido or not codecs_compativeis:
            raise ErroYtDlp("O contêiner ou os codecs do arquivo final não são compatíveis.")
