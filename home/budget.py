"""Programme budget calculations derived from accepted application approvals."""

from decimal import Decimal


ZERO = Decimal("0")
PROGRAM_TRAVEL = "TRAVEL"
PROGRAM_RFG = "RFG"
PROGRAMS = (PROGRAM_TRAVEL, PROGRAM_RFG)

# Serializes programme-budget updates, approvals, and edits to accepted amounts.
_LOCK_ID = 2_026_091_401


def lock_ledger(cursor):
    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_LOCK_ID])


def table_exists(cursor):
    cursor.execute("SELECT to_regclass(%s)", ['public."PROGRAM_BUDGETS"'])
    return cursor.fetchone()[0] is not None


def load_total(cursor, program, *, for_update=False):
    if not table_exists(cursor):
        return None

    sql = 'SELECT "TOTAL_BUDGET" FROM "PROGRAM_BUDGETS" WHERE "PROGRAM" = %s'
    if for_update:
        sql += " FOR UPDATE"
    cursor.execute(sql, [program])
    row = cursor.fetchone()
    return row[0] if row else None


def approved_spending(cursor, *, exclude_application_id=None):
    """Current approved spend per programme, counting each application once."""
    params = []
    excluded = ""
    if exclude_application_id is not None:
        excluded = 'AND a."ID" <> %s'
        params.append(exclude_application_id)

    cursor.execute(f"""
        SELECT a."PROGRAM",
               COALESCE(SUM(GREATEST(current_approval."APPROVED_AMOUNT", 0)), 0)
        FROM "APPLICATIONS" a
        JOIN LATERAL (
            SELECT fa."APPROVED_AMOUNT"
            FROM "FINAL_APPROVALS" fa
            WHERE fa."APPLICATION_ID" = a."ID"
            ORDER BY fa."CREATED_AT" DESC NULLS LAST, fa."ID" DESC
            LIMIT 1
        ) current_approval ON TRUE
        WHERE a."STATUS" IN ('Accepted', 'Approved')
          AND a."PROGRAM" IN ('TRAVEL', 'RFG')
          {excluded}
        GROUP BY a."PROGRAM"
    """, params)

    spending = {PROGRAM_TRAVEL: ZERO, PROGRAM_RFG: ZERO}
    for program, amount in cursor.fetchall():
        spending[program] = amount or ZERO
    return spending


def available_for(cursor, total, program, *, exclude_application_id=None):
    spending = approved_spending(
        cursor, exclude_application_id=exclude_application_id)
    return total - spending.get(program, ZERO)


def minimum_total_for_current_approvals(cursor, program):
    spending = approved_spending(cursor)
    return spending.get(program, ZERO)


def save_total(cursor, program, total, updated_by, updated_at):
    cursor.execute("""
        INSERT INTO "PROGRAM_BUDGETS"
            ("PROGRAM", "TOTAL_BUDGET", "UPDATED_BY", "UPDATED_AT")
        VALUES (%s, %s, %s, %s)
        ON CONFLICT ("PROGRAM") DO UPDATE
        SET "TOTAL_BUDGET" = EXCLUDED."TOTAL_BUDGET",
            "UPDATED_BY" = EXCLUDED."UPDATED_BY",
            "UPDATED_AT" = EXCLUDED."UPDATED_AT"
    """, [program, total, updated_by, updated_at])


def format_money(value):
    return f"₹{value:,.2f}"


def summary(cursor, program):
    if not table_exists(cursor):
        return {"schema_ready": False, "configured": False}

    cursor.execute("""
        SELECT "TOTAL_BUDGET", "UPDATED_BY", "UPDATED_AT"
        FROM "PROGRAM_BUDGETS"
        WHERE "PROGRAM" = %s
    """, [program])
    row = cursor.fetchone()
    if not row:
        return {"schema_ready": True, "configured": False}

    total, updated_by, updated_at = row
    spending = approved_spending(cursor)
    spent = spending.get(program, ZERO)
    remaining = total - spent

    used_percent = 0
    if total > ZERO:
        used_percent = min(100, max(0, float(spent / total * 100)))

    return {
        "schema_ready": True,
        "configured": True,
        "total": total,
        "total_display": format_money(total),
        "spent": spent,
        "spent_display": format_money(spent),
        "remaining": remaining,
        "remaining_display": format_money(remaining),
        "used_percent": used_percent,
        "updated_by": updated_by,
        "updated_at": updated_at,
    }
