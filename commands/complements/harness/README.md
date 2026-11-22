# Harness — plugin autocontido do Crivonansky

Ponto de entrada único do harness de desenvolvimento assistido para o sistema legado
(PHP/MySQL/JS). Recebe blocos `crivonansky` (colados do LLM), executa tarefas do catálogo
e devolve um bloco `crivonansky-result` (no terminal e no clipboard).

A troca com o LLM é **manual**: você copia o bloco do chat, cola na TUI (ou usa
`exec --clip`) e copia o resultado de volta.

## Estratégia: busca JIT, não ingestão vetorial

Código-fonte **não** é vetorizado. O LLM navega pelo repositório com busca
determinística, guiada por um mapa leve:

```text
code:skeleton  ->  project.json + SKELETON.md (símbolos, tabelas, imports)
code:search    ->  ripgrep no repositório (ou nas notas auditadas)
code:read      ->  leitura fatiada por linha
code:outline   ->  assinaturas + imports de um arquivo
code:symbol    ->  definições (ast-grep) e chamadas (ripgrep)
```

O RAG é **opcional** e cobre só a camada semântica de negócio: manuais, tickets,
schema do banco e vínculos código↔tabela (`db:links`).

## Estrutura

```text
commands/complements/harness/
├── install.ps1                  # instalador (venv + config; RAG opcional)
├── requirements.txt             # deps Python do plugin
├── harness.example.yaml         # template da configuração
├── fixture/exemplo-locadora/    # fixture RotaCar (versionada)
├── workspace/                   # harness.yaml + knowledge/ + runs/ (gitignored)
├── vendor/                      # local-rag-system (gitignored, só com --with-rag)
└── .venv/                       # deps do plugin (gitignored)
```

O `install.ps1` cria o venv do plugin, instala `requirements.txt` e gera
`workspace/harness.yaml` com caminhos absolutos. O pacote `bootstrap.py` adiciona o
site-packages do plugin ao `sys.path` do crivonansky quando o venv do host não tem as
dependências.

> **Módulos do plugin não podem ter nome de módulo da stdlib.** O plugin já teve um
> `types.py`, que sombreava o `types` da biblioteca padrão quando a pasta do harness
> entrava no `sys.path` (subprocessos do pip, execução a partir da pasta) e quebrava
> a instalação. O arquivo hoje é `task_types.py` e
> `tests/harness/test_package_layout.py` impede a reincidência.

## Instalação

```powershell
python crivonansky.py harness install
python crivonansky.py harness install --check-only
python crivonansky.py harness install --force
python crivonansky.py harness install --with-rag     # camada semântica opcional
```

O instalador é idempotente e retomável: cada etapa que toca o disco tem retry, venv
pela metade e clone interrompido são refeitos, e rodar de novo após uma falha retoma
do ponto problemático.

### Python

O **core** exige Python **3.10+**. O RAG opcional exige **3.13+**. O instalador procura
por `-PythonExe`, `HARNESS_PYTHON`, `py -0p`, `C:\Python3*`, `%LOCALAPPDATA%`,
registro e `PATH` (ignorando o atalho da Microsoft Store).

| Flag | Efeito |
|---|---|
| `--check-only` | Só valida pré-requisitos, caminhos e permissão de escrita |
| `--skip-docker` | Permite instalar em máquina sem Docker |
| `--force` | Regenera `workspace/harness.yaml` mesmo se já existir |
| `--python CAMINHO` | Força o interpretador usado no venv |
| `--with-rag` | Clona o `local-rag-system` e cria o venv dele |

Para reinstalar do zero, remova `vendor/` e/ou `.venv/` e rode `/harness install`.

## Operação

