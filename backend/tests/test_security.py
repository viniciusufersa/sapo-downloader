import pytest
from fastapi import HTTPException

from app.main import _montar_previa_midia
from app.security import normalizar_url_youtube


@pytest.mark.parametrize(
    ("url", "id_esperado"),
    [
        ("https://www.youtube.com/watch?v=abcdefghijk", "abcdefghijk"),
        ("https://youtu.be/abcdefghijk", "abcdefghijk"),
        ("https://m.youtube.com/shorts/abcdefghijk", "abcdefghijk"),
        ("https://www.youtube.com/embed/abcdefghijk", "abcdefghijk"),
    ],
)
def test_deve_normalizar_urls_youtube_compativeis(url: str, id_esperado: str) -> None:
    video_id, url_normalizada = normalizar_url_youtube(url)
    assert video_id == id_esperado
    assert url_normalizada == f"https://www.youtube.com/watch?v={id_esperado}"


@pytest.mark.parametrize(
    "url",
    [
        "http://youtube.com/watch?v=abcdefghijk",
        "https://youtube.com.evil.example/watch?v=abcdefghijk",
        "https://youtube.com@evil.example/watch?v=abcdefghijk",
        "https://youtube.com:8443/watch?v=abcdefghijk",
        "https://www.youtube.com/watch?v=abcdefghijk&list=PL123",
        "https://youtu.be/abcdefghijk/extra",
        "https://example.com/watch?v=abcdefghijk",
    ],
)
def test_deve_rejeitar_urls_inseguras_ou_de_playlist_quando_destino_nao_for_permitido(url: str) -> None:
    with pytest.raises(HTTPException) as error:
        normalizar_url_youtube(url)
    assert error.value.status_code == 422


def test_deve_retornar_formatos_progressivos_e_pares_compativeis_quando_fluxos_estiverem_separados() -> None:
    metadados_video = {
        "id": "abcdefghijk",
        "title": "Vídeo autorizado",
        "duration": 240,
        "thumbnail": "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg",
        "formats": [
            {
                "format_id": "18",
                "ext": "mp4",
                "height": 360,
                "vcodec": "avc1",
                "acodec": "mp4a",
                "filesize": 20,
            },
            {
                "format_id": "137",
                "ext": "mp4",
                "height": 1080,
                "vcodec": "avc1",
                "acodec": "none",
                "filesize": 30,
            },
            {"format_id": "140", "ext": "m4a", "height": None, "vcodec": "none", "acodec": "mp4a"},
            {
                "format_id": "999",
                "ext": "mp4",
                "height": 720,
                "vcodec": "avc1",
                "acodec": "aac",
                "filesize": 300,
            },
        ],
    }
    previa = _montar_previa_midia("abcdefghijk", metadados_video, duracao_maxima=1800, tamanho_maximo=100)
    assert {opcao.format_id for opcao in previa.formats} == {"18", "137+140"}
    assert previa.title == "Vídeo autorizado"


def test_deve_rejeitar_metadados_quando_formatos_nao_for_lista() -> None:
    metadados_video = {
        "id": "abcdefghijk",
        "title": "Vídeo",
        "duration": 120,
        "formats": None,
    }

    with pytest.raises(HTTPException, match="Não há formatos"):
        _montar_previa_midia("abcdefghijk", metadados_video, duracao_maxima=1800, tamanho_maximo=1000)


@pytest.mark.parametrize(
    ("alteracoes", "mensagem_esperada"),
    [
        ({"is_live": True}, "disponível"),
        ({"duration": 1801}, "duração"),
        ({"id": "lmnopqrstuv"}, "corresponde"),
    ],
)
def test_deve_rejeitar_midia_quando_video_exceder_politica(alteracoes: dict, mensagem_esperada: str) -> None:
    metadados_video = {
        "id": "abcdefghijk",
        "title": "Vídeo",
        "duration": 120,
        "formats": [
            {"format_id": "18", "ext": "mp4", "height": 360, "vcodec": "avc1", "acodec": "mp4a"},
        ],
        **alteracoes,
    }
    with pytest.raises(HTTPException) as error:
        _montar_previa_midia("abcdefghijk", metadados_video, duracao_maxima=1800, tamanho_maximo=1000)
    assert mensagem_esperada in error.value.detail
