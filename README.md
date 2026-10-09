# Sapo Downloader

Aplicação web para analisar vídeos individuais do YouTube e baixar formatos progressivos ou combinar faixas compatíveis de áudio e vídeo, quando o usuário tem autorização para fazê-lo.

## Funcionalidades

- Valida e normaliza links HTTPS de vídeos individuais do YouTube.
- Exibe título, miniatura, duração e formatos MP4 ou WebM com áudio e vídeo.
- Combina faixas separadas H.264/AAC em MP4 e VP8, VP9 ou AV1 com Opus ou Vorbis em WebM, sem recodificação.
- Verifica o contêiner e os codecs do arquivo concluído com `ffprobe` antes de disponibilizá-lo.
- Processa downloads em segundo plano e consulta o estado e o progresso informado pelo yt-dlp.
- Permite cancelar o processamento ou descartar um arquivo pronto.
- Remove arquivos temporários após a transferência, cancelamento ou expiração e registra falhas do sistema de arquivos.
- Aplica limites de tamanho do corpo da API, taxa de requisições, concorrência, duração e tamanho do arquivo.

## Tecnologias

- Frontend: React, TypeScript, Vite, Tailwind CSS e Lucide.
- Backend: Python, FastAPI, Pydantic, yt-dlp, FFmpeg e ffprobe.
- Qualidade: Prettier, ESLint, TypeScript, Ruff, mypy, Vitest, pytest e pip-audit.
- Empacotamento: Docker.

## Execução local

Requisitos: Python 3.13 ou superior, Node.js 24, FFmpeg e ffprobe disponíveis no `PATH`. O yt-dlp usa o Node como runtime JavaScript. No Windows, use uma distribuição indicada pela [página oficial de downloads do FFmpeg](https://ffmpeg.org/download.html).

No PowerShell, a partir da pasta do projeto, crie o ambiente Python e instale as dependências:

```powershell
py -3.13 -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install --require-hashes -r backend/requirements-dev.lock
```

Inicie a API em um terminal:

```powershell
backend/.venv/Scripts/python.exe backend/run.py
```

Em outro terminal, instale as dependências e inicie o frontend:

```powershell
Set-Location frontend
npm.cmd ci
npm.cmd run dev
```

Abra o endereço informado pelo Vite. Durante o desenvolvimento, as requisições `/api` são encaminhadas para `http://127.0.0.1:8000`.

## Configuração

Não há variáveis obrigatórias para a execução local. Os valores padrão estão listados em [`.env.example`](.env.example), mas o aplicativo não carrega esse arquivo automaticamente. Exporte as variáveis no ambiente do processo da API ou configure-as no provedor de hospedagem.

| Variável                     | Padrão          | Descrição                                                                                       |
| ---------------------------- | --------------- | ----------------------------------------------------------------------------------------------- |
| `PORT`                       | `8000`          | Porta HTTP da API.                                                                              |
| `MAX_CONCURRENT_DOWNLOADS`   | `1`             | Número máximo de processamentos simultâneos.                                                    |
| `MAX_STORED_DOWNLOADS`       | `1`             | Número máximo de arquivos prontos aguardando transferência.                                     |
| `MAX_MEDIA_DURATION_SECONDS` | `1800`          | Duração máxima do vídeo.                                                                        |
| `MAX_DOWNLOAD_SIZE_MB`       | `200`           | Tamanho máximo do arquivo.                                                                      |
| `TEMP_FILE_TTL_MINUTES`      | `30`            | Tempo até a remoção de arquivos temporários.                                                    |
| `REQUEST_TIMEOUT_SECONDS`    | `120`           | Timeout da análise; o processamento de download tem limite próprio de até dez vezes esse valor. |
| `TEMP_DIR`                   | `.tmp`          | Diretório dos arquivos temporários.                                                             |
| `FRONTEND_DIST`              | `frontend/dist` | Diretório da build estática servida pela API, quando presente.                                  |

## Desenvolvimento e verificações

Frontend, executado na pasta `frontend`:

```powershell
npm.cmd run format
npm.cmd run format:check
npm.cmd run lint
npm.cmd audit --audit-level=moderate
npm.cmd run typecheck
npm.cmd test -- --run
npm.cmd run build
```

Backend, executado na pasta `backend`:

```powershell
.venv/Scripts/python.exe -m ruff check app tests run.py
.venv/Scripts/python.exe -m ruff format --check app tests run.py
.venv/Scripts/python.exe -m mypy
.venv/Scripts/pip-audit.exe --requirement requirements-dev.lock
.venv/Scripts/python.exe -m pytest
```

O workflow de integração contínua executa formatação, lint, checagem de tipos, testes, build do frontend e construção da imagem Docker em pushes e pull requests.

## Deploy

O projeto contém um [Dockerfile](Dockerfile) e um [Blueprint do Render](render.yaml), mas a imagem Docker e a implantação no Render ainda não foram validadas. O serviço não deve ser exposto publicamente enquanto o egress do subprocesso yt-dlp e a identificação confiável de clientes atrás do proxy não tiverem controles efetivos e validados no ambiente de hospedagem.

## Limitações

- São aceitos somente vídeos individuais em hosts do YouTube explicitamente permitidos; playlists, transmissões ao vivo, conteúdo privado, cookies, DRM e contorno de controles de acesso não são suportados.
- São aceitos formatos progressivos compatíveis e combinações H.264/AAC em MP4 ou VP8, VP9 ou AV1 com Opus ou Vorbis em WebM. A aplicação não recodifica mídia nem oferece MP3.
- A confirmação de autorização é fornecida pelo usuário; o aplicativo não verifica direitos autorais nem permissão do titular.
- O estado das tarefas e o limite de taxa ficam em memória e pressupõem uma única instância. O limitador tem capacidade fixa, usa o endereço de conexão observado pelo servidor e não confia em `X-Forwarded-For`; o endereço individual atrás do proxy do Render não foi validado. Uma reinicialização encerra tarefas e invalida arquivos pendentes.
- A aplicação desativa a busca de componentes remotos do yt-dlp, mas não impõe uma política de egress para os destinos de rede acessados durante a extração. A validação do link inicial não elimina esse risco.
- O subprocesso yt-dlp pode acessar destinos adicionais para extrair e baixar mídia. `--no-remote-components` não restringe destinos de rede. A hospedagem pública permanece bloqueada até existir um controle de saída de rede comprovado e identificação confiável do cliente atrás do proxy.
- O estado das tarefas, os downloads e o limitador são mantidos em memória e em disco temporário local. Uma única instância e armazenamento efêmero não oferecem persistência ou continuidade após reinicializações.
- A disponibilidade de extração depende do YouTube e do ambiente de hospedagem. A imagem Docker precisa ser construída e validada no ambiente de CI antes da publicação; a implantação pública não foi validada.

## Licença

Este projeto está licenciado sob a [MIT License](LICENSE).
