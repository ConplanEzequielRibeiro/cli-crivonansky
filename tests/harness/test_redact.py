"""Redação de dados pessoais, segredos e colunas (T01/T02)."""

from commands.complements.harness import redact


def _policy(**kw):
    return redact.get_policy({"policy": {"redact": kw}} if kw else {})


def test_cpf_cnpj_email_phone_are_masked():
    text = "cpf 529.982.247-25, cnpj 11.222.333/0001-81, a@b.com.br, (55) 99999-1234"

    out, stats = redact.redact_text(text, _policy())

    for secret in ("529.982.247-25", "11.222.333/0001-81", "a@b.com.br", "99999-1234"):
        assert secret not in out
    assert sum(stats.values()) == 4


def test_raw_cpf_only_when_check_digits_are_valid():
    out, _ = redact.redact_text("ok 52998224725 e id 12345678900", _policy())

    assert "52998224725" not in out
    assert "12345678900" in out  # dígitos inválidos: não é CPF, mantém


def test_secrets_in_code_and_env():
    text = (
        "$senha = 'abc123';\n"
        "DB_PASSWORD=hunter2\n"
        'mysql_connect("h", "u", "segredo");\n'
        "CREATE USER x IDENTIFIED BY 'pw1';\n"
        "Authorization: Bearer abc.def.12345\n"
    )

    out = redact.redact_secrets(text)

    for secret in ("abc123", "hunter2", "segredo", "pw1", "abc.def.12345"):
        assert secret not in out
    assert out.count("\n") == text.count("\n")  # preserva a numeração de linhas


def test_private_key_block_keeps_line_count():
    text = "a\n-----BEGIN RSA PRIVATE KEY-----\nAAAA\nBBBB\n-----END RSA PRIVATE KEY-----\nb\n"

    out = redact.redact_secrets(text)

    assert "AAAA" not in out
    assert out.count("\n") == text.count("\n")


def test_disabled_policy_is_a_noop():
    text = "529.982.247-25"

    assert redact.redact_text(text, _policy(enabled=False))[0] == text


def test_extra_secret_names_and_channels():
    policy = _policy(secrets=["matricula"], apply_to=["exec"])

    assert "999" not in redact.redact_secrets("matricula = '999'", policy.secrets)
    assert redact.applies(policy, "exec")
    assert not redact.applies(policy, "ask")


def test_column_rules_and_mask_rows():
    rules = ("cpf", "tb_cli.*email*")

    assert redact.column_matches(rules, "tb_x", "CPF")
    assert redact.column_matches(rules, "tb_cli", "email_alt")
    assert not redact.column_matches(rules, "tb_x", "nome")

    rows, count = redact.mask_rows([["1", "a", "NULL"], ["2", "b", "c"]], {1, 2})
    assert rows == [["1", "[MASCARADO]", "NULL"], ["2", "[MASCARADO]", "[MASCARADO]"]]
    assert count == 3
