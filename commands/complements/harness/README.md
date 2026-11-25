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

## Perfis de stack

O recorte de arquivos, as linguagens do parser, os imports e o dialeto SQL vêm de um
**perfil de stack** resolvido de `legacy.stack` (padrão `php-mysql`):

| Perfil | Extensões | Linguagens (ast-grep) | Dialeto |
|---|---|---|---|
| `php-mysql` (padrão) | php, js, jsx, ts, tsx, py | php, javascript, typescript, tsx, python | mysql |
| `java-oracle` | java, jsp | java | oracle |
| `dotnet-sqlserver` | cs | csharp | tsql |
| `ruby-postgres` | rb, erb | ruby | postgres |
| `node-postgres` | js, jsx, ts, tsx, mjs, cjs | javascript, typescript, tsx | postgres |
| `custom` | overrides | overrides | overrides |

Overrides no `harness.yaml` (vencem o perfil):

```yaml
legacy:
  stack: custom
  extensions: [".go", ".tmpl"]
  sql_extensions: [".go"]
  languages: { ".go": "go" }
  db_dialect: postgres
  encoding: cp1252
```

Precedência: perfil → `legacy.*` → defaults do harness. Linguagens sem perfil embutido
funcionam via `custom` (ex.: Go: `extensions: [".go"]`, `languages: {".go": "go"}`).

Dialetos com snapshot/consulta **ao vivo**: `mysql`, `postgres`. Os demais usam
`legacy.schema_dump`. Encoding: UTF-8 → `legacy.encoding` → cp1252/latin-1.

Para adicionar uma linguagem: registre extensão/kinds em `profiles.py`
(`EXTENSION_LANGUAGES`, `DEFINITION_KINDS`, `IMPORT_PATTERNS`), o fallback regex em
`astsym.py` e, se for uma stack recorrente, um perfil novo. Linguagem fora da allowlist
**nunca** chega ao ast-grep (ele derruba o processo com linguagem inválida).

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
| `code:skeleton` | read | Esqueleto em níveis (índice, `level=map`, `level=dir path=`); incremental |
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
| `patch:apply` | write | Aplica diff preservando encoding/CRLF/BOM; exige branch não protegida |
| `notes:draft` | read | Rascunho de ficha de módulo (frontmatter + seções) |
| `notes:save` | write | Valida e grava a ficha em `notes_path` (mostra diff) |
| `notes:stale` | read | Fichas cujos arquivos de origem mudaram |
| `state:save` / `state:load` / `state:list` | write/read/read | Estado de tarefa (`crivonansky-state`) para retomar numa conversa nova |
| `watch:clip` | read | Monitora o clipboard e executa blocos novos (política e y/N do `exec`) |
| `watch:downloads` | read | Monitora downloads: `.patch`, fichas e estados, sempre com confirmação |
| `kb:export` | write | Pasta com MAPA, glossário, ADRs e fichas revisadas (redact + MANIFEST) |
| `clean:artifacts` | write | Remove artefatos regeráveis (`knowledge/*`, exceto `notes`) |
| `clean:runs` | write | Remove execuções antigas de `runs/` e compacta o `runs.jsonl` |
| `test:run` / `verify` / `lint` | read | Pipelines do `harness.yaml` |
| `prompt` | read | Prompt do LLM no clipboard |

Tarefas `write` pedem confirmação. Blocos vindos do LLM nunca aceitam `--yes` e **não
executam** `shell:run`, `py:run` e `docker:exec` (só o usuário, pela linha de comando;
configurável em `policy.llm_denied_tasks` / `policy.llm_allowed_tasks`). Na TUI a
confirmação abre um modal (`y`/`n`) com a prévia da tarefa; no terminal continua `y/N`.

## Esqueleto em níveis e fichas

`code:skeleton` grava em `workspace/knowledge/skeleton/`:

| Arquivo | Conteúdo |
|---|---|
| `project.json` | índice completo (símbolos, tabelas, imports) |
| `SKELETON.md` | repo pequeno: símbolos inline; repo grande: índice (diretórios + tabelas), dentro de 16.000 caracteres |
| `MAP.md` | por diretório, os 5 arquivos mais relevantes (tabelas, includes recebidos, símbolos, tamanho) |
| `dirs/<dir>.md` | símbolos de cada diretório, lidos sob demanda |

```text
code:skeleton                              # gera tudo (incremental)
code:skeleton --level map                  # devolve o MAP.md
code:skeleton --level dir --path cadastro  # símbolos de cadastro/ (e subpastas)
code:skeleton --exclude "relatorios,*_old.php"
```

Exclusões permanentes em `legacy.exclude` (globs de diretório, caminho ou nome); valem
para `code:skeleton` e `db:links`. Toda saída cortada traz `[truncado: N … — dica]`.

**Fichas** são Markdown com frontmatter (`modulo`, `tags`, `tabelas`, `arquivos`,
`hash_fonte`, `revisado`, `atualizado_em`) e seis seções fixas. Ficam em
`knowledge.notes_path` (repositório git próprio; padrão `workspace/knowledge/notes/`).
Fluxo: `notes:draft --module cadastro` → completar no chat → `notes:save --clip` →
`notes:stale` (roda no hook pós-commit) lista as fichas cujos arquivos mudaram.
`notes:save` não faz commit; você revisa o diff no repositório de notas.

## Estado, monitores e exportação

**Estado de tarefa.** O prompt pede que o Claude encerre com um bloco `crivonansky-state`
(`tarefa`, `decisoes`, `arquivos`, `pendencias`, `proximo_passo`).

