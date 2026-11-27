# harness_watch

Comando: `/harness-watch`

Monitores: clipboard e pasta de downloads

## Uso

```text
/harness-watch tasks
/harness-watch runs [--last N]
/harness-watch prompt
/harness-watch env:check
/harness-watch run <tarefa> [--param k=v ...] [--yes] [--dry-run]
/harness-watch exec --clip | --file F | --stdin [--yes] [--dry-run]
```

Atalhos: `clip`, `downloads`.

## Tarefas

- `watch:clip`
- `watch:downloads`

Tarefas de core disponíveis em qualquer comando: `env:check`, `prompt`.

## Política

Blocos vindos do LLM não executam: `watch:clip`, `watch:downloads`.

`plugins.watch.enabled=false` desabilita o comando. O workspace,
venv e `harness.yaml` são compartilhados com o pack de mapeamento.
