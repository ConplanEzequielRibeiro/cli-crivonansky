# harness_clean

Comando: `/harness-clean`

Limpeza: artefatos regeráveis e execuções antigas

## Uso

```text
/harness-clean tasks
/harness-clean runs [--last N]
/harness-clean prompt
/harness-clean env:check
/harness-clean run <tarefa> [--param k=v ...] [--yes] [--dry-run]
/harness-clean exec --clip | --file F | --stdin [--yes] [--dry-run]
```

Atalhos: `artifacts`, `runs`.

## Tarefas

- `clean:artifacts`
- `clean:runs`

Tarefas de core disponíveis em qualquer comando: `env:check`, `prompt`.

## Política

Blocos vindos do LLM não executam: `clean:artifacts`, `clean:runs`.

`plugins.clean.enabled=false` desabilita o comando. O workspace,
venv e `harness.yaml` são compartilhados com o pack de mapeamento.
