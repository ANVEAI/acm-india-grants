"""Research Facilitation Grant: validation and field mapping.

Kept out of backend/views.py, which is already long. This module owns the
programme-specific rules; the view keeps owning the transaction, the file
writes and the tracking code, so both programmes share that machinery.

Field mapping: an RFG application is stored as an APPLICATIONS row (the spine)
plus one RFG_DETAILS row. Several RFG answers map onto existing spine columns
rather than being duplicated -- see SPINE_NOTES below.
"""

from datetime import datetime

from django.conf import settings


SCHEME_OPEN_ACCESS = "OPEN_ACCESS"
SCHEME_EXTRA_PAGE = "EXTRA_PAGE"
SCHEME_INVITATION = "INVITATION"
SCHEMES = (SCHEME_OPEN_ACCESS, SCHEME_EXTRA_PAGE, SCHEME_INVITATION)
PAPER_SCHEMES = (SCHEME_OPEN_ACCESS, SCHEME_EXTRA_PAGE)

SCHEME_LABELS = {
    SCHEME_OPEN_ACCESS: "Open access charges for accepted paper",
    SCHEME_EXTRA_PAGE: "Extra page charges for accepted paper",
    SCHEME_INVITATION: "Invitation-only seminar / school",
}

# Approval ceiling. Applicants may REQUEST more than this (the applicant-facing
# form never mentions a cap); the Chairman cannot APPROVE above it.
RFG_APPROVAL_CAP = 60000

# The Google Form specified 1 MB, which rejected ordinary scanned letters.
# The portal applies one ceiling across both programmes instead; see
# settings.MAX_UPLOAD_BYTES for why that number is what it is.
RFG_MAX_UPLOAD_BYTES = settings.MAX_UPLOAD_BYTES

SPINE_NOTES = """
  conference/journal name or seminar name -> APPLICATIONS.CONFERENCE_NAME
  event location                          -> APPLICATIONS.CONFERENCE_VENUE
  event start/end                         -> APPLICATIONS.CONFERENCE_START/END_DATE
  paper title                             -> APPLICATIONS.PAPER_TITLE
  acceptance / invitation letter          -> APPLICATIONS.ACCEPTANCE_LETTER_PATH
  amount requested                        -> APPLICATIONS.TRAVEL_BUDGET
  justification                           -> APPLICATIONS.BUDGET_JUSTIFICATION
"""


REQUIRED_COMMON = {
    "rfg_correspondence_email": "Correspondence email",
    "rfg_affiliation_status": "Affiliation status",
    "rfg_previous": "Previous grant answer",
    "rfg_amount": "Amount requested",
    "rfg_justification": "Justification",
}

REQUIRED_PAPER = {
    "rfg_paper_title": "Paper title",
    "rfg_paper_authors": "List of authors",
    "rfg_venue_name": "Conference or journal name",
    "rfg_venue_url": "Conference or journal URL",
    "rfg_paper_pdf_url": "Paper PDF URL",
}

REQUIRED_INVITATION = {
    "rfg_event_name": "Event name",
    "rfg_organizer_name": "Organizer name",
    "rfg_organizer_affiliation": "Organizer affiliation",
    "rfg_organizer_email": "Organizer email",
    "rfg_event_location": "Event location",
    "rfg_event_start": "Event start date",
    "rfg_event_end": "Event end date",
}

# Deliberately not required: the applicant already gives a total amount and a
# justification, and the committee can ask for a breakup if it wants one.


def _text(data, field):
    return (data.get(field) or "").strip()


