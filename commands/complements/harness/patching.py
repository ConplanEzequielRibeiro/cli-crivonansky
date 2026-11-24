"""Aplicação fiel de diffs: preserva encoding, finais de linha e BOM do arquivo.

O diff que vem do chat é UTF-8 com LF, mas o legado costuma ser ISO-8859-1 com
CRLF. Aplicá-lo cru falha no contexto (CRLF) ou grava mojibake (encoding). Este
módulo lê o formato real de cada arquivo alvo e reescreve as linhas do diff nesse
formato antes do ``git apply``; depois confere o resultado em uma cópia.

Funções puras: nada aqui toca o repositório nem roda o git.
"""

import os
import re
from dataclasses import dataclass, field

BOM = b"\xef\xbb\xbf"
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
DEV_NULL = "/dev/null"
SINGLE_BYTE = {"latin-1", "latin1", "iso-8859-1", "cp1252", "windows-1252"}


class PatchFormatError(Exception):
    """Diff inválido ou impossível de converter para o formato do arquivo."""


@dataclass
class FileFormat:
    encoding: str = "utf-8"
    bom: bool = False
    eol: str = "lf"  # lf | crlf | mixed | none
    final_newline: bool = True

    @property
    def eol_bytes(self) -> bytes:
        return b"\r\n" if self.eol == "crlf" else b"\n"

    def describe(self) -> str:
        bom = "com BOM" if self.bom else "sem BOM"
        return f"{self.encoding}, {self.eol.upper()}, {bom}"


@dataclass
class Hunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    trailer: str = ""
    lines: list = field(default_factory=list)  # (prefixo, conteúdo)


@dataclass
class FilePatch:
    headers: list = field(default_factory=list)
    old_path: str | None = None
    new_path: str | None = None
    hunks: list = field(default_factory=list)
    is_new: bool = False
    is_delete: bool = False
    binary: bool = False

    def target(self, strip: int) -> str | None:
        path = self.new_path if self.new_path not in (None, DEV_NULL) else self.old_path
        if path in (None, DEV_NULL):
            return None
        return strip_prefix(path, strip)


def strip_prefix(path: str, strip: int) -> str:
    parts = path.replace("\\", "/").split("/")
    return "/".join(parts[strip:]) if strip else "/".join(parts)


# ---------------------------------------------------------------------------
# Detecção do formato do arquivo
# ---------------------------------------------------------------------------
def detect_format(raw: bytes, preferred: str = "utf-8") -> FileFormat:
    bom = raw.startswith(BOM)
    body = raw[3:] if bom else raw

    crlf = body.count(b"\r\n")
    lf_only = body.count(b"\n") - crlf
    if crlf == 0 and lf_only == 0:
        eol = "none"
    elif lf_only == 0:
        eol = "crlf"
    elif crlf == 0:
        eol = "lf"
    else:
        eol = "mixed"

    preferred = (preferred or "utf-8").strip()
    if body.isascii():
        # Só ASCII: caracteres novos seguem o encoding configurado do legado.
        encoding = "utf-8" if bom else preferred
    else:
        try:
            body.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            encoding = preferred if preferred.lower().replace("_", "-") not in (
                "utf-8",
                "utf8",
                "auto",
            ) else "cp1252"
            try:
                body.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                encoding = "latin-1"

    return FileFormat(
        encoding=encoding,
        bom=bom,
        eol=eol,
        final_newline=body.endswith(b"\n") if body else True,
    )


def guess_new_file_format(
    repo: str, rel_path: str, preferred: str, default_eol: str = "auto"
) -> FileFormat:
    """Formato de um arquivo novo: encoding do perfil e EOL dos vizinhos."""
    encoding = (preferred or "utf-8").strip()
    if encoding.lower() == "auto":
        encoding = "utf-8"

    eol = default_eol if default_eol in ("lf", "crlf") else None
    if eol is None:
        folder = os.path.join(repo, os.path.dirname(rel_path))
        extension = os.path.splitext(rel_path)[1].lower()
        seen = 0
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            names = []
        for name in names:
            full = os.path.join(folder, name)
            if not os.path.isfile(full) or os.path.splitext(name)[1].lower() != extension:
                continue
            try:
                with open(full, "rb") as fh:
                    sample = detect_format(fh.read(200_000), encoding)
            except OSError:
                continue
            if sample.eol in ("crlf", "lf"):
                eol = sample.eol
                break
            seen += 1
            if seen >= 5:
                break
    return FileFormat(encoding=encoding, bom=False, eol=eol or "lf", final_newline=True)


