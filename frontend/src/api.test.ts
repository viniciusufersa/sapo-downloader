import { describe, expect, it, vi } from "vitest";
import {
  analisarMidia,
  cancelarDownload,
  consultarDownload,
  criarDownload,
  ErroApi,
} from "./api";

const previaValida = {
  video_id: "abcdefghijk",
  title: "Vídeo autorizado",
  thumbnail: "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg",
  duration_seconds: 120,
  formats: [
    {
      format_id: "18",
      label: "360p · MP4",
      ext: "mp4",
      height: 360,
      filesize: 1024,
    },
  ],
};

describe("contratos da API", () => {
  it("deve retornar prévia válida quando a API responder com contrato compatível", async () => {
    const requisicao = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(previaValida), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(
      analisarMidia("https://youtu.be/abcdefghijk"),
    ).resolves.toEqual(previaValida);
    expect(requisicao).toHaveBeenCalledWith(
      "/api/media/analyze",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ url: "https://youtu.be/abcdefghijk" }),
      }),
    );
  });

  it("deve rejeitar resposta de análise incompatível mesmo com HTTP 200", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ video_id: "invalido" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(analisarMidia("https://youtu.be/abcdefghijk")).rejects.toThrow(
      "dados incompatíveis",
    );
  });

  it("deve aceitar identificadores de pares de faixas e rejeitar texto arbitrário", async () => {
    const respostaValida = structuredClone(previaValida);
    respostaValida.formats.push({
      format_id: "137+140",
      label: "1080p · MP4",
      ext: "mp4",
      height: 1080,
      filesize: 4096,
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(respostaValida), { status: 200 }),
    );

    await expect(
      analisarMidia("https://youtu.be/abcdefghijk"),
    ).resolves.toEqual(respostaValida);

    respostaValida.formats[1].format_id = "137+140;--exec=calc";
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(respostaValida), { status: 200 }),
    );
    await expect(analisarMidia("https://youtu.be/abcdefghijk")).rejects.toThrow(
      "dados incompatíveis",
    );
  });

  it("deve rejeitar resposta sem JSON válido", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("resposta inesperada", { status: 200 }),
    );

    await expect(analisarMidia("https://youtu.be/abcdefghijk")).rejects.toThrow(
      "resposta inválida",
    );
  });

  it("deve preservar o erro HTTP informado pela API", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Informe um link válido." }), {
        status: 422,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(analisarMidia("https://example.com")).rejects.toMatchObject({
      message: "Informe um link válido.",
      status: 422,
    });
  });

  it("deve propagar falha de conexão sem converter a resposta em sucesso", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(
      new TypeError("Falha de conexão"),
    );

    await expect(analisarMidia("https://youtu.be/abcdefghijk")).rejects.toThrow(
      "Falha de conexão",
    );
  });

  it("deve validar o estado e o endereço de arquivo durante o polling", async () => {
    const statusValido = {
      download_id: "download-123",
      status: "completed",
      progress: 100,
      message: "Arquivo pronto para baixar.",
      download_url: "/api/downloads/download-123/file",
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(statusValido), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(consultarDownload("download-123")).resolves.toEqual(
      statusValido,
    );
  });

  it("deve rejeitar progresso fora do intervalo permitido", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          download_id: "download-123",
          status: "processing",
          progress: 101,
          message: "Baixando",
          download_url: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    await expect(consultarDownload("download-123")).rejects.toBeInstanceOf(
      ErroApi,
    );
  });

  it("deve exigir contrato de aceitação ao iniciar um download", async () => {
    const requisicao = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(
          JSON.stringify({ download_id: "download-123", status: "processing" }),
          { status: 202, headers: { "Content-Type": "application/json" } },
        ),
      );

    await expect(criarDownload("abcdefghijk", "18")).rejects.toThrow(
      "dados incompatíveis",
    );
    expect(requisicao).toHaveBeenCalledWith(
      "/api/downloads",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          video_id: "abcdefghijk",
          format_id: "18",
          authorized: true,
        }),
      }),
    );
  });

  it("deve aceitar cancelamento sem conteúdo quando a API responder 204", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 }),
    );

    await expect(cancelarDownload("download-123")).resolves.toBeUndefined();
  });
});
