from __future__ import annotations

from copy import deepcopy
from typing import Any


class FakeSupabaseClient:
    def __init__(self, tables: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.tables = deepcopy(tables or {})
        self.calls: list[dict[str, Any]] = []
        self.next_id = 1

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str | list[str]] | None = None,
        body: Any | None = None,
        prefer: str | None = None,
    ) -> Any:
        method = method.upper()
        table = path.strip("/")
        query = query or {}
        self.calls.append({"method": method, "path": table, "query": query, "body": body, "prefer": prefer})

        if method == "GET":
            rows = deepcopy(self.tables.get(table, []))
            rows = self._filter(rows, query)
            order = query.get("order")
            if isinstance(order, str) and order:
                rows = self._order(rows, order)
            limit = query.get("limit")
            if isinstance(limit, str):
                rows = rows[: int(limit)]
            return rows

        if method == "POST":
            row = deepcopy(body or {})
            row.setdefault("id", f"fake-{self.next_id}")
            if table == "tasks":
                row.setdefault("status", "draft")
            self.next_id += 1
            self.tables.setdefault(table, []).append(row)
            return [deepcopy(row)] if prefer != "return=minimal" else None

        if method == "PATCH":
            rows = self._filter(self.tables.get(table, []), query)
            for row in rows:
                row.update(body or {})
            return [deepcopy(row) for row in rows]

        if method == "DELETE":
            before = self.tables.get(table, [])
            matched_ids = {row.get("id") for row in self._filter(before, query)}
            self.tables[table] = [row for row in before if row.get("id") not in matched_ids]
            return None

        raise AssertionError(f"Unexpected method {method}")

    def _filter(self, rows: list[dict[str, Any]], query: dict[str, str | list[str]]) -> list[dict[str, Any]]:
        filtered = rows
        for key, value in query.items():
            if key in {"select", "order", "limit", "on_conflict"}:
                continue
            if not isinstance(value, str):
                continue
            if value.startswith("eq."):
                expected = value[3:]
                filtered = [row for row in filtered if str(row.get(key)).lower() == expected.lower()]
            elif value.startswith("lt."):
                expected = value[3:]
                filtered = [row for row in filtered if str(row.get(key, "")) < expected]
            elif value.startswith("ilike.*") and value.endswith("*"):
                needle = value[7:-1].lower()
                filtered = [row for row in filtered if needle in str(row.get(key, "")).lower()]
            elif value.startswith("cs.{") and value.endswith("}"):
                needle = value[4:-1]
                filtered = [row for row in filtered if needle in (row.get(key) or [])]
        return filtered

    def _order(self, rows: list[dict[str, Any]], order: str) -> list[dict[str, Any]]:
        ordered = rows
        for clause in reversed([part.strip() for part in order.split(",") if part.strip()]):
            column, _, direction = clause.partition(".")
            reverse = direction.lower() == "desc"
            ordered = sorted(ordered, key=lambda row: row.get(column) or "", reverse=reverse)
        return ordered
