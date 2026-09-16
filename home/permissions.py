"""Programme-scoped permissions for Travel Support and RFG.

Travel and RFG may be run by different teams with some overlap, so a role is
held *per programme* rather than globally. Assignments live in
`USER_PROGRAM_ROLES` (one role per user per programme).

`USERS.ROLE` carries the account type: System Reviewer or the legacy value
`Reviewer`, which represents every standard account. Chairman, Reviewer,
Observer and Finance are programme roles in `USER_PROGRAM_ROLES`.
"""

from django.db import connection


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------
PROGRAM_TRAVEL = "TRAVEL"
PROGRAM_RFG = "RFG"
PROGRAMS = (PROGRAM_TRAVEL, PROGRAM_RFG)

PROGRAM_LABELS = {
    PROGRAM_TRAVEL: "Travel Support",
    PROGRAM_RFG: "Research Facilitation Grant",
}

ROLE_CHAIRMAN = "Chairman"
ROLE_REVIEWER = "Reviewer"
ROLE_OBSERVER = "Observer"
ROLE_FINANCE = "Finance"

SYSTEM_REVIEWER = "System Reviewer"
STANDARD_ACCOUNT_ROLE = "Reviewer"

FINANCE_ACCOUNTS = {
    "tg-finance": PROGRAM_TRAVEL,
    "rfg-finance": PROGRAM_RFG,
}
RESERVED_FINANCE_USERNAMES = set(FINANCE_ACCOUNTS)
_FINANCE_PROGRAM_UNSET = object()

# Statuses each programme role may communicate to the applicant. Mirrors the
# behaviour that used to live in home.views.NOTIFY_PERMISSIONS.
NOTIFY_PERMISSIONS = {
    ROLE_CHAIRMAN: {"Under Review", "Accepted", "Rejected"},
    ROLE_REVIEWER: {"Under Review"},
    ROLE_OBSERVER: set(),
}



# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_program_roles(user_id):
    """Read a user's programme roles from the database.

    Returns e.g. {"TRAVEL": "Chairman", "RFG": "Observer"}.
    """
    if not user_id:
        return {}

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT "PROGRAM", "ROLE"
            FROM "USER_PROGRAM_ROLES"
            WHERE "USER_ID" = %s
            """,
            [user_id],
        )
        return {program: role for program, role in cursor.fetchall()}


def program_roles(request):
    """The signed-in user's programme roles, read fresh from the database.

    Cached for the life of the request only, so a role change made in the admin
    UI applies on the user's very next page load rather than at their next
    login. There is deliberately no fallback to the legacy USERS.ROLE: falling
    back would silently re-grant access to a user whose programme roles had just
    been revoked.
    """
    cached = getattr(request, "_program_roles_cache", None)
    if cached is not None:
        return cached

    roles = load_program_roles(request.session.get("user_id"))
    request._program_roles_cache = roles
    return roles


def set_program_role(user_id, program, role):
    """Assign, change or clear one programme role for a user.

    An empty role clears the assignment. Invalid values are ignored rather than
    raising -- the database CHECK constraints are the real guard.
    """
    if program not in PROGRAMS:
        return
    if role and role not in (
            ROLE_CHAIRMAN, ROLE_REVIEWER, ROLE_OBSERVER, ROLE_FINANCE):
        return

    with connection.cursor() as cursor:
        if not role:
            cursor.execute(
                'DELETE FROM "USER_PROGRAM_ROLES" WHERE "USER_ID"=%s AND "PROGRAM"=%s',
                [user_id, program])
        else:
            cursor.execute("""
                INSERT INTO "USER_PROGRAM_ROLES" ("USER_ID", "PROGRAM", "ROLE")
                VALUES (%s, %s, %s)
                ON CONFLICT ("USER_ID", "PROGRAM")
                DO UPDATE SET "ROLE" = EXCLUDED."ROLE"
            """, [user_id, program, role])


def all_program_roles():
    """{user_id: {"TRAVEL": "Chairman", "RFG": "Observer"}} for the admin table."""
    out = {}
    with connection.cursor() as cursor:
        cursor.execute('SELECT "USER_ID", "PROGRAM", "ROLE" FROM "USER_PROGRAM_ROLES"')
        for user_id, program, role in cursor.fetchall():
            out.setdefault(user_id, {})[program] = role
    return out


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------
def role_for(request, program):
    """Role held in one programme, or None."""
    return program_roles(request).get(program)


def visible_programs(request):
    """Programmes whose applications this user may see at all.

    Always a list (never empty-as-None) so callers can pass it straight into a
    `WHERE "PROGRAM" = ANY(%s)` without special-casing.

    System Reviewer sees every programme for system oversight. Each Finance
    account sees only the programme fixed to its reserved username. Other
    standard users see the programmes assigned to them.
    """
    finance = finance_program(request)
    if finance is not None:
        return [finance]
    if is_system_reviewer(request):
        return list(PROGRAMS)
    return sorted(program_roles(request).keys())


def is_system_reviewer(request):
    return request.session.get("user_role") == SYSTEM_REVIEWER


def finance_program(request):
    """Programme managed by the signed-in Finance account, or ``None``.

    Finance is a programme role on a standard account, not a separate account
    type. The reserved username identifies which single programme that account
    may manage. Reading both tables fresh makes deactivation and role changes
    effective on the next request.
    """
    cached = getattr(request, "_finance_program_cache", _FINANCE_PROGRAM_UNSET)
    if cached is not _FINANCE_PROGRAM_UNSET:
        return cached

    user_id = request.session.get("user_id")
    if not user_id:
        request._finance_program_cache = None
        return None

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT "USERNAME", "ROLE", "STATUS"
            FROM "USERS"
            WHERE "ID" = %s
        """, [user_id])
        row = cursor.fetchone()

    program = FINANCE_ACCOUNTS.get(row[0]) if row else None
    if (row and program is not None
            and row[1] == STANDARD_ACCOUNT_ROLE
            and row[2] == "Active"
            and role_for(request, program) == ROLE_FINANCE):
        request._finance_program_cache = program
    else:
        request._finance_program_cache = None
    return request._finance_program_cache


