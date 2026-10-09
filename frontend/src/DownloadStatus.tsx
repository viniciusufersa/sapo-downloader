import {
  ArrowDownToLine,
  Check,
  CircleAlert,
  LoaderCircle,
} from "lucide-react";
import type { StatusDownload } from "./api";

type PropsDownloadStatus = {
  status: StatusDownload | null;
  estaCancelando: boolean;
  aoCancelar: () => void;
  aoIniciarTransferencia: () => void;
};

export default function DownloadStatus({
  status,
  estaCancelando,
  aoCancelar,
  aoIniciarTransferencia,
}: PropsDownloadStatus) {
  if (!status) return null;

  if (status.status === "queued" || status.status === "processing") {
    return (
      <div className="estado-processamento" role="status" aria-live="polite">
        <div className="cabecalho-processamento">
          <LoaderCircle className="animacao-carregamento" size={17} />
          <span>{status.message}</span>
        </div>
        <div
          className="trilho-progresso"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={status.progress ?? undefined}
          aria-valuetext={
            status.progress === null
              ? "Progresso indeterminado"
              : `${Math.round(status.progress)}%`
          }
        >
          <div
            className={
              status.progress === null
                ? "preenchimento-progresso indeterminado"
                : "preenchimento-progresso"
            }
            style={
              status.progress === null
                ? undefined
                : { width: `${status.progress}%` }
            }
          />
        </div>
        <button
          className="botao-texto botao-cancelar"
          type="button"
          onClick={aoCancelar}
          disabled={estaCancelando}
        >
          {estaCancelando ? "Cancelando…" : "Cancelar processamento"}
        </button>
      </div>
    );
  }

  if (status.status === "completed" && status.download_url) {
    return (
      <div className="estado-download-pronto">
        <p>
          <span className="indicador-sucesso">
            <Check size={14} />
          </span>{" "}
          Arquivo pronto para salvar.
        </p>
        <a
          className="botao-principal botao-download"
          href={status.download_url}
          onClick={aoIniciarTransferencia}
        >
          <ArrowDownToLine size={18} strokeWidth={1.8} /> Baixar arquivo
        </a>
        <span className="aviso-expiracao">
          O arquivo temporário será removido após a transferência.
        </span>
        <button
          className="botao-texto botao-descartar"
          type="button"
          onClick={aoCancelar}
          disabled={estaCancelando}
        >
          Descartar arquivo
        </button>
      </div>
    );
  }

  if (status.status === "failed") {
    return (
      <div className="aviso aviso-erro" role="alert">
        <CircleAlert size={18} /> <span>{status.message}</span>
      </div>
    );
  }

  if (status.status === "expired") {
    return (
      <div className="estado-download-finalizado" role="status">
        {status.message}
      </div>
    );
  }

  return null;
}
