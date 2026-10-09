from typing import Literal

from pydantic import BaseModel, Field


class SolicitacaoAnalise(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class OpcaoFormato(BaseModel):
    format_id: str
    label: str
    ext: str
    height: int | None
    filesize: int | None


class PreviaMidia(BaseModel):
    video_id: str
    title: str
    thumbnail: str | None
    duration_seconds: int
    formats: list[OpcaoFormato]


class SolicitacaoDownload(BaseModel):
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    format_id: str = Field(
        min_length=1,
        max_length=161,
        pattern=r"^[A-Za-z0-9._-]{1,80}(?:\+[A-Za-z0-9._-]{1,80})?$",
    )
    authorized: bool


class DownloadAceito(BaseModel):
    download_id: str
    status: Literal["queued"]


class StatusDownload(BaseModel):
    download_id: str
    status: Literal["queued", "processing", "completed", "failed", "expired"]
    progress: float | None
    message: str
    download_url: str | None
