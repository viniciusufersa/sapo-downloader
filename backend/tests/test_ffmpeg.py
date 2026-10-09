import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import carregar_configuracoes
from app.ytdlp import ErroYtDlp, ServicoYtDlp


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg e ffprobe são necessários para o teste de integração local",
)
def test_deve_remuxar_faixas_locais_sem_recodificar_quando_codecs_fore_compativeis(
    tmp_path: Path,
) -> None:
    caminho_video = tmp_path / "video.mp4"
    caminho_audio = tmp_path / "audio.aac"
    caminho_saida = tmp_path / "resultado.mp4"

    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=160x90:rate=25",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(caminho_video),
        ],
        check=True,
        timeout=30,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=2",
            "-vn",
            "-c:a",
            "aac",
            str(caminho_audio),
        ],
        check=True,
        timeout=30,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(caminho_video),
            "-i",
            str(caminho_audio),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(caminho_saida),
        ],
        check=True,
        timeout=30,
    )

    resultado_probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=format_name:stream=codec_type,codec_name",
            "-of",
            "json",
            str(caminho_saida),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    metadados = json.loads(resultado_probe.stdout)

    assert caminho_saida.is_file()
    assert caminho_saida.stat().st_size > 0
    assert "mp4" in metadados["format"]["format_name"]
    assert {faixa["codec_type"] for faixa in metadados["streams"]} == {"video", "audio"}
    assert {faixa["codec_name"] for faixa in metadados["streams"]} == {"h264", "aac"}
    servico = ServicoYtDlp(carregar_configuracoes())
    asyncio.run(servico._validar_midia(caminho_saida, "mp4"))

    caminho_extensao_incompativel = tmp_path / "resultado.webm"
    shutil.copyfile(caminho_saida, caminho_extensao_incompativel)
    with pytest.raises(ErroYtDlp, match="contêiner ou os codecs"):
        asyncio.run(servico._validar_midia(caminho_extensao_incompativel, "webm"))