# ---------------------------------------------------------------------------
# Parse do diff
# ---------------------------------------------------------------------------
def _is_file_header(lines: list[str], index: int) -> bool:
    return (
        lines[index].startswith("--- ")
        and index + 1 < len(lines)
        and lines[index + 1].startswith("+++ ")
    )


def _header_path(line: str) -> str:
    value = line[4:].split("\t")[0].strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
    return value


def parse_diff(text: str) -> list[FilePatch]:
    lines = (text or "").replace("\r\n", "\n").split("\n")
    while lines and lines[-1] == "":
        lines.pop()

    patches: list[FilePatch] = []
    current: FilePatch | None = None
    index = 0

    def fresh() -> FilePatch:
        patch = FilePatch()
        patches.append(patch)
        return patch

    while index < len(lines):
        line = lines[index]

        if line.startswith("diff --git "):
            current = fresh()
            current.headers.append(line)
            index += 1
            continue

        if _is_file_header(lines, index):
            if current is None or current.hunks or current.old_path is not None:
                current = fresh()
            current.old_path = _header_path(line)
            current.new_path = _header_path(lines[index + 1])
            current.is_new = current.is_new or current.old_path == DEV_NULL
            current.is_delete = current.is_delete or current.new_path == DEV_NULL
            index += 2
            continue

        match = HUNK_RE.match(line)
        if match and current is not None:
            hunk = Hunk(
                old_start=int(match.group(1)),
                old_len=int(match.group(2) if match.group(2) is not None else 1),
                new_start=int(match.group(3)),
                new_len=int(match.group(4) if match.group(4) is not None else 1),
                trailer=line[match.end() :],
            )
            index += 1
            old_left, new_left = hunk.old_len, hunk.new_len
            while index < len(lines):
                body = lines[index]
                counting = old_left > 0 or new_left > 0
                if body.startswith("\\"):
                    hunk.lines.append(("\\", body))
                    index += 1
                    continue
                if not counting and (
                    body.startswith("diff --git ")
                    or HUNK_RE.match(body)
                    or _is_file_header(lines, index)
                ):
                    break
                if body == "":
                    prefix, content = " ", ""  # linha de contexto sem o espaço inicial
                elif body[0] in " +-":
                    prefix, content = body[0], body[1:]
                else:
                    break
                hunk.lines.append((prefix, content))
                if prefix in " -":
                    old_left -= 1
                if prefix in " +":
                    new_left -= 1
                index += 1
            current.hunks.append(hunk)
            continue

        if current is not None and not current.hunks:
            current.headers.append(line)
            if line.startswith("new file mode"):
                current.is_new = True
            elif line.startswith("deleted file mode"):
                current.is_delete = True
            elif line.startswith("Binary files") or line.startswith("GIT binary patch"):
                current.binary = True
        index += 1

    return [patch for patch in patches if patch.hunks or patch.binary or patch.headers]


def detect_strip(patches: list[FilePatch]) -> int:
    """``1`` quando os caminhos têm prefixos ``a/``/``b/``; senão ``0``."""
    seen = False
    for patch in patches:
        for path, prefix in ((patch.old_path, "a/"), (patch.new_path, "b/")):
            if path in (None, DEV_NULL):
                continue
            seen = True
            if not path.startswith(prefix):
                return 0
    return 1 if seen else 0


# ---------------------------------------------------------------------------
# Reescrita no formato do arquivo
# ---------------------------------------------------------------------------
def _encode(content: str, fmt: FileFormat, where: str) -> bytes:
    try:
        return content.encode(fmt.encoding)
    except UnicodeEncodeError as exc:
        char = content[exc.start : exc.end]
        raise PatchFormatError(
            f"{where}: o caractere {char!r} não existe em {fmt.encoding}; "
            "troque-o por um equivalente (sem emoji/aspas tipográficas) ou "
            "ajuste legacy.encoding"
        ) from exc
    except LookupError as exc:
        raise PatchFormatError(f"encoding desconhecido: {fmt.encoding}") from exc