| Subcomando | O que faz | Flags |
|---|---|---|
| `start` | Sobe a fixture MySQL/PHP (RAG só com `--rag`) | `--rag`, `--no-docker` |
| `stop` | Para a fixture (e o RAG, se estiver no ar) | `--purge` |
| `prepare` | `start` + coleta + esqueleto (+ `rag:sync` sob demanda) | `--full`, `--sync`, `--rag`, `--no-docker` |
| `preprocess` | Alias de `code:skeleton` (compatibilidade) | `--sync`, `--full`, `--no-codeknow`, `--no-wiki` |
| `config` | Mostra caminhos do plugin/workspace/vendor/venv, `tools.*` e o perfil efetivo (`stack`, dialeto, encoding, extensões, esqueleto) | — |

```text
/harness start                    # fixture MySQL/PHP
/harness start --rag              # fixture + API do RAG
/harness start --no-docker        # nada a iniciar (sem --rag)
/harness prepare                  # db:snapshot, code:skeleton, db:links, docs:import
/harness prepare --sync           # + rag:sync
/harness prepare --full           # esqueleto completo + ingestão completa
/harness preprocess --sync        # esqueleto + rag:sync
/harness config                   # mostra caminhos usados
```

**`prepare`** para no primeiro erro e informa em qual tarefa parou. A ordem é fixa:
`db:snapshot` → `code:skeleton` → `db:links` → `docs:import` → (opcional) `rag:sync`.
O esqueleto vem **antes** do `db:links` porque é ele que resolve o símbolo
(função/método) de cada ocorrência de SQL.

**`start`** sobe a fixture (`setup.ps1` + healthchecks + usuários MySQL) e define
`HARNESS_DB_USER=rotacar_read` / `HARNESS_DB_PASSWORD=readpass` se não existirem. O RAG
só sobe com `--rag`; sem Docker, use `--no-docker` (no-op sem `--rag`).

## Uso do contrato

```text
/harness exec --clip | --file F | --stdin [--yes] [--dry-run]
/harness run <task> [--param k=v ...] [--k v] [--yes] [--dry-run]
/harness ask "<pergunta>" [--context skeleton,code,db,docs,rag]
/harness prompt
/harness tasks
/harness runs [--last N]
/harness hooks install|uninstall|status
/harness env:check
```

Opção global: `--config CAMINHO` (ou a variável `HARNESS_CONFIG`).

### `exec`

Lê blocos `crivonansky` de `--clip` (padrão), `--file CAMINHO` ou `--stdin`. Cada bloco
é validado contra o contrato e o catálogo antes de executar. Vários blocos são
executados em ordem até `output.max_blocks_per_message` (padrão 5), parando no primeiro
status negativo, salvo `continue_on_failure: true`. `--yes` é ignorado para blocos
vindos do LLM; `--dry-run` valida bloco e política, mas não executa.

### `run`

Executa uma tarefa do catálogo diretamente. Parâmetros aceitam `--param k=v` ou `--k v`:

```text
/harness run code:search --pattern "UPDATE.*tb_veiculos" --path cadastro
/harness run code:read --file cadastro/veiculo.php --start 10 --end 40
/harness run db:schema --table tb_veiculos
```

Tarefas de leitura rodam sem confirmação. Tarefas de escrita pedem `y/N`; `--yes` pula a
confirmação somente na linha de comando.

### `ask` / `prompt`

`ask` monta um prompt com a pergunta e, conforme `--context`, inclui:

- `skeleton` (padrão): `workspace/knowledge/skeleton/SKELETON.md`;
- `db` (padrão): resumo de tabelas/colunas de `schema-catalog.json`;
- `code`: ocorrências do identificador mais provável da pergunta (via `code:search`);
- `docs`: lista de manuais/tickets importados (`manifest.json`);
- `rag`: trechos de `rag:search` (requer a API e o RAG instalados).

O texto é impresso e copiado para o clipboard. `prompt` copia apenas o prompt de
instrução do LLM (contrato, workflow JIT e catálogo).

### `tasks` / `runs` / `hooks` / `env:check`