```text
state save --clip            # valida e grava em <notes_path>/estado/AAAA-MM-DD-<tarefa>.md
state list
state load --last            # ou: state load <parte-do-nome>; devolve o prompt de abertura
```

`state load` junta o estado ao `MAP.md`: cole na conversa nova e a tarefa continua de onde
parou. Nada é commitado; o caminho gravado é informado.

**Monitores** (só o usuário os inicia; blocos do LLM não podem). Param com `Ctrl+C` ou
`watch clip --stop` / `watch downloads --stop`.

- `watch clip` (intervalo `--interval_ms`, padrão 500): reage só a blocos `crivonansky`
  novos, ignora o próprio `crivonansky-result`, executa pelo mesmo caminho do `exec`
  (política, y/N, redact, truncamento) e deixa o resultado no clipboard.
- `watch downloads [--path P] [--branch B]`: reconhece `*.patch` (→ `patch:apply`), fichas
  `.md` válidas (→ `notes:save`) e blocos de estado (→ `state:save`). Só trata arquivos
  novos desde o início (`--include_existing` para os antigos), pergunta sempre, nunca apaga
  o arquivo e lembra o que já viu em `runs/watch-downloads.json`.

**`kb export`** grava em `workspace/kb_export/` (ou `kb.export_path`) `MAPA.md`,
`glossario.md`, `adr/*.md` e as fichas com `revisado: true`, aplicando `redact`, respeitando
`kb.max_chars` (padrão 200.000; o que não cabe é listado) e gerando `MANIFEST.md` com o hash
de cada arquivo e o que mudou desde a última exportação. As fichas entram da mais recente
para a mais antiga (ainda não há contagem de consultas).

## Privacidade (`policy.redact`)

Antes de ir para o clipboard/stdout (`exec`, `ask`, `context:pack`), o harness mascara
CPF/CNPJ (com dígitos verificadores), e-mail, telefone e segredos (`senha`, `token`,
`mysql_connect(..., 'senha')`, `.env`, chaves privadas). Em `db:query`, colunas listadas em
`policy.redact.columns` saem como `[MASCARADO]` (se não for possível identificar a coluna,
a consulta é negada). O resumo informa `[redact: cpf=2, …]`; o log bruto só é guardado
com `policy.redact.keep_raw_log: true`.

## `patch:apply` e o encoding do legado

O diff do chat é UTF-8/LF; o harness lê o formato real de cada arquivo alvo (encoding de
`legacy.encoding`, CRLF/LF, BOM) e reescreve o diff nele antes do `git apply`; se o
resultado mudar o formato, o patch é revertido. Parâmetros: `branch` (cria/usa a branch),
`allow_dirty`, `strip`, `verify`. Branches de `patch.protected_branches` (padrão: main,
master, develop, production, producao) exigem `branch`. Arquivos tocados precisam estar
limpos no git.

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

## Limpeza

Duas tarefas de escrita (pedem confirmação e mostram o que será removido):

```text
run clean:artifacts [--scope skeleton,db,links,docs,legacy-code] [--param dry_run=true]
run clean:runs      [--days 30] [--keep 100] [--param dry_run=true]
```

- **`clean:artifacts`** remove `knowledge/{skeleton,db,links,docs}` e, com
  `legacy-code`, o resíduo da v1 em `knowledge/code/` (que nenhuma tarefa atual lê).
  **Nunca** toca `knowledge/notes/` (fichas) nem o `harness.yaml`.
- **`clean:runs`** apaga execuções mais antigas que `days` **e** fora das `keep` mais
  recentes (proteção dupla) e reescreve o `runs.jsonl` só com execuções existentes.
  Diretórios fora do padrão `c-<8 hex>` (ex.: `rag-api.*`) são ignorados.
- `--param dry_run=true` lista caminhos e tamanho sem apagar (roda como leitura, sem
  confirmação). O `env:check` mostra o tamanho de `knowledge/` e `runs/`.

`vendor/` e `.venv/` ficam de fora: são reinstaláveis, mas caros; remova manualmente
(veja "Instalação").

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
| `legacy.exclude` / `skeleton.exclude` | `code:skeleton`, `db:links` | Globs excluídos da varredura |
| `skeleton.max_symbols` / `recent_days` | `code:skeleton` | Símbolos por arquivo no SKELETON.md; janela de commits do ranking |
| `output.ask_context` / `ask_budget` / `token_chars` | `ask` | Contextos padrão (`map,notes,db`), orçamento em tokens e caracteres por token |
| `knowledge.notes_path` | `notes:*`, `code:search scope=notes` | Repositório git das fichas; entra em `allowed_roots` |
| `watch.downloads_path` / `watch.patch_branch` | `watch:downloads` | Pasta monitorada (padrão: Downloads do usuário) e branch usada nos patches |
| `kb.export_path` / `kb.max_chars` | `kb:export` | Destino e limite total de caracteres |
| `policy.redact.*` | todas as saídas | `enabled`, `patterns`, `columns`, `secrets`, `apply_to`, `keep_raw_log` |
| `policy.llm_denied_tasks` / `llm_allowed_tasks` | blocos do LLM | Padrão nega `shell:run`, `py:run`, `docker:exec` |
| `patch.protected_branches` / `allow_dirty` | `patch:apply` | Branches que exigem `branch`; aceitar árvore suja |
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
  stack: php-mysql
  encoding: utf-8
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
