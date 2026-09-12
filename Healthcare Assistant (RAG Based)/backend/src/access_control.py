"""
Role-based access control + SQL validation for the patient-records agent.

Two independent layers of defense are provided:

1. `validate_sql`     - a strict, allow-list based validator that inspects any
                         SQL string (whether hand-written or LLM-generated)
                         before it is ever executed against SQLite. This is
                         defense-in-depth on top of PatientDatabase.execute's
                         own basic checks: it parses the statement with
                         `sqlparse`, rejects anything that is not a single
                         read-only SELECT against the known table/columns,
                         and rejects SQL-injection patterns (stacked
                         statements, comments, UNION-based exfiltration,
                         PRAGMA/ATTACH, etc.).

2. `Role` / `filter_columns_for_role` - a simple RBAC layer that maps a
                         caller-supplied role to the set of patient columns
                         they are allowed to see, and redacts everything
                         else from query results before they reach the LLM
                         summarizer or the client. This keeps a "front desk"
                         role, for example, from ever seeing billing or
                         clinical detail, independent of what SQL was run.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Dict, Any

import sqlparse
from sqlparse.sql import IdentifierList, Identifier
from sqlparse.tokens import Keyword, DML

# ---------------------------------------------------------------------------
# Schema allow-list
# ---------------------------------------------------------------------------
ALLOWED_TABLE = "patients"
ALLOWED_COLUMNS = {
    "name", "age", "gender", "blood_type", "medical_condition",
    "date_of_admission", "doctor", "hospital", "insurance_provider",
    "billing_amount", "room_number", "admission_type", "discharge_date",
    "medication", "test_results",
}

# Statement-level keywords that must never appear anywhere in the SQL,
# regardless of case or how it's parsed. Blocks writes, schema changes,
# multi-statement/stacked-query injection, and metadata probing.
FORBIDDEN_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "attach", "detach", "pragma", "vacuum", "reindex", "grant", "revoke",
    "into", "union", "exec", "execute", "load_extension",
}

MAX_ROWS_ALLOWED = 200


class SQLValidationError(ValueError):
    """Raised when a generated/user SQL statement fails RBAC/safety checks."""


@dataclass
class SQLValidationResult:
    sql: str
    warnings: List[str]


def _strip_comments(sql: str) -> str:
    # sqlparse.format also strips comments but we do a manual pass first so
    # that we can also flag their presence as a suspicious signal.
    return re.sub(r"(--[^\n]*)|(/\*.*?\*/)", " ", sql, flags=re.DOTALL)


def validate_sql(sql: str, allowed_columns: Iterable[str] | None = None) -> SQLValidationResult:
    """
    Validate a candidate SQL string before execution.

    Raises SQLValidationError with a human-readable reason on any violation.
    Returns a SQLValidationResult with the (lightly normalized) SQL and any
    non-fatal warnings on success.
    """
    if not sql or not sql.strip():
        raise SQLValidationError("Empty SQL statement.")

    raw = sql.strip().rstrip(";")
    had_comment = bool(re.search(r"(--)|(/\*)", raw))
    cleaned = _strip_comments(raw).strip()

    if ";" in cleaned:
        raise SQLValidationError("Stacked/multiple statements are not allowed.")

    parsed = sqlparse.parse(cleaned)
    if len(parsed) != 1:
        raise SQLValidationError("Exactly one SQL statement is required.")

    statement = parsed[0]
    stype = statement.get_type()
    if stype != "SELECT":
        raise SQLValidationError(f"Only SELECT statements are allowed (got {stype}).")

    low = cleaned.lower()
    tokens = set(re.findall(r"[a-zA-Z_]+", low))
    hit = tokens & FORBIDDEN_KEYWORDS
    if hit:
        raise SQLValidationError(f"Forbidden keyword(s) detected: {', '.join(sorted(hit))}")

    if ALLOWED_TABLE not in low:
        raise SQLValidationError(f"Query must select from the '{ALLOWED_TABLE}' table.")

    no_literals_for_star_check = re.sub(r"'(?:[^']|'')*'", "''", cleaned)
    select_clause = re.match(r"select\s+(distinct\s+)?(.*?)\s+from\s", no_literals_for_star_check,
                              re.IGNORECASE | re.DOTALL)
    if select_clause and "*" in select_clause.group(2):
        raise SQLValidationError(
            "Wildcard 'SELECT *' is not allowed; the query must name explicit, "
            "role-permitted columns."
        )

    # Column allow-list: pull every bare identifier out of the statement and
    # make sure it's either a known column, the table name, a SQL keyword,
    # a numeric literal, or a function name (count/sum/avg/min/max) used for
    # aggregation. Anything else (e.g. sqlite_master, a hidden column, an
    # attempt to reference another table) is rejected.
    permitted_cols = set(allowed_columns) if allowed_columns is not None else ALLOWED_COLUMNS
    safe_extra = {
        "select", "from", "where", "and", "or", "not", "like", "in", "is",
        "null", "limit", "order", "by", "group", "having", "asc", "desc",
        "as", "distinct", "count", "sum", "avg", "min", "max", "between",
        ALLOWED_TABLE,
    }
    # Strip out string-literal contents before scanning for identifiers, so
    # that values inside quotes (e.g. WHERE name LIKE '%Smith%') aren't
    # mistaken for unrecognized column/table references.
    identifiers = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", no_literals_for_star_check)
    for ident in identifiers:
        low_ident = ident.lower()
        if low_ident in safe_extra or low_ident in permitted_cols:
            continue
        if low_ident in ALLOWED_COLUMNS:
            # Column exists in the schema but not for this role.
            raise SQLValidationError(
                f"Column '{ident}' is not permitted for the current role."
            )
        # Unknown identifier entirely (typo, injected table/column, function
        # we don't recognise as safe). Reject rather than silently execute.
        raise SQLValidationError(f"Unrecognized identifier in query: '{ident}'")

    if "limit" not in low:
        cleaned = f"{cleaned} LIMIT {MAX_ROWS_ALLOWED}"
    else:
        m = re.search(r"limit\s+(\d+)", low)
        if m and int(m.group(1)) > MAX_ROWS_ALLOWED:
            cleaned = re.sub(r"limit\s+\d+", f"LIMIT {MAX_ROWS_ALLOWED}", cleaned, flags=re.IGNORECASE)

    warnings = []
    if had_comment:
        warnings.append("Comments were stripped from the query before execution.")

    return SQLValidationResult(sql=cleaned, warnings=warnings)


# ---------------------------------------------------------------------------
# Role-based column access
# ---------------------------------------------------------------------------
class Role:
    ADMIN = "admin"
    CLINICIAN = "clinician"
    BILLING = "billing"
    FRONT_DESK = "front_desk"

    ALL = {ADMIN, CLINICIAN, BILLING, FRONT_DESK}
    DEFAULT = FRONT_DESK


# Columns each role may see. Admin sees everything. Every other role is
# scoped to the minimum necessary for its job (HIPAA "minimum necessary"
# principle), matching the hospital's own HIPAA policy doc.
ROLE_COLUMN_ACCESS: Dict[str, set] = {
    Role.ADMIN: set(ALLOWED_COLUMNS),
    Role.CLINICIAN: ALLOWED_COLUMNS - {"billing_amount", "insurance_provider"},
    Role.BILLING: {
        "name", "insurance_provider", "billing_amount", "admission_type",
        "date_of_admission", "discharge_date", "hospital",
    },
    Role.FRONT_DESK: {
        "name", "room_number", "doctor", "hospital", "admission_type",
        "date_of_admission", "discharge_date",
    },
}

# Roles allowed to use the patient-records agent at all. (Kept as a hook for
# future roles, e.g. "guest", that should be denied outright.)
ROLES_WITH_SQL_ACCESS = {Role.ADMIN, Role.CLINICIAN, Role.BILLING, Role.FRONT_DESK}


def normalize_role(role: str | None) -> str:
    role = (role or "").strip().lower()
    return role if role in Role.ALL else Role.DEFAULT


def columns_for_role(role: str) -> set:
    return ROLE_COLUMN_ACCESS.get(role, ROLE_COLUMN_ACCESS[Role.DEFAULT])


def filter_columns_for_role(rows: List[Dict[str, Any]], role: str) -> List[Dict[str, Any]]:
    """Redact any column not permitted for `role` from each result row."""
    allowed = columns_for_role(role)
    return [{k: v for k, v in row.items() if k in allowed} for row in rows]


def has_sql_access(role: str) -> bool:
    return role in ROLES_WITH_SQL_ACCESS
