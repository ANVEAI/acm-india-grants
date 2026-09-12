from django.core.mail import send_mail
from django.conf import settings

def send_notification_email(subject, message, recipients):
    """
    Generic email sender
    """
    print("📧 Sending email...")
    print("To:", recipients)
    print("Subject:", subject)

    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipients,
        fail_silently=False,
    )
