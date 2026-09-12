"""Programme-scoped permissions for Travel Support and RFG.

Travel and RFG may be run by different teams with some overlap, so a role is
held *per programme* rather than globally. Assignments live in
`USER_PROGRAM_ROLES` (one role per user per programme).

`USERS.ROLE` is deliberately left alone: it keeps serving the global
'System Reviewer' user-administration capability, which is not a programme role
and has never been able to review, decide or notify.
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

SYSTEM_REVIEWER = "System Reviewer"

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
    if role and role not in (ROLE_CHAIRMAN, ROLE_REVIEWER, ROLE_OBSERVER):
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

    System Reviewer sees every programme: it administers users and needs
    oversight of the whole system, but holds no reviewing or deciding power
    anywhere (see can_review / can_decide / can_notify below).
    """
    if is_system_reviewer(request):
        return list(PROGRAMS)
    return sorted(program_roles(request).keys())


def is_system_reviewer(request):
    return request.session.get("user_role") == SYSTEM_REVIEWER


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------
def can_view(request, program):
    """Read access. System Reviewer has it everywhere; nothing else follows."""
    if is_system_reviewer(request):
        return True
    return role_for(request, program) is not None


def can_review(request, program):
    """Submit a rating/feedback.

    Deliberately keyed on the programme role only: Observers and System
    Reviewers hold none, so both are denied.
    """
    return role_for(request, program) in (ROLE_CHAIRMAN, ROLE_REVIEWER)


def can_decide(request, program):
    """Approve with an amount, or reject. Chairman only."""
    return role_for(request, program) == ROLE_CHAIRMAN


def marks_under_review(request, program):
    """Whether opening an application should flip it to Under Review.

    Reviewers only, matching the existing Travel behaviour.
    """
    return role_for(request, program) == ROLE_REVIEWER


def can_notify(request, program, status, notified_status):
    """Whether this user may send the pending notification for `status`."""
    if notified_status == status:
        return False
    role = role_for(request, program)
    if role is None:
        return False
    return status in NOTIFY_PERMISSIONS.get(role, set())


def is_observer(request, program):
    return role_for(request, program) == ROLE_OBSERVER