- `tasks`: lista `tarefa`, `intent` (`read`/`write`) e descrição.
- `runs --last N`: lista as últimas execuções de `workspace/runs/runs.jsonl`.
- `hooks install|uninstall|status`: instala/remove hooks `post-commit` e `post-merge` no
  repositório legado. O padrão é `code:skeleton` (incremental); ajuste `hooks.tasks`.
- `env:check`: verifica git, Docker, workspace e `tools.*`. Docker e a API do RAG são
  avisos, não falhas — o core funciona sem eles.

## Flags comuns

| Flag | Aplicação | Efeito |
|---|---|---|
| `--config CAMINHO` | qualquer subcomando | Usa outro `harness.yaml` |
| `--yes` | `run`, `exec` | Pula confirmação de escrita (não vale para blocos do LLM) |
| `--dry-run` | `run`, `exec` | Valida tarefa/bloco e política, sem executar |
| `--param k=v` | `run` | Parâmetro da tarefa |
| `--clip` / `--file F` / `--stdin` | `exec` | Fonte dos blocos |
| `--last N` | `runs` | Quantidade listada (padrão 10) |
| `--context ...` | `ask` | Contextos do prompt |
| `--rag` | `start`, `prepare` | Sobe a API do RAG |
| `--no-docker` | `start`, `prepare` | Não inicia a fixture |
| `--purge` | `stop` | Remove o volume do MySQL |
| `--sync` | `prepare`, `preprocess` | Encadeia `rag:sync` |
| `--full` | `prepare`, `preprocess`, `code:skeleton` | Reindexação completa |
| `--force` | `install`, `code:skeleton` | Regenera config / reconstrói índice |
| `--skip-docker` | `install` | Não exige Docker |
| `--check-only` | `install` | Só valida |
| `--with-rag` | `install` | Instala o RAG opcional |
| `--no-codeknow`, `--no-wiki` | `preprocess` | Aceitos e ignorados (compatibilidade) |

## Status e artefatos

| Status | Significado |
|---|---|
| `success` | Tarefa concluída; exit code 0 |
| `failure` | Rodou, mas o resultado foi negativo (ex.: teste falhou) |
| `error` | Erro de bloco, parâmetro ou do harness |
| `denied` | Barrado pela política ou pelo usuário |
| `timeout` | O prazo expirou; o processo foi encerrado |

Cada execução grava `workspace/runs/<id>/command.yaml`, `result.md` e `full.log`, além
de uma linha em `runs.jsonl`. O clipboard recebe o bloco truncado por
`output.max_chars.clipboard` (padrão 12.000 caracteres).

O workspace de conhecimento:

```text
workspace/knowledge/
├── skeleton/   project.json + SKELETON.md   (mapa do código)
├── code/       src/ (legado, se existir) + ... (não é mais gerado)
├── db/         schema-catalog.json + tables/*.md
├── links/      code-db-links + fk-inferred + includes + tables/*.md
├── docs/       manuals/ + tickets/ + manifest.json
└── notes/      resumos auditados (opcional, buscáveis com scope=notes)
```

## Tarefas

| Tarefa | Intent | Descrição |
|---|---|---|
| `code:skeleton` | read | Esqueleto do código (símbolos, tabelas, imports); incremental |
| `code:search` | read | Busca textual (ripgrep) no repositório ou notas |
| `code:read` | read | Lê um intervalo de linhas |
| `code:outline` | read | Imports + assinaturas de um arquivo |
| `code:symbol` | read | Definições e chamadas de um símbolo |
| `env:check` | read | Verifica git, docker, workspace e RAG opcional |
| `context:pack` | read | Empacota arquivos em Markdown |
| `file:read` | read | Lê arquivo com números de linha |
| `db:snapshot` | read | Schema do banco (live MySQL/Postgres ou dump do dialeto do perfil) |
| `db:schema` | read | Markdown de uma tabela |
| `db:query` | read | SELECT/SHOW/DESCRIBE/EXPLAIN |
| `db:links` | read | SQL embutido + FKs inferidas + includes/imports + visões `tables/*.md` (segue o perfil de stack) |
| `docs:import` | read | Manuais e tickets |
| `rag:serve` | read | Inicia/para/consulta a API local do RAG (opcional) |
| `rag:sync` | read | Publica a camada semântica no RAG e ingere |
| `rag:search` | read | Busca no RAG (opcional) |
| `git:run` | read/write | Comando git |
| `shell:run` | write | Shell do Windows |
| `py:run` | write | Script/módulo Python |
| `docker:exec` | write | Comando no contêiner |
| `logs:tail` | read | Logs de contêiner |
| `patch:apply` | write | Aplica diff e verifica |
| `test:run` / `verify` / `lint` | read | Pipelines do `harness.yaml` |
| `prompt` | read | Prompt do LLM no clipboard |

