"""Canonical SQLite schema evidence for the independently shipped numeric revisions."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import cast

from sqlalchemy import Connection

# SQLite does not expose CHECK expressions, conflict modes or collations via
# table_info. Read the DDL as tokens, including literal text, so these matter.
_SQL_TOKENS = re.compile(
    r"""--[^\n]*|/\*.*?\*/|'(?:''|[^'])*'|"(?:""|[^"])*"|\x60(?:\x60\x60|[^\x60])*\x60|\[[^\]]*\]|[\w$]+|[^\s]""",
    re.DOTALL,
)
_TABLE_CONSTRAINT = {"CHECK", "CONSTRAINT", "FOREIGN", "PRIMARY", "UNIQUE"}


def _tokens(sql: str) -> list[str]:
    result = []
    for token in _SQL_TOKENS.findall(sql):
        if token.startswith(("--", "/*")):
            continue
        if token[0] == "'":
            result.append(token)
        elif token[0] in {'"', chr(96), "["}:
            quote = token[-1]
            result.append(token[1:-1].replace(quote * 2, quote).upper())
        else:
            result.append(token.upper())
    return result


def _canonical_table(sql: str) -> list[list[str]]:
    # During an Alembic batch rewrite SQLAlchemy may emit independent named
    # constraints in a different order. Preserve column order and every clause.
    tokens = _tokens(sql)
    start = tokens.index("(")
    columns: list[list[str]] = []
    constraints: list[list[str]] = []
    clause: list[str] = []
    depth = 0
    for index in range(start + 1, len(tokens)):
        token = tokens[index]
        if depth == 0 and token in {",", ")"}:
            if not clause:
                raise ValueError("Empty column declaration")
            (constraints if clause[0] in _TABLE_CONSTRAINT else columns).append(clause)
            clause = []
            if token == ")":
                return [tokens[:start], *columns, *sorted(constraints), tokens[index + 1 :]]
            continue
        clause.append(token)
        depth += int(token == "(") - int(token == ")")
    raise ValueError("Incomplete table declaration")


def digest(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def sqlite_table_signatures(connection: Connection) -> dict[str, str]:
    rows = connection.exec_driver_sql(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT GLOB 'sqlite_*' AND tbl_name != 'alembic_version' ORDER BY type, name"
    )
    tables: dict[str, list[list[str]]] = {}
    attached: dict[str, list[list[str]]] = defaultdict(list)
    for row in rows:
        kind, name, table, sql = cast(tuple[str, str, str, str | None], tuple(row))
        if sql is None:
            raise ValueError("SQLite did not report a schema definition")
        if kind == "table":
            tables[name] = _canonical_table(sql)
        else:
            attached[table].append([kind, name, *_tokens(sql)])
    return {
        name: digest([tables.get(name), sorted(attached.get(name, []))])
        for name in tables.keys() | attached.keys()
    }


def changed_tables(
    base: Mapping[str, str], steps: Mapping[str, Mapping[str, str]], heads: Sequence[str]
) -> dict[str, str]:
    expected = dict(base)
    for head in heads:
        past = head.rpartition("_")[0]
        for step, changes in steps.items():
            if step.rpartition("_")[0] == past and step <= head:
                expected.update(changes)
    return expected