def can_manage_acm_budget(request):
    """Whether this is one of the two programme-specific Finance accounts."""
    return finance_program(request) is not None


def can_view_budget(request):
    """Whether the user may view (read-only) the budget overview.

    Returns True for all authenticated internal users who are NOT Finance
    account holders (those use can_manage_acm_budget / budget_management view
    with full edit access). This covers Chairmen, Reviewers, Observers and
    System Reviewers.
    """
    if not request.session.get("user_id"):
        return False
    # Finance users use the full Budget Management page, not this read-only view
    if finance_program(request) is not None:
        return False
    return True


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------
def can_view(request, program):
    """Read access, including the Finance account's single programme."""
    finance = finance_program(request)
    if finance is not None:
        return program == finance
    if is_system_reviewer(request):
        return True
    return role_for(request, program) is not None


def can_review(request, program):
    """Submit a rating/feedback.

    Deliberately keyed on the programme role only: Observers and System
    Reviewers hold none, so both are denied.
    """
    if finance_program(request) is not None:
        return False
    return role_for(request, program) in (ROLE_CHAIRMAN, ROLE_REVIEWER)


def can_edit_budget(request, program):
    """Edit applicant-supplied budget fields for this programme."""
    if is_system_reviewer(request) or finance_program(request) is not None:
        return False
    return role_for(request, program) in (ROLE_CHAIRMAN, ROLE_REVIEWER)


def can_access_help(request):
    """Whether the user may access the Help page.

    Accessible to all users, including students, applicants, reviewers,
    chairpersons, finance, and system administrators.
    """
    return True


def can_decide(request, program):
    """Approve with an amount, or reject. Chairman only."""
    if finance_program(request) is not None:
        return False
    return role_for(request, program) == ROLE_CHAIRMAN


def marks_under_review(request, program):
    """Whether opening an application should flip it to Under Review.

    Reviewers only, matching the existing Travel behaviour.
    """
    if finance_program(request) is not None:
        return False
    return role_for(request, program) == ROLE_REVIEWER


def can_notify(request, program, status, notified_status):
    """Whether this user may send the pending notification for `status`."""
    if finance_program(request) is not None:
        return False
    if notified_status == status:
        return False
    role = role_for(request, program)
    if role is None:
        return False
    return status in NOTIFY_PERMISSIONS.get(role, set())


def is_observer(request, program):
    return role_for(request, program) == ROLE_OBSERVER