Tarefas `write` pedem confirmação. Blocos vindos do LLM nunca aceitam `--yes`.

## Progresso das tarefas longas

`db:links`, `code:skeleton` e `install` publicam o andamento em tempo real:

- **TUI:** as linhas aparecem no painel de saída enquanto a tarefa roda;
- **CLI:** as linhas vão para o `stderr` quando ele é um terminal;
- **log:** sempre gravado em `<run_dir>/progress.log` (ou
  `workspace/install.log`/`workspace/prepare.log`).

`HARNESS_PROGRESS` controla o canal: `auto` (padrão), `log`, `stderr` ou `off`.

O `db:links` parseia cada SQL uma única vez (memoizado) e ignora bundles
`*.min.js`/`*.bundle.js`/`*.pack.js`. Para limitar o custo em arquivos gigantes, use
`--max_file_mb N`.

## Configuração

Gerada em `workspace/harness.yaml` pelo `install.ps1`. O template
(`harness.example.yaml`) usa caminhos relativos ao plugin; o instalador troca o
marcador `{{PLUGIN_ROOT}}` pelo caminho absoluto. Também é possível apontar para
outro arquivo com `--config` ou `HARNESS_CONFIG`.

Campos relevantes:

| Campo | Usado por | Observação |
|---|---|---|
| `legacy.stack` | `code:*`, `db:*` | Perfil de stack: `php-mysql` (padrão), `java-oracle`, `dotnet-sqlserver`, `ruby-postgres`, `node-postgres`, `custom` |
| `legacy.encoding` | leitura de fontes | `utf-8` (padrão); legado Windows: `cp1252`/`latin-1` |
| `legacy.extensions` | `code:skeleton`, `db:links` | Sobrepõe as extensões do perfil |
| `legacy.languages` | `code:skeleton`, `code:outline` | Extensão → linguagem do ast-grep (ex.: `".phtml": "php"`) |
| `legacy.db_dialect` | `db:snapshot`, `db:links` | Sobrepõe o dialeto do perfil |
| `legacy.repo_path` | `code:*`, `db:links`, `git:run`, hooks | Repositório legado |
| `legacy.app_container` | `docker:exec`, `logs:tail`, pipelines | Contêiner da aplicação |
| `legacy.db_container` | `db:snapshot` live, `db:query` | Contêiner MySQL |
| `legacy.db_name` | `db:snapshot`, `db:query` | Banco consultado |
| `legacy.manuals_path` | `docs:import` | Aceita `.pdf`, `.md` e `.txt` |
| `legacy.schema_dump` | `db:snapshot` fallback | Estrutura sem dados |
| `tools.rg` | `code:search`, `code:symbol` | Padrão: `rg` do PATH |
| `tools.rag.*` | `rag:serve/sync/search` | Só existe com `--with-rag` |
| `policy.allowed_roots` | leitura/escrita | Inclua repo e workspace |

## Adicionar um projeto real

A fixture `exemplo-locadora` é só referência. Para usar o harness com um projeto real,
aponte o `harness.yaml` para ele. Durante a coleta, o harness **não escreve** no
repositório legado; ações de escrita passam pela política de confirmação.

