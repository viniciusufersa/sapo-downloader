import os
from dataclasses import dataclass
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parents[2]


def _ler_inteiro_positivo(nome_variavel: str, valor_padrao: int) -> int:
    try:
        valor = int(os.getenv(nome_variavel, str(valor_padrao)))
    except ValueError as erro:
        raise ValueError(f"{nome_variavel} deve ser um número inteiro") from erro
    if valor <= 0:
        raise ValueError(f"{nome_variavel} deve ser maior que zero")
    return valor


@dataclass(frozen=True)
class Configuracoes:
    limite_downloads_simultaneos: int
    limite_arquivos_prontos: int
    duracao_maxima_midia_segundos: int
    tamanho_maximo_download_bytes: int
    validade_temporario_segundos: int
    tempo_limite_requisicao_segundos: int
    diretorio_temporario: Path
    diretorio_build_frontend: Path


def carregar_configuracoes() -> Configuracoes:
    return Configuracoes(
        limite_downloads_simultaneos=_ler_inteiro_positivo("MAX_CONCURRENT_DOWNLOADS", 1),
        limite_arquivos_prontos=_ler_inteiro_positivo("MAX_STORED_DOWNLOADS", 1),
        duracao_maxima_midia_segundos=_ler_inteiro_positivo("MAX_MEDIA_DURATION_SECONDS", 1800),
        tamanho_maximo_download_bytes=_ler_inteiro_positivo("MAX_DOWNLOAD_SIZE_MB", 200) * 1024 * 1024,
        validade_temporario_segundos=_ler_inteiro_positivo("TEMP_FILE_TTL_MINUTES", 30) * 60,
        tempo_limite_requisicao_segundos=_ler_inteiro_positivo("REQUEST_TIMEOUT_SECONDS", 120),
        diretorio_temporario=Path(os.getenv("TEMP_DIR", str(RAIZ_PROJETO / ".tmp"))).resolve(),
        diretorio_build_frontend=Path(
            os.getenv("FRONTEND_DIST", str(RAIZ_PROJETO / "frontend" / "dist"))
        ).resolve(),
    )
