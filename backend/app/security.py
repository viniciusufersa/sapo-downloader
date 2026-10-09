import re
from urllib.parse import parse_qs, urlsplit

from fastapi import HTTPException

PADRAO_ID_VIDEO = re.compile(r"^[A-Za-z0-9_-]{11}$")
DOMINIOS_PERMITIDOS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


def normalizar_url_youtube(url_informada: str) -> tuple[str, str]:
    try:
        url_analisada = urlsplit(url_informada.strip())
        dominio = (url_analisada.hostname or "").lower().rstrip(".")
        if (
            url_analisada.scheme.lower() != "https"
            or dominio not in DOMINIOS_PERMITIDOS
            or url_analisada.username is not None
            or url_analisada.password is not None
            or url_analisada.port not in (None, 443)
            or "list" in parse_qs(url_analisada.query)
        ):
            raise ValueError

        if dominio == "youtu.be":
            partes_caminho = url_analisada.path.strip("/").split("/")
            if len(partes_caminho) != 1:
                raise ValueError
            id_video = partes_caminho[0]
        elif url_analisada.path == "/watch":
            id_video = parse_qs(url_analisada.query).get("v", [""])[0]
        elif url_analisada.path.startswith(("/shorts/", "/embed/")):
            id_video = url_analisada.path.split("/", 2)[2].split("/", 1)[0]
        else:
            raise ValueError

        if not PADRAO_ID_VIDEO.fullmatch(id_video):
            raise ValueError
    except (ValueError, IndexError):
        raise HTTPException(status_code=422, detail="Informe um link válido de vídeo do YouTube.") from None

    return id_video, f"https://www.youtube.com/watch?v={id_video}"