def render_file_patch(patch: FilePatch, fmt: FileFormat | None, strip_note: str = "") -> bytes:
    """Serializa um arquivo do diff com as linhas no formato de ``fmt``."""
    out: list[bytes] = []
    for header in patch.headers:
        out.append(header.encode("utf-8") + b"\n")
    if patch.old_path is not None:
        out.append(f"--- {patch.old_path}".encode("utf-8") + b"\n")
        out.append(f"+++ {patch.new_path}".encode("utf-8") + b"\n")

    if fmt is None:
        fmt = FileFormat()
    where = patch.new_path or patch.old_path or "diff"

    for hunk in patch.hunks:
        out.append(
            f"@@ -{hunk.old_start},{hunk.old_len} +{hunk.new_start},{hunk.new_len} @@"
            f"{hunk.trailer}".encode("utf-8")
            + b"\n"
        )

        first_old = first_new = True
        for position, (prefix, content) in enumerate(hunk.lines):
            if prefix == "\\":
                out.append(content.encode("utf-8") + b"\n")
                continue

            raw = _encode(content, fmt, f"{where}, hunk @@ -{hunk.old_start}")
            if fmt.bom and hunk.old_start <= 1:
                # A linha 1 do arquivo carrega o BOM; o diff precisa dele no contexto.
                if prefix in " -" and first_old:
                    raw = BOM + raw
                elif prefix == "+" and first_new and first_old is False:
                    raw = BOM + raw
                elif prefix == "+" and first_new and not any(
                    p in " -" for p, _ in hunk.lines[:position]
                ):
                    raw = BOM + raw
            if prefix in " -":
                first_old = False
            if prefix in " +":
                first_new = False

            nxt = hunk.lines[position + 1][0] if position + 1 < len(hunk.lines) else ""
            # Linha seguida de "\ No newline" não tem terminador de linha no arquivo.
            terminator = b"\n" if nxt == "\\" else fmt.eol_bytes
            out.append(prefix.encode("ascii") + raw + terminator)
    return b"".join(out)


def convert_diff(
    text: str,
    formats: dict[str, FileFormat | None],
    strip: int,
) -> bytes:
    """Reescreve o diff inteiro; ``formats`` mapeia o alvo (relativo) ao formato."""
    patches = parse_diff(text)
    if not patches:
        raise PatchFormatError("nenhum arquivo/hunk reconhecido no diff")
    chunks = []
    for patch in patches:
        target = patch.target(strip)
        fmt = formats.get(target) if target else None
        chunks.append(render_file_patch(patch, fmt))
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# Conferência do resultado
# ---------------------------------------------------------------------------
def verify_result(before: FileFormat, after: bytes) -> list[str]:
    """Problemas de formato introduzidos pelo patch (lista vazia = ok)."""
    problems: list[str] = []
    now = detect_format(after, before.encoding)

    if before.bom != now.bom:
        problems.append("BOM " + ("removido" if before.bom else "adicionado"))

    if before.eol in ("crlf", "lf") and now.eol not in (before.eol, "none"):
        problems.append(
            f"finais de linha mudaram de {before.eol.upper()} para {now.eol.upper()}"
        )

    body = after[3:] if after.startswith(BOM) else after
    if before.encoding.lower() == "utf-8":
        try:
            body.decode("utf-8")
        except UnicodeDecodeError:
            problems.append("o arquivo deixou de ser UTF-8 válido")
    elif before.encoding.lower().replace("_", "-") in SINGLE_BYTE and not body.isascii():
        try:
            body.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            # Texto não-ASCII que também é UTF-8 válido num arquivo single-byte:
            # praticamente certo que o patch gravou UTF-8 (mojibake).
            problems.append(f"bytes UTF-8 gravados em arquivo {before.encoding}")
    return problems
