"""One place where outbound notification mail is constructed.

Django's send_mail() cannot set a Reply-To header, and every notification needs
one. The From address is a Gmail account presented under a display name, so it
is not a real no-reply mailbox: without Reply-To an applicant who hits reply
lands in a personal inbox rather than wherever the committee actually reads
mail. Routing both send paths through here keeps that consistent.
"""

from django.conf import settings
from django.core.mail import EmailMessage


def send(subject, body, recipients, fail_silently=False):
    """Send one plain-text notification. Returns the number of messages sent.

    fail_silently mirrors Django's own meaning and is chosen per caller: the
    submission confirmations swallow failures because the application row is
    already committed, while the decision notification must raise so the
    NOTIFIED_AT/NOTIFIED_STATUS columns are not written for mail that never
    left.
    """
    if not recipients:
        return 0

    reply_to = [settings.REPLY_TO_EMAIL] if settings.REPLY_TO_EMAIL else None

    message = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=list(recipients),
        reply_to=reply_to,
    )
    return message.send(fail_silently=fail_silently)