def validate(data, files, validate_upload):
    """Validate an RFG submission.

    `validate_upload(file, label, max_bytes, errors, field)` is passed in so the
    same PDF/size rule is used for both programmes.

    Returns (errors, scheme).
    """
    errors = {}
    scheme = _text(data, "rfg_scheme").upper()

    if scheme not in SCHEMES:
        errors["rfg_scheme"] = "Please choose a scheme"
        return errors, None

    required = dict(REQUIRED_COMMON)
    required.update(REQUIRED_PAPER if scheme in PAPER_SCHEMES else REQUIRED_INVITATION)

    for field, label in required.items():
        if not _text(data, field):
            errors[field] = f"{label} is required"

    # Multi-selects: "Other" free text counts as a department.
    if not data.getlist("rfg_departments") and not _text(data, "rfg_department_other"):
        errors["rfg_departments"] = "Select at least one department"

    if scheme == SCHEME_INVITATION and not data.getlist("rfg_grant_heads"):
        errors["rfg_grant_heads"] = "Select at least one grant head"

    # Details of a prior award are only relevant if there was one.
    if _text(data, "rfg_previous") == "Yes" and not _text(data, "rfg_previous_details"):
        errors["rfg_previous_details"] = "Previous grant details are required"

    # Amount must be a usable number: the cap check, the export and the
    # Chairman's decision all need a figure, not prose.
    raw_amount = _text(data, "rfg_amount")
    if raw_amount and "rfg_amount" not in errors:
        try:
            if float(raw_amount) <= 0:
                errors["rfg_amount"] = "Amount requested must be greater than zero"
        except ValueError:
            errors["rfg_amount"] = "Amount requested must be a number"

    # Event dates, invitation scheme only.
    if scheme == SCHEME_INVITATION:
        parsed = {}
        for field, label in (("rfg_event_start", "Event start date"),
                             ("rfg_event_end", "Event end date")):
            raw = _text(data, field)
            if raw and field not in errors:
                try:
                    parsed[field] = datetime.strptime(raw, "%Y-%m-%d").date()
                except ValueError:
                    errors[field] = f"{label} must be a valid date (YYYY-MM-DD)"
        if len(parsed) == 2 and parsed["rfg_event_end"] < parsed["rfg_event_start"]:
            errors["rfg_event_end"] = "Event end date cannot be before the start date"

    # Uploads. Paper schemes need the acceptance letter plus the charges
    # document; the invitation scheme needs the invitation letter.
    if scheme in PAPER_SCHEMES:
        validate_upload(files.get("rfg_acceptance_letter"), "Acceptance letter",
                        RFG_MAX_UPLOAD_BYTES, errors, "rfg_acceptance_letter")
        validate_upload(files.get("rfg_charges_doc"), "Charges document",
                        RFG_MAX_UPLOAD_BYTES, errors, "rfg_charges_doc")
    else:
        validate_upload(files.get("rfg_invitation_letter"), "Invitation letter",
                        RFG_MAX_UPLOAD_BYTES, errors, "rfg_invitation_letter")

    return errors, scheme


def spine_values(data, scheme):
    """The APPLICATIONS columns an RFG application fills.

    Travel-only columns are left as None -- that is exactly what the
    programme-conditional CHECK constraint permits.
    """
    is_paper = scheme in PAPER_SCHEMES

    return {
        "conference_name": (_text(data, "rfg_venue_name") if is_paper
                            else _text(data, "rfg_event_name")),
        "conference_venue": None if is_paper else _text(data, "rfg_event_location"),
        "conference_start_date": None if is_paper else (_text(data, "rfg_event_start") or None),
        "conference_end_date": None if is_paper else (_text(data, "rfg_event_end") or None),
        "conference_website": (_text(data, "rfg_venue_url") if is_paper
                               else _text(data, "rfg_event_url")),
        "paper_title": _text(data, "rfg_paper_title") if is_paper else None,
        "travel_budget": float(_text(data, "rfg_amount") or 0),
        "budget_justification": _text(data, "rfg_justification"),
    }


def detail_values(data, scheme):
    """The RFG_DETAILS columns, excluding file paths (set after the files land)."""
    departments = list(data.getlist("rfg_departments"))
    other_dept = _text(data, "rfg_department_other")
    if other_dept:
        departments.append(other_dept)

    return {
        "scheme": scheme,
        "correspondence_email": _text(data, "rfg_correspondence_email"),
        "departments": ", ".join(departments),
        "affiliation_status": _text(data, "rfg_affiliation_status"),
        "student_type": _text(data, "rfg_student_type"),
        "faculty_contact_name": _text(data, "rfg_faculty_name"),
        "faculty_contact_email": _text(data, "rfg_faculty_email"),
        "previous_rfg": _text(data, "rfg_previous") == "Yes",
        "previous_rfg_details": _text(data, "rfg_previous_details"),
        "paper_authors": _text(data, "rfg_paper_authors"),
        "publication_venue_url": _text(data, "rfg_venue_url"),
        "paper_pdf_url": _text(data, "rfg_paper_pdf_url"),
        "event_url": _text(data, "rfg_event_url"),
        "organizer_name": _text(data, "rfg_organizer_name"),
        "organizer_affiliation": _text(data, "rfg_organizer_affiliation"),
        "organizer_email": _text(data, "rfg_organizer_email"),
        "grant_heads": ", ".join(data.getlist("rfg_grant_heads")),
        "amount_breakdown": _text(data, "rfg_amount_breakdown"),
    }


def tracking_prefix_source(data, scheme):
    """Text the tracking code's initials are derived from."""
    if scheme in PAPER_SCHEMES:
        return _text(data, "rfg_venue_name")
    return _text(data, "rfg_event_name")
