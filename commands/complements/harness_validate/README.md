# harness_validate

Comando: `/harness-validate`

Validação: pipelines test:run, verify e lint

## Uso

```text
/harness-validate tasks
/harness-validate runs [--last N]
/harness-validate prompt
/harness-validate env:check
/harness-validate run <tarefa> [--param k=v ...] [--yes] [--dry-run]
/harness-validate exec --clip | --file F | --stdin [--yes] [--dry-run]
```

Atalhos: (nenhum).

## Tarefas

- `test:run`
- `verify`
- `lint`

Tarefas de core disponíveis em qualquer comando: `env:check`, `prompt`.

## Política

Blocos vindos do LLM não executam: (nenhuma).

`plugins.validate.enabled=false` desabilita o comando. O workspace,
venv e `harness.yaml` são compartilhados com o pack de mapeamento.
