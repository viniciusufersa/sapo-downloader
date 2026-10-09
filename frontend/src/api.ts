export type OpcaoFormato = {
  format_id: string;
  label: string;
  ext: "mp4" | "webm";
  height: number | null;
  filesize: number | null;
};

export type PreviaVideo = {
  video_id: string;
  title: string;
  thumbnail: string | null;
  duration_seconds: number;
  formats: OpcaoFormato[];
};

export type SituacaoDownload =
  "queued" | "processing" | "completed" | "failed" | "expired";

export type StatusDownload = {
  download_id: string;
  status: SituacaoDownload;
  progress: number | null;
  message: string;
  download_url: string | null;
};

type DownloadAceito = {
  download_id: string;
  status: "queued";
};

type Validador<T> = (valor: unknown) => valor is T;

export class ErroApi extends Error {
  constructor(
    mensagem: string,
    readonly status: number,
  ) {
    super(mensagem);
    this.name = "ErroApi";
  }
}

function ehRegistro(valor: unknown): valor is Record<string, unknown> {
  return typeof valor === "object" && valor !== null && !Array.isArray(valor);
}

function ehTexto(valor: unknown): valor is string {
  return typeof valor === "string";
}

function ehNumeroNaoNegativo(valor: unknown): valor is number {
  return typeof valor === "number" && Number.isFinite(valor) && valor >= 0;
}

function ehInteiroNaoNegativo(valor: unknown): valor is number {
  return ehNumeroNaoNegativo(valor) && Number.isInteger(valor);
}

function ehNumeroOuNulo(valor: unknown): valor is number | null {
  return valor === null || ehNumeroNaoNegativo(valor);
}

function ehInteiroOuNulo(valor: unknown): valor is number | null {
  return valor === null || ehInteiroNaoNegativo(valor);
}

function ehSituacaoDownload(valor: unknown): valor is SituacaoDownload {
  return (
    valor === "queued" ||
    valor === "processing" ||
    valor === "completed" ||
    valor === "failed" ||
    valor === "expired"
  );
}

function ehThumbnailPermitida(valor: unknown): valor is string | null {
  if (valor === null) return true;
  if (!ehTexto(valor)) return false;

  try {
    const urlThumbnail = new URL(valor);
    return (
      urlThumbnail.protocol === "https:" &&
      ["i.ytimg.com", "img.youtube.com"].includes(urlThumbnail.hostname)
    );
  } catch {
    return false;
  }
}

function ehOpcaoFormato(valor: unknown): valor is OpcaoFormato {
  return (
    ehRegistro(valor) &&
    ehTexto(valor.format_id) &&
    /^[A-Za-z0-9._-]{1,80}(?:\+[A-Za-z0-9._-]{1,80})?$/.test(valor.format_id) &&
    ehTexto(valor.label) &&
    (valor.ext === "mp4" || valor.ext === "webm") &&
    ehInteiroOuNulo(valor.height) &&
    ehInteiroOuNulo(valor.filesize)
  );
}

function ehPreviaVideo(valor: unknown): valor is PreviaVideo {
  return (
    ehRegistro(valor) &&
    ehTexto(valor.video_id) &&
    /^[A-Za-z0-9_-]{11}$/.test(valor.video_id) &&
    ehTexto(valor.title) &&
    ehThumbnailPermitida(valor.thumbnail) &&
    ehInteiroNaoNegativo(valor.duration_seconds) &&
    valor.duration_seconds > 0 &&
    Array.isArray(valor.formats) &&
    valor.formats.length > 0 &&
    valor.formats.every(ehOpcaoFormato)
  );
}

function ehDownloadAceito(valor: unknown): valor is DownloadAceito {
  return (
    ehRegistro(valor) &&
    ehTexto(valor.download_id) &&
    valor.download_id.length > 0 &&
    valor.status === "queued"
  );
}

function ehStatusDownload(valor: unknown): valor is StatusDownload {
  return (
    ehRegistro(valor) &&
    ehTexto(valor.download_id) &&
    valor.download_id.length > 0 &&
    ehSituacaoDownload(valor.status) &&
    ehNumeroOuNulo(valor.progress) &&
    (valor.progress === null || valor.progress <= 100) &&
    ehTexto(valor.message) &&
    (valor.download_url === null ||
      (ehTexto(valor.download_url) &&
        /^\/api\/downloads\/[A-Za-z0-9_-]+\/file$/.test(valor.download_url)))
  );
}

function extrairMensagemErro(valor: unknown): string | null {
  if (!ehRegistro(valor) || !ehTexto(valor.detail)) return null;
  return valor.detail;
}

async function solicitarJson<T>(
  caminho: string,
  opcoes: RequestInit,
  validar: Validador<T>,
): Promise<T> {
  const respostaHttp = await fetch(caminho, {
    ...opcoes,
    headers: {
      ...(opcoes.body ? { "Content-Type": "application/json" } : {}),
      ...opcoes.headers,
    },
  });

  let resposta: unknown;
  try {
    resposta = await respostaHttp.json();
  } catch {
    throw new ErroApi(
      respostaHttp.ok
        ? "O servidor retornou uma resposta inválida. Tente novamente."
        : "Não foi possível concluir a solicitação. Tente novamente.",
      respostaHttp.status,
    );
  }

  if (!respostaHttp.ok) {
    throw new ErroApi(
      extrairMensagemErro(resposta) ??
        "Não foi possível concluir a solicitação. Tente novamente.",
      respostaHttp.status,
    );
  }

  if (!validar(resposta)) {
    throw new ErroApi(
      "O servidor retornou dados incompatíveis com a aplicação.",
      respostaHttp.status,
    );
  }

  return resposta;
}

export function analisarMidia(url: string): Promise<PreviaVideo> {
  return solicitarJson(
    "/api/media/analyze",
    { method: "POST", body: JSON.stringify({ url }) },
    ehPreviaVideo,
  );
}

export function criarDownload(
  videoId: string,
  idFormato: string,
): Promise<DownloadAceito> {
  return solicitarJson(
    "/api/downloads",
    {
      method: "POST",
      body: JSON.stringify({
        video_id: videoId,
        format_id: idFormato,
        authorized: true,
      }),
    },
    ehDownloadAceito,
  );
}

export function consultarDownload(downloadId: string): Promise<StatusDownload> {
  return solicitarJson(
    `/api/downloads/${encodeURIComponent(downloadId)}`,
    {},
    ehStatusDownload,
  );
}

export async function cancelarDownload(downloadId: string): Promise<void> {
  const respostaHttp = await fetch(
    `/api/downloads/${encodeURIComponent(downloadId)}`,
    { method: "DELETE" },
  );

  if (respostaHttp.ok && respostaHttp.status === 204) return;

  let resposta: unknown;
  try {
    resposta = await respostaHttp.json();
  } catch {
    resposta = null;
  }

  throw new ErroApi(
    extrairMensagemErro(resposta) ??
      "Não foi possível remover o arquivo temporário.",
    respostaHttp.status,
  );
}
