"""Store SQLite consultável do mapeamento (M1)."""

import hashlib
import json
import os
import sqlite3
from datetime import datetime

from commands.complements.harness_core.config import resolve_path
from commands.complements.harness_core.util import legacy_repo, workspace

SCHEMA_VERSION = 1
DEFAULT_PATH = "knowledge/graph.sqlite"

DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS files (
  path TEXT PRIMARY KEY,
  dir TEXT,
  loc INTEGER,
  size INTEGER,
  mtime INTEGER,
  hash TEXT,
  language TEXT,
  generated INTEGER NOT NULL DEFAULT 0,
  surface TEXT
);
CREATE TABLE IF NOT EXISTS symbols (
  id TEXT PRIMARY KEY,
  file_path TEXT NOT NULL,
  name TEXT NOT NULL,
  kind TEXT,
  line_start INTEGER,
  line_end INTEGER,
  exported INTEGER NOT NULL DEFAULT 0,
  confidence TEXT NOT NULL DEFAULT 'parsed'
);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_path);
CREATE TABLE IF NOT EXISTS imports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_path TEXT NOT NULL,
  target_path TEXT,
  specifier TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'import',
  line INTEGER,
  confidence TEXT NOT NULL DEFAULT 'parsed'
);
CREATE INDEX IF NOT EXISTS idx_imports_file ON imports(file_path);
CREATE TABLE IF NOT EXISTS tables (name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS table_ops (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  table_name TEXT NOT NULL,
  file_path TEXT NOT NULL,
  line INTEGER,
  op TEXT,
  access TEXT,
  sql TEXT,
  symbol TEXT,
  confidence TEXT
);
CREATE INDEX IF NOT EXISTS idx_ops_table ON table_ops(table_name, access);
CREATE INDEX IF NOT EXISTS idx_ops_file ON table_ops(file_path);
CREATE TABLE IF NOT EXISTS fk_inferred (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  from_table TEXT NOT NULL,
  to_table TEXT NOT NULL,
  columns_json TEXT,
  ref_columns_json TEXT,
  evidence TEXT,
  confidence TEXT
);
CREATE INDEX IF NOT EXISTS idx_fk_from ON fk_inferred(from_table);
CREATE TABLE IF NOT EXISTS includes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_path TEXT NOT NULL,
  target_path TEXT,
  kind TEXT,
  line INTEGER
);
CREATE INDEX IF NOT EXISTS idx_includes_file ON includes(file_path);
CREATE TABLE IF NOT EXISTS index_cache (
  path TEXT PRIMARY KEY,
  hash TEXT NOT NULL,
  parser_version INTEGER NOT NULL,
  facts_hash TEXT,
  indexed_at TEXT NOT NULL
);
"""


def db_path(ctx) -> str:
    configured = ((ctx.config or {}).get("graph") or {}).get("path")
    if configured:
        return os.path.abspath(resolve_path(ctx.config, str(configured)))
    return os.path.join(workspace(ctx), "knowledge", "graph.sqlite")


def connect(ctx) -> sqlite3.Connection:
    path = db_path(ctx)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn


def _norm(path: str) -> str:
    return str(path).replace("\\", "/").lstrip("./")


def _hash(path: str) -> str:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()
    except OSError:
        return ""


def _surface(path: str) -> str:
    parts = _norm(path).split("/")
    return parts[0] if len(parts) > 1 else "(root)"


def _language(path: str, profile) -> str:
    ext = os.path.splitext(path)[1].lower()
    return (getattr(profile, "languages", {}) or {}).get(ext, "")


def sync_skeleton(ctx, files_index: dict, profile, parser_version: int) -> dict:
    """Sincroniza files/symbols/imports a partir do ``files_index`` do esqueleto."""
    repo = os.path.abspath(legacy_repo(ctx))
    conn = connect(ctx)
    now = datetime.now().isoformat(timespec="seconds")
    parser_version = int(parser_version or 0)
    try:
        with conn:
            conn.execute("CREATE TEMP TABLE IF NOT EXISTS current_paths(path TEXT PRIMARY KEY)")
            conn.execute("DELETE FROM current_paths")
            for rel, entry in files_index.items():
                rel_norm = _norm(rel)
                path = os.path.join(repo, rel)
                digest = _hash(path)
                size = int(entry.get("size") or (os.path.getsize(path) if os.path.isfile(path) else 0))
                mtime = int(entry.get("mtime") or (int(os.path.getmtime(path)) if os.path.isfile(path) else 0))
                conn.execute(
                    "INSERT OR REPLACE INTO files(path, dir, loc, size, mtime, hash, language, generated, surface) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        rel_norm,
                        os.path.dirname(rel_norm),
                        int(entry.get("loc") or 0),
                        size,
                        mtime,
                        digest,
                        _language(rel_norm, profile),
                        0,
                        _surface(rel_norm),
                    ),
                )
                conn.execute("INSERT OR REPLACE INTO current_paths(path) VALUES(?)", (rel_norm,))

                cached = conn.execute(
                    "SELECT hash, parser_version FROM index_cache WHERE path=?", (rel_norm,)
                ).fetchone()
                if cached and cached["hash"] == digest and int(cached["parser_version"]) == parser_version:
                    continue

                conn.execute("DELETE FROM symbols WHERE file_path=?", (rel_norm,))
                conn.execute("DELETE FROM imports WHERE file_path=?", (rel_norm,))
                for symbol in entry.get("symbols") or []:
                    name = str(symbol.get("name") or "").strip()
                    if not name:
                        continue
                    kind = str(symbol.get("kind") or "symbol")
                    line = int(symbol.get("line") or symbol.get("start") or 0)
                    sid = hashlib.sha1(f"{rel_norm}:{name}:{kind}:{line}".encode("utf-8")).hexdigest()
                    conn.execute(
                        "INSERT OR REPLACE INTO symbols(id, file_path, name, kind, line_start, line_end, exported, confidence) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (
                            sid,
                            rel_norm,
                            name,
                            kind,
                            line,
                            int(symbol.get("end") or line),
                            int(bool(symbol.get("exported"))),
                            "parsed",
                        ),
                    )
                for specifier in entry.get("imports") or []:
                    conn.execute(
                        "INSERT INTO imports(file_path, target_path, specifier, kind, line, confidence) "
                        "VALUES(?,?,?,?,?,?)",
                        (rel_norm, str(specifier), str(specifier), "import", 0, "heuristic"),
                    )
                conn.execute(
                    "INSERT OR REPLACE INTO index_cache(path, hash, parser_version, facts_hash, indexed_at) "
                    "VALUES(?,?,?,?,?)",
                    (rel_norm, digest, parser_version, "", now),
                )

            conn.execute("DELETE FROM files WHERE path NOT IN (SELECT path FROM current_paths)")
            conn.execute("DELETE FROM symbols WHERE file_path NOT IN (SELECT path FROM files)")
            conn.execute("DELETE FROM imports WHERE file_path NOT IN (SELECT path FROM files)")
            conn.execute("DELETE FROM index_cache WHERE path NOT IN (SELECT path FROM files)")
    finally:
        conn.close()
    return {"files": len(files_index), "db": db_path(ctx)}


def sync_links(ctx, links: list[dict], fks: list[dict], includes: list[dict]) -> dict:
    """Sincroniza tables/table_ops/fk_inferred/includes a partir do db:links."""
    conn = connect(ctx)
    try:
        with conn:
            for table in ("tables", "table_ops", "fk_inferred", "includes"):
                conn.execute(f"DELETE FROM {table}")
            names = sorted({str(link.get("table")) for link in links if link.get("table")})
            names += sorted(
                {str(fk.get("ref_table")) for fk in fks if fk.get("ref_table")}
            )
            for name in sorted(set(names)):
                conn.execute("INSERT OR IGNORE INTO tables(name) VALUES(?)", (name,))
            for link in links:
                table = str(link.get("table") or "")
                if not table:
                    continue
                operation = str(link.get("operation") or "read")
                conn.execute(
                    "INSERT INTO table_ops(table_name, file_path, line, op, access, sql, symbol, confidence) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (
                        table,
                        _norm(link.get("file") or ""),
                        int(link.get("line") or 0),
                        operation,
                        "write" if operation == "write" else "read",
                        str(link.get("snippet") or ""),
                        link.get("symbol"),
                        str(link.get("confidence") or ""),
                    ),
                )
            for fk in fks:
                conn.execute(
                    "INSERT INTO fk_inferred(from_table, to_table, columns_json, ref_columns_json, evidence, confidence) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        str(fk.get("table") or ""),
                        str(fk.get("ref_table") or ""),
                        json.dumps(fk.get("columns") or [], ensure_ascii=False),
                        json.dumps(fk.get("ref_columns") or [], ensure_ascii=False),
                        ", ".join(str(item) for item in (fk.get("evidence") or [])),
                        str(fk.get("confidence") or "inferred"),
                    ),
                )
            for item in includes:
                conn.execute(
                    "INSERT INTO includes(file_path, target_path, kind, line) VALUES(?,?,?,?)",
                    (
                        _norm(item.get("file") or ""),
                        str(item.get("target") or ""),
                        str(item.get("type") or "include"),
                        int(item.get("line") or 0),
                    ),
                )
    finally:
        conn.close()
    return {"tables": len(set(names)), "ops": len(links), "fks": len(fks), "includes": len(includes)}


def stats(ctx) -> dict:
    conn = connect(ctx)
    try:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in ("files", "symbols", "imports", "tables", "table_ops", "fk_inferred", "includes")
        }
        counts["db"] = db_path(ctx)
        counts["schema_version"] = SCHEMA_VERSION
        return counts
    finally:
        conn.close()


def impact_by_table(ctx, table: str) -> list[dict]:
    conn = connect(ctx)
    try:
        rows = conn.execute(
            "SELECT * FROM table_ops WHERE table_name=? ORDER BY access DESC, file_path, line",
            (table,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def impact_by_symbol(ctx, symbol: str) -> list[dict]:
    conn = connect(ctx)
    try:
        rows = conn.execute(
            "SELECT * FROM table_ops WHERE symbol LIKE ? ORDER BY file_path, line",
            (f"%{symbol}%",),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def files_by_surface(ctx, surface: str) -> list[dict]:
    conn = connect(ctx)
    try:
        rows = conn.execute(
            "SELECT * FROM files WHERE surface=? ORDER BY path", (surface,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
