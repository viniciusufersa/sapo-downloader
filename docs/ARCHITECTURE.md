# Arquitetura

## Estrutura

```text
frontend/src/       Interface React, estilos e testes de interface
backend/app/        API FastAPI, validação, configuração e integração com yt-dlp
backend/tests/      Testes da API e validação de URLs e formatos
.github/workflows/  Verificações automatizadas de qualidade
Dockerfile          Build do frontend e imagem de execução da API
render.yaml         Configuração declarativa do serviço no Render
```

## Fluxo de análise e download

1. O frontend envia uma URL para `POST /api/media/analyze`.
2. O backend permite apenas hosts e caminhos de vídeo do YouTube definidos em `backend/app/security.py`, valida o identificador e reconstrói uma URL canônica.
3. O yt-dlp é executado como subprocesso, sem shell, para consultar metadados e formatos.
4. O backend filtra formatos progressivos e pares de faixas com codecs compatíveis: H.264/AAC em MP4 ou VP8, VP9 ou AV1 com Opus ou Vorbis em WebM. Aplica os limites de duração e tamanho e retorna apenas as opções disponíveis.
5. `POST /api/downloads` exige confirmação de autorização e cria uma tarefa em memória com diretório temporário próprio.
6. O frontend consulta `GET /api/downloads/{id}`. O arquivo pronto é entregue por `GET /api/downloads/{id}/file` e removido após a transferência; `DELETE /api/downloads/{id}` cancela ou descarta a tarefa.
7. Para pares separados, yt-dlp baixa os IDs validados e usa FFmpeg para remuxar sem recodificação no contêiner selecionado. O backend verifica tamanho, extensão, contêiner e faixas com ffprobe antes de marcar a tarefa como concluída.

## Estado e arquivos temporários

As tarefas, o limitador de requisições e os semáforos são mantidos em memória. Essa configuração pressupõe uma única instância e perde o estado em uma reinicialização. O limitador aceita até 4.096 chaves por endereço de conexão e rota, remove entradas expiradas quando atinge a capacidade e recusa novas chaves enquanto a capacidade estiver ocupada. O backend não confia em cabeçalhos encaminhados; o endereço individual de clientes atrás do proxy do Render precisa ser validado no serviço real ou controlado por uma camada de edge confiável. Cada download usa um identificador aleatório e uma pasta isolada. A limpeza ocorre após a transferência, cancelamento ou expiração; falhas de remoção são registradas. Na inicialização, pastas antigas com identificadores de tarefa também são removidas.

## Limites de rede e execução

O backend limita o corpo da API, a taxa de requisições, a concorrência, a duração da mídia, o tamanho do arquivo e o tempo de subprocesso. Antes do processamento, verifica se há espaço livre para até três vezes o limite de tamanho configurado; o resultado final também precisa respeitar esse limite. O yt-dlp é executado sem shell e com `--no-remote-components`; esse parâmetro impede a busca de componentes JavaScript remotos, mas não restringe os destinos HTTP acessados pelos extratores e pelas URLs de mídia. A validação da URL inicial não é uma proteção completa contra SSRF. O serviço só deve ser exposto publicamente depois de existir e ser testada uma política de egress compatível com os hosts de mídia necessários. A disponibilidade do yt-dlp varia conforme o serviço de origem e o provedor.
