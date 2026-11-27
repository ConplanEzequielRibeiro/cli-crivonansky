# harness_exec

Comando: `/harness-exec`

Execução: shell, Python, Docker, git e logs

## Uso

```text
/harness-exec tasks
/harness-exec runs [--last N]
/harness-exec prompt
/harness-exec env:check
/harness-exec run <tarefa> [--param k=v ...] [--yes] [--dry-run]
/harness-exec exec --clip | --file F | --stdin [--yes] [--dry-run]
```

Atalhos: (nenhum).

## Tarefas

- `shell:run`
- `py:run`
- `docker:exec`
- `logs:tail`
- `git:run`

Tarefas de core disponíveis em qualquer comando: `env:check`, `prompt`.

## Política

Blocos vindos do LLM não executam: `shell:run`, `py:run`, `docker:exec`, `git:run`.

`plugins.exec.enabled=false` desabilita o comando. O workspace,
venv e `harness.yaml` são compartilhados com o pack de mapeamento.
