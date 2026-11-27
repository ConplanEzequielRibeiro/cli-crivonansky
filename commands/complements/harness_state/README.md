# harness_state

Comando: `/harness-state`

Estado: continuidade de tarefa entre conversas

## Uso

```text
/harness-state tasks
/harness-state runs [--last N]
/harness-state prompt
/harness-state env:check
/harness-state run <tarefa> [--param k=v ...] [--yes] [--dry-run]
/harness-state exec --clip | --file F | --stdin [--yes] [--dry-run]
```

Atalhos: `save`, `load`, `list`.

## Tarefas

- `state:save`
- `state:load`
- `state:list`

Tarefas de core disponíveis em qualquer comando: `env:check`, `prompt`.

## Política

Blocos vindos do LLM não executam: (nenhuma).

`plugins.state.enabled=false` desabilita o comando. O workspace,
venv e `harness.yaml` são compartilhados com o pack de mapeamento.