```yaml
harness_version: 1
workspace: C:/projetos/harness-configs/meu-legado/workspace

legacy:
  repo_path: C:/projetos/meu-legado
  app_container: meu_php
  db_container: meu_mysql
  db_name: meu_banco
  db_user_env: HARNESS_DB_USER
  db_password_env: HARNESS_DB_PASSWORD
  manuals_path: C:/projetos/meu-legado/docs/manuais
  tickets_path: C:/projetos/meu-legado/docs/tickets
  schema_dump: C:/projetos/meu-legado/banco/dump-estrutura.sql

tools:
  python: C:/projetos/cli-crivonansky/commands/complements/harness/.venv/Scripts/python.exe
  rg: rg
  # rag: ... (opcional)

policy:
  allowed_roots:
    - C:/projetos/meu-legado
    - C:/projetos/harness-configs/meu-legado/workspace

pipelines:
  verify:
    - docker:exec: { container: meu_php, command: "php -l index.php" }
```

### Coleta e indexação

```powershell
python crivonansky.py harness run db:snapshot      # live ou fallback do dump
python crivonansky.py harness run code:skeleton    # mapa do código (segundos)
python crivonansky.py harness run db:links         # SQL embutido + FKs + includes
python crivonansky.py harness run docs:import       # manuais e tickets
```

O `rag:sync` é opcional:

```powershell
python crivonansky.py harness install --with-rag
python crivonansky.py harness start --rag
python crivonansky.py harness run rag:sync
```

### Validação

```powershell
python crivonansky.py harness run env:check
python crivonansky.py harness run code:search --pattern "tb_clientes" --max_results 5
python crivonansky.py harness run db:schema --table tb_clientes
python crivonansky.py harness run code:symbol --name salvar_cliente --kind ref
```

Confira `workspace/knowledge/{skeleton,db,links,docs}` e se `SKELETON.md` cita as
tabelas e os diretórios do seu projeto.

### Checklist

- [ ] `repo_path` existe e aponta para o projeto;
- [ ] `HARNESS_DB_USER`/`HARNESS_DB_PASSWORD` definidos (para `db:*` ao vivo);
- [ ] `schema_dump` contém só estrutura;
- [ ] `allowed_roots` inclui repo e workspace;
- [ ] `rg` no PATH (ou `tools.rg` configurado);
- [ ] `env:check`, `db:snapshot`, `code:skeleton`, `db:links` e `docs:import` concluíram;
- [ ] `ask` com `--context skeleton,db` devolve conteúdo do projeto.

## Testes

```powershell
# de dentro de cli-crivonansky
.\.venv\Scripts\python.exe -m pytest tests/harness -q

# RAG (dentro do vendor, só se instalado)
cd commands\complements\harness\vendor\local-rag-system
.\.venv\Scripts\python.exe -m pytest -q
```

## Troubleshooting

| Sintoma | Causa provável | Ação |
|---|---|---|
| `Python 3.10+ (nao encontrado)` com Python instalado | `python` do `PATH` é o atalho da Store | `harness install --python C:\caminho\python.exe` ou `HARNESS_PYTHON` |
| `code:search` retorna `ripgrep (rg) não encontrado` | `rg` fora do PATH | instale o ripgrep ou aponte `tools.rg` |
| `code:symbol` sem definições | esqueleto ausente/desatualizado | rode `harness run code:skeleton` |
| `db:links` sem o campo `symbol` | esqueleto não gerado | rode `code:skeleton` antes de `db:links` |
| `rag:search` responde 503 | índice não existe | `harness run rag:sync` (requer `--with-rag`) |
| `rag:sync` falha com `WinError 2/3` | `tools.rag.*` inexistente | `harness config` mostra `rag_python_exists`/`rag_path_exists` |
| `docker exec ... container not found` | MySQL não está no ar | `harness start` |
| `db:snapshot` cai no modo dump | Docker/contêiner indisponível | `harness start` ou use `--source dump` |
