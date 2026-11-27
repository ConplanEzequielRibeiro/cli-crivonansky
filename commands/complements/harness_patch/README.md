# harness_patch

Comando: `/harness-patch`

Patch: aplicação de diff preservando encoding/CRLF/BOM

## Uso

```text
/harness-patch tasks
/harness-patch runs [--last N]
/harness-patch prompt
/harness-patch env:check
/harness-patch run <tarefa> [--param k=v ...] [--yes] [--dry-run]
/harness-patch exec --clip | --file F | --stdin [--yes] [--dry-run]
```

Atalhos: `apply`.

## Tarefas

- `patch:apply`

Tarefas de core disponíveis em qualquer comando: `env:check`, `prompt`.

## Política

Blocos vindos do LLM não executam: `patch:apply`.

`plugins.patch.enabled=false` desabilita o comando. O workspace,
venv e `harness.yaml` são compartilhados com o pack de mapeamento.
