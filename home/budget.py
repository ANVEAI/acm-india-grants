"""ACM budget calculations derived from accepted application approvals."""

from decimal import Decimal


ZERO = Decimal("0")
PROGRAM_TRAVEL = "TRAVEL"
PROGRAM_RFG = "RFG"
PROGRAMS = (PROGRAM_TRAVEL, PROGRAM_RFG)

# Serializes total-budget updates, approvals, and edits to accepted amounts.
_LOCK_ID = 2_026_091_401


def lock_ledger(cursor):
    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_LOCK_ID])


def table_exists(cursor):
    cursor.execute("SELECT to_regclass(%s)", ['public."ACM_BUDGET"'])
    return cursor.fetchone()[0] is not None


def load_total(cursor, *, for_update=False):
    if not table_exists(cursor):
        return None

    sql = 'SELECT "TOTAL_BUDGET" FROM "ACM_BUDGET" WHERE "ID" = 1'
    if for_update:
        sql += " FOR UPDATE"
    cursor.execute(sql)
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
        WHERE a."STATUS" = 'Accepted'
          AND a."PROGRAM" IN ('TRAVEL', 'RFG')
          {excluded}
        GROUP BY a."PROGRAM"
    """, params)

    spending = {PROGRAM_TRAVEL: ZERO, PROGRAM_RFG: ZERO}
    for program, amount in cursor.fetchall():
        spending[program] = amount or ZERO
    return spending


def assigned_budget(total):
    return total / Decimal("2")


def available_for(cursor, total, program, *, exclude_application_id=None):
    spending = approved_spending(
        cursor, exclude_application_id=exclude_application_id)
    return assigned_budget(total) - spending.get(program, ZERO)


def minimum_total_for_current_approvals(cursor):
    spending = approved_spending(cursor)
    return max(spending.values()) * Decimal("2")


def save_total(cursor, total, updated_by, updated_at):
    cursor.execute("""
        INSERT INTO "ACM_BUDGET"
            ("ID", "TOTAL_BUDGET", "UPDATED_BY", "UPDATED_AT")
        VALUES (1, %s, %s, %s)
        ON CONFLICT ("ID") DO UPDATE
        SET "TOTAL_BUDGET" = EXCLUDED."TOTAL_BUDGET",
            "UPDATED_BY" = EXCLUDED."UPDATED_BY",
            "UPDATED_AT" = EXCLUDED."UPDATED_AT"
    """, [total, updated_by, updated_at])


def format_money(value):
    return f"₹{value:,.2f}"


def summary(cursor):
    if not table_exists(cursor):
        return {"schema_ready": False, "configured": False}

    cursor.execute("""
        SELECT "TOTAL_BUDGET", "UPDATED_BY", "UPDATED_AT"
        FROM "ACM_BUDGET"
        WHERE "ID" = 1
    """)
    row = cursor.fetchone()
    if not row:
        return {"schema_ready": True, "configured": False}

    total, updated_by, updated_at = row
    assigned = assigned_budget(total)
    spending = approved_spending(cursor)
    travel_remaining = assigned - spending[PROGRAM_TRAVEL]
    rfg_remaining = assigned - spending[PROGRAM_RFG]
    total_remaining = total - spending[PROGRAM_TRAVEL] - spending[PROGRAM_RFG]

    def used_percent(spent):
        if assigned <= ZERO:
            return 0
        return min(100, max(0, float(spent / assigned * 100)))

    return {
        "schema_ready": True,
        "configured": True,
        "total": total,
        "total_display": format_money(total),
        "assigned_travel_display": format_money(assigned),
        "assigned_rfg_display": format_money(assigned),
        "spent_travel_display": format_money(spending[PROGRAM_TRAVEL]),
        "spent_rfg_display": format_money(spending[PROGRAM_RFG]),
        "remaining_travel": travel_remaining,
        "remaining_rfg": rfg_remaining,
        "remaining_travel_display": format_money(travel_remaining),
        "remaining_rfg_display": format_money(rfg_remaining),
        "total_remaining": total_remaining,
        "total_remaining_display": format_money(total_remaining),
        "travel_used_percent": used_percent(spending[PROGRAM_TRAVEL]),
        "rfg_used_percent": used_percent(spending[PROGRAM_RFG]),
        "updated_by": updated_by,
        "updated_at": updated_at,
    }
