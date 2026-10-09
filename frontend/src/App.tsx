import { useEffect, useState, type FormEvent } from "react";
import {
  ArrowDownToLine,
  ArrowUpRight,
  Check,
  CircleAlert,
  Link2,
  LoaderCircle,
  ShieldCheck,
  X,
} from "lucide-react";
import DownloadStatus from "./DownloadStatus";
import {
  analisarMidia,
  cancelarDownload as cancelarDownloadApi,
  consultarDownload,
  criarDownload,
  ErroApi,
  type PreviaVideo,
  type StatusDownload,
} from "./api";

function formatarDuracao(segundos: number): string {
  const minutos = Math.floor(segundos / 60);
  const segundosRestantes = segundos % 60;
  return `${minutos}:${String(segundosRestantes).padStart(2, "0")} min`;
}

function formatarTamanho(tamanhoBytes: number | null): string {
  if (!tamanhoBytes) return "Tamanho variável";
  return `${(tamanhoBytes / (1024 * 1024)).toFixed(0)} MB`;
}

export default function SapoDownloader() {
  const [urlVideo, setUrlVideo] = useState("");
  const [previa, setPrevia] = useState<PreviaVideo | null>(null);
  const [formatoSelecionado, setFormatoSelecionado] = useState("");
  const [temAutorizacao, setTemAutorizacao] = useState(false);
  const [estaCarregando, setEstaCarregando] = useState(false);
  const [estaCancelando, setEstaCancelando] = useState(false);
  const [erro, setErro] = useState("");
  const [statusDownload, setStatusDownload] = useState<StatusDownload | null>(
    null,
  );
  const [transferenciaIniciada, setTransferenciaIniciada] = useState(false);

  useEffect(() => {
    if (
      !statusDownload ||
      (!["queued", "processing"].includes(statusDownload.status) &&
        !(statusDownload.status === "completed" && transferenciaIniciada))
    )
      return;
    let consultaAtiva = true;
    const temporizadorConsulta = window.setTimeout(async () => {
      try {
        const novoStatus = await consultarDownload(statusDownload.download_id);
        if (consultaAtiva) setStatusDownload(novoStatus);
      } catch (falhaCapturada) {
        if (
          consultaAtiva &&
          falhaCapturada instanceof ErroApi &&
          falhaCapturada.status === 404
        ) {
          setStatusDownload({
            ...statusDownload,
            status: "expired",
            progress: null,
            message: "Arquivo transferido e removido.",
            download_url: null,
          });
          setTransferenciaIniciada(false);
          return;
        }
        if (consultaAtiva)
          setErro(
            falhaCapturada instanceof Error
              ? falhaCapturada.message
              : "Falha ao consultar o processamento.",
          );
      }
    }, 1100);
    return () => {
      consultaAtiva = false;
      window.clearTimeout(temporizadorConsulta);
    };
  }, [statusDownload, transferenciaIniciada]);

  async function analisarVideo(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault();
    setEstaCarregando(true);
    setErro("");
    setPrevia(null);
    setStatusDownload(null);
    setTransferenciaIniciada(false);
    setTemAutorizacao(false);
    try {
      const previaRecebida = await analisarMidia(urlVideo);
      setPrevia(previaRecebida);
      setFormatoSelecionado(previaRecebida.formats[0]?.format_id ?? "");
    } catch (falhaCapturada) {
      setErro(
        falhaCapturada instanceof Error
          ? falhaCapturada.message
          : "Não foi possível analisar este link.",
      );
    } finally {
      setEstaCarregando(false);
    }
  }

  async function iniciarDownload() {
    if (!previa || !formatoSelecionado || !temAutorizacao) return;
    setEstaCarregando(true);
    setErro("");
    try {
      const downloadAceito = await criarDownload(
        previa.video_id,
        formatoSelecionado,
      );
      setStatusDownload({
        download_id: downloadAceito.download_id,
        status: downloadAceito.status,
        progress: null,
        message: "Aguardando processamento.",
        download_url: null,
      });
    } catch (falhaCapturada) {
      setErro(
        falhaCapturada instanceof Error
          ? falhaCapturada.message
          : "Não foi possível iniciar o download.",
      );
    } finally {
      setEstaCarregando(false);
    }
  }

  async function cancelarDownload() {
    if (!statusDownload) return;
    setEstaCancelando(true);
    setErro("");
    try {
      await cancelarDownloadApi(statusDownload.download_id);
      setStatusDownload({
        ...statusDownload,
        status: "expired",
        progress: null,
        message: "Processamento cancelado e arquivo temporário removido.",
        download_url: null,
      });
      setTransferenciaIniciada(false);
    } catch (falhaCapturada) {
      setErro(
        falhaCapturada instanceof Error
          ? falhaCapturada.message
          : "Não foi possível cancelar o processamento.",
      );
    } finally {
      setEstaCancelando(false);
    }
  }

  const opcaoFormatoSelecionada = previa?.formats.find(
    (opcaoFormato) => opcaoFormato.format_id === formatoSelecionado,
  );
  const downloadBloqueado = Boolean(
    statusDownload &&
    ["queued", "processing", "completed"].includes(statusDownload.status),
  );

  return (
    <div className="estrutura-pagina">
      <header className="barra-superior">
        <a className="marca-textual" href="#inicio" aria-label="Sapo, início">
          <span className="ponto-marca" aria-hidden="true" />
          <span>
            sapo<span className="ponto-final-marca">.</span>
          </span>
        </a>
        <a
          className="link-projeto"
          href="https://github.com/viniciusufersa/sapo-downloader"
          target="_blank"
          rel="noreferrer"
        >
          Projeto no GitHub{" "}
          <ArrowUpRight size={15} strokeWidth={1.8} aria-hidden="true" />
        </a>
      </header>

      <main id="inicio" className="conteudo-principal">
        <section className="introducao" aria-labelledby="titulo-pagina">
          <p className="rotulo-destaque">
            <span /> MÍDIAS COM AUTORIZAÇÃO
          </p>
          <h1 id="titulo-pagina">
            Um link. Uma cópia.
            <br />
            <span>Sem complicação.</span>
          </h1>
          <p className="texto-introducao">
            Analise os formatos disponíveis e salve o que você tem permissão
            para baixar.
          </p>
        </section>

        <section className="area-aplicacao" aria-label="Analisar mídia">
          <form className="formulario-link" onSubmit={analisarVideo}>
            <label htmlFor="url-video">Link do vídeo</label>
            <div className="linha-entrada">
              <div className="grupo-entrada">
                <Link2 size={19} strokeWidth={1.7} aria-hidden="true" />
                <input
                  id="url-video"
                  name="url"
                  type="url"
                  autoComplete="url"
                  placeholder="Cole aqui um link do YouTube"
                  value={urlVideo}
                  onChange={(evento) => setUrlVideo(evento.target.value)}
                  disabled={downloadBloqueado}
                  aria-invalid={Boolean(erro)}
                  required
                  maxLength={2048}
                  aria-describedby={erro ? "erro-formulario" : "dica-link"}
                />
                {urlVideo && (
                  <button
                    className="botao-limpar"
                    type="button"
                    onClick={() => setUrlVideo("")}
                    aria-label="Limpar link"
                    disabled={downloadBloqueado}
                  >
                    <X size={16} />
                  </button>
                )}
              </div>
              <button
                className="botao-principal botao-analisar"
                type="submit"
                disabled={
                  estaCarregando || downloadBloqueado || !urlVideo.trim()
                }
              >
                {estaCarregando && !statusDownload ? (
                  <LoaderCircle className="animacao-carregamento" size={17} />
                ) : null}
                Analisar link
              </button>
            </div>
            <p id="dica-link" className="ajuda-campo">
              Funciona com links de vídeos individuais do YouTube.
            </p>
          </form>

          {erro && (
            <div id="erro-formulario" className="aviso aviso-erro" role="alert">
              <CircleAlert size={18} /> <span>{erro}</span>
            </div>
          )}

          {estaCarregando && !previa && (
            <div className="estado-analise" role="status">
              <LoaderCircle className="animacao-carregamento" size={19} />{" "}
              Analisando informações do vídeo…
            </div>
          )}

          {previa && (
            <div className="previa" aria-live="polite">
              <div className="divisoria-previa">
                <span>PRÉVIA DO VÍDEO</span>
                <span className="disponibilidade">
                  <span /> Disponível
                </span>
              </div>
              <div className="resumo-midia">
                {previa.thumbnail ? (
                  <img className="miniatura" src={previa.thumbnail} alt="" />
                ) : (
                  <div className="miniatura miniatura-reserva">
                    <Link2 size={24} />
                  </div>
                )}
                <div className="detalhes-midia">
                  <h2>{previa.title}</h2>
                  <p>
                    {formatarDuracao(previa.duration_seconds)}{" "}
                    <span aria-hidden="true">·</span> {previa.formats.length}{" "}
                    {previa.formats.length === 1
                      ? "formato disponível"
                      : "formatos disponíveis"}
                  </p>
                </div>
              </div>

              {!statusDownload && (
                <div className="opcoes-download">
                  <label htmlFor="formato-escolhido">Qualidade e formato</label>
                  <div className="grupo-selecao">
                    <select
                      id="formato-escolhido"
                      value={formatoSelecionado}
                      onChange={(evento) =>
                        setFormatoSelecionado(evento.target.value)
                      }
                    >
                      {previa.formats.map((opcaoFormato) => (
                        <option
                          key={opcaoFormato.format_id}
                          value={opcaoFormato.format_id}
                        >
                          {opcaoFormato.label} ·{" "}
                          {formatarTamanho(opcaoFormato.filesize)}
                        </option>
                      ))}
                    </select>
                    <span className="indicador-selecao" aria-hidden="true">
                      ⌄
                    </span>
                  </div>
                  <label className="confirmacao-autorizacao">
                    <input
                      type="checkbox"
                      checked={temAutorizacao}
                      onChange={(evento) =>
                        setTemAutorizacao(evento.target.checked)
                      }
                    />
                    <span className="caixa-selecao" aria-hidden="true">
                      <Check size={13} />
                    </span>
                    <span>
                      Confirmo que tenho autorização para baixar esta mídia.
                    </span>
                  </label>
                  <button
                    className="botao-principal botao-download"
                    type="button"
                    onClick={iniciarDownload}
                    disabled={
                      !temAutorizacao ||
                      !opcaoFormatoSelecionada ||
                      estaCarregando
                    }
                  >
                    {estaCarregando ? (
                      <LoaderCircle
                        className="animacao-carregamento"
                        size={17}
                      />
                    ) : (
                      <ArrowDownToLine size={18} strokeWidth={1.8} />
                    )}
                    Baixar arquivo
                  </button>
                </div>
              )}

              <DownloadStatus
                status={statusDownload}
                estaCancelando={estaCancelando}
                aoCancelar={cancelarDownload}
                aoIniciarTransferencia={() => setTransferenciaIniciada(true)}
              />
            </div>
          )}

          {!previa && !estaCarregando && !erro && (
            <div className="orientacao-vazia">
              <div className="icone-orientacao-vazia">
                <ArrowDownToLine size={18} strokeWidth={1.7} />
              </div>
              <span>
                Os detalhes e formatos aparecem aqui depois da análise.
              </span>
            </div>
          )}
        </section>

        <div className="aviso-privacidade">
          <ShieldCheck size={16} strokeWidth={1.8} />
          <span>
            Sem contas, sem histórico. Arquivos temporários são removidos após o
            download.
          </span>
        </div>
      </main>

      <footer className="rodape">
        <span>
          Use apenas mídias próprias ou com autorização dos titulares.
        </span>
        <span aria-hidden="true">·</span>
        <a
          href="https://www.youtube.com/t/terms"
          target="_blank"
          rel="noreferrer"
        >
          Termos do YouTube <ArrowUpRight size={12} />
        </a>
      </footer>
    </div>
  );
}
