import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import SapoDownloader from "./App";

describe("Sapo Downloader", () => {
  it("exibe a assinatura com um ícone de coração no rodapé", () => {
    render(<SapoDownloader />);

    expect(screen.getByText(/Feito com.*Vinícius/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "coração" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Termos do YouTube/ }),
    ).toBeInTheDocument();
  });

  it("exibe os detalhes de um link válido e exige autorização antes do download", async () => {
    const requisicaoApiEspionada = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(
          JSON.stringify({
            video_id: "abcdefghijk",
            title: "Vídeo de teste",
            thumbnail: null,
            duration_seconds: 120,
            formats: [
              {
                format_id: "18",
                label: "360p · MP4",
                ext: "mp4",
                height: 360,
                filesize: 1000,
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    render(<SapoDownloader />);
    fireEvent.change(screen.getByLabelText("Link do vídeo"), {
      target: { value: "https://youtu.be/abcdefghijk" },
    });
    fireEvent.click(screen.getByRole("button", { name: /analisar link/i }));
    expect(await screen.findByText("Vídeo de teste")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /baixar arquivo/i }),
    ).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/confirmo que tenho autorização/i));
    expect(
      screen.getByRole("button", { name: /baixar arquivo/i }),
    ).toBeEnabled();
    expect(requisicaoApiEspionada).toHaveBeenCalledWith(
      "/api/media/analyze",
      expect.any(Object),
    );
  });

  it("exibe uma mensagem clara quando a análise falha", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Informe um link válido." }), {
        status: 422,
        headers: { "Content-Type": "application/json" },
      }),
    );
    render(<SapoDownloader />);
    fireEvent.change(screen.getByLabelText("Link do vídeo"), {
      target: { value: "https://example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /analisar link/i }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Informe um link válido.",
      ),
    );
  });

  it("inicia o download no formato escolhido após a autorização", async () => {
    const requisicaoApiEspionada = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            video_id: "abcdefghijk",
            title: "Vídeo autorizado",
            thumbnail: null,
            duration_seconds: 120,
            formats: [
              {
                format_id: "18",
                label: "360p · MP4",
                ext: "mp4",
                height: 360,
                filesize: 1000,
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ download_id: "download-123", status: "queued" }),
          { status: 202, headers: { "Content-Type": "application/json" } },
        ),
      );

    render(<SapoDownloader />);
    fireEvent.change(screen.getByLabelText("Link do vídeo"), {
      target: { value: "https://youtu.be/abcdefghijk" },
    });
    fireEvent.click(screen.getByRole("button", { name: /analisar link/i }));
    expect(await screen.findByText("Vídeo autorizado")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/confirmo que tenho autorização/i));
    fireEvent.click(screen.getByRole("button", { name: /baixar arquivo/i }));

    await waitFor(() =>
      expect(requisicaoApiEspionada).toHaveBeenLastCalledWith(
        "/api/downloads",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            video_id: "abcdefghijk",
            format_id: "18",
            authorized: true,
          }),
        }),
      ),
    );
    expect(
      await screen.findByText("Aguardando processamento."),
    ).toBeInTheDocument();
  });

  it("atualiza o estado quando o polling recebe um download concluído", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            video_id: "abcdefghijk",
            title: "Vídeo autorizado",
            thumbnail: null,
            duration_seconds: 120,
            formats: [
              {
                format_id: "18",
                label: "360p · MP4",
                ext: "mp4",
                height: 360,
                filesize: 1000,
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ download_id: "download-123", status: "queued" }),
          { status: 202, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            download_id: "download-123",
            status: "completed",
            progress: 100,
            message: "Arquivo pronto para baixar.",
            download_url: "/api/downloads/download-123/file",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

    render(<SapoDownloader />);
    fireEvent.change(screen.getByLabelText("Link do vídeo"), {
      target: { value: "https://youtu.be/abcdefghijk" },
    });
    fireEvent.click(screen.getByRole("button", { name: /analisar link/i }));
    expect(await screen.findByText("Vídeo autorizado")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/confirmo que tenho autorização/i));
    fireEvent.click(screen.getByRole("button", { name: /baixar arquivo/i }));

    expect(
      await screen.findByRole(
        "link",
        { name: /baixar arquivo/i },
        { timeout: 5000 },
      ),
    ).toHaveAttribute("href", "/api/downloads/download-123/file");
  });

  it("permite cancelar o processamento e encerra o estado ativo", async () => {
    const requisicao = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            video_id: "abcdefghijk",
            title: "Vídeo autorizado",
            thumbnail: null,
            duration_seconds: 120,
            formats: [
              {
                format_id: "18",
                label: "360p · MP4",
                ext: "mp4",
                height: 360,
                filesize: 1000,
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ download_id: "download-123", status: "queued" }),
          { status: 202, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    render(<SapoDownloader />);
    fireEvent.change(screen.getByLabelText("Link do vídeo"), {
      target: { value: "https://youtu.be/abcdefghijk" },
    });
    fireEvent.click(screen.getByRole("button", { name: /analisar link/i }));
    expect(await screen.findByText("Vídeo autorizado")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/confirmo que tenho autorização/i));
    fireEvent.click(screen.getByRole("button", { name: /baixar arquivo/i }));
    fireEvent.click(
      await screen.findByRole("button", { name: /cancelar processamento/i }),
    );

    expect(
      await screen.findByText(
        "Processamento cancelado e arquivo temporário removido.",
      ),
    ).toBeInTheDocument();
    expect(requisicao).toHaveBeenLastCalledWith("/api/downloads/download-123", {
      method: "DELETE",
    });
  });

  it("bloqueia uma segunda submissão enquanto o download está sendo criado", async () => {
    let concluirCriacao!: (resposta: Response) => void;
    const respostaPendente = new Promise<Response>((resolver) => {
      concluirCriacao = resolver;
    });
    const requisicao = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            video_id: "abcdefghijk",
            title: "Vídeo autorizado",
            thumbnail: null,
            duration_seconds: 120,
            formats: [
              {
                format_id: "18",
                label: "360p · MP4",
                ext: "mp4",
                height: 360,
                filesize: 1000,
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockReturnValueOnce(respostaPendente);

    render(<SapoDownloader />);
    fireEvent.change(screen.getByLabelText("Link do vídeo"), {
      target: { value: "https://youtu.be/abcdefghijk" },
    });
    fireEvent.click(screen.getByRole("button", { name: /analisar link/i }));
    expect(await screen.findByText("Vídeo autorizado")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/confirmo que tenho autorização/i));
    const botaoDownload = screen.getByRole("button", {
      name: /baixar arquivo/i,
    });
    fireEvent.click(botaoDownload);
    expect(botaoDownload).toBeDisabled();
    fireEvent.click(botaoDownload);
    expect(requisicao).toHaveBeenCalledTimes(2);

    concluirCriacao(
      new Response(
        JSON.stringify({ download_id: "download-123", status: "queued" }),
        { status: 202, headers: { "Content-Type": "application/json" } },
      ),
    );
    expect(
      await screen.findByText("Aguardando processamento."),
    ).toBeInTheDocument();
  });
});
