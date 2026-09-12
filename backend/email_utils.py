"""
Email utility module for sending emails in the Travel Grant application.
Provides helper functions for sending various types of emails.
"""

from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
import logging

logger = logging.getLogger('django')


def send_simple_email(subject, message, recipient_list, from_email=None):
    """
    Send a simple plain text email.
    
    Args:
        subject (str): Email subject
        message (str): Email body (plain text)
        recipient_list (list): List of recipient email addresses
        from_email (str, optional): Sender email. Defaults to DEFAULT_FROM_EMAIL
    
    Returns:
        int: Number of emails sent, 0 if failed
    """
    if from_email is None:
        from_email = settings.DEFAULT_FROM_EMAIL
    
    try:
        result = send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=recipient_list,
            fail_silently=False,
        )
        logger.info(f"Email sent successfully to {recipient_list}")
        return result
    except Exception as e:
        logger.error(f"Failed to send email to {recipient_list}: {str(e)}")
        return 0


def send_html_email(subject, html_message, recipient_list, text_message=None, from_email=None):
    """
    Send an HTML email with optional plain text fallback.
    
    Args:
        subject (str): Email subject
        html_message (str): Email body (HTML format)
        recipient_list (list): List of recipient email addresses
        text_message (str, optional): Plain text fallback. Auto-generated if not provided
        from_email (str, optional): Sender email. Defaults to DEFAULT_FROM_EMAIL
    
    Returns:
        int: Number of emails sent, 0 if failed
    """
    if from_email is None:
        from_email = settings.DEFAULT_FROM_EMAIL
    
    if text_message is None:
        text_message = strip_tags(html_message)
    
    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=from_email,
            to=recipient_list,
        )
        email.attach_alternative(html_message, "text/html")
        result = email.send(fail_silently=False)
        logger.info(f"HTML email sent successfully to {recipient_list}")
        return result
    except Exception as e:
        logger.error(f"Failed to send HTML email to {recipient_list}: {str(e)}")
        return 0


def send_template_email(template_name, context, subject, recipient_list, from_email=None):
    """
    Send an email using a Django template.
    
    Args:
        template_name (str): Path to email template (e.g., 'emails/welcome.html')
        context (dict): Context variables for template rendering
        subject (str): Email subject
        recipient_list (list): List of recipient email addresses
        from_email (str, optional): Sender email. Defaults to DEFAULT_FROM_EMAIL
    
    Returns:
        int: Number of emails sent, 0 if failed
    """
    if from_email is None:
        from_email = settings.DEFAULT_FROM_EMAIL
    
    try:
        logger.info(f"[EMAIL] SENDING TEMPLATE EMAIL")
        logger.info(f"  Subject: {subject}")
        logger.info(f"  From: {from_email}")
        logger.info(f"  To: {recipient_list}")
        logger.info(f"  Template: {template_name}")
        logger.info(f"  Email Host: {settings.EMAIL_HOST}")
        logger.info(f"  Email Port: {settings.EMAIL_PORT}")
        logger.info(f"  Email Backend: {settings.EMAIL_BACKEND}")
        
        html_message = render_to_string(template_name, context)
        text_message = strip_tags(html_message)
        
        logger.info(f"  Template rendered successfully ({len(html_message)} chars)")
        
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=from_email,
            to=recipient_list,
        )
        email.attach_alternative(html_message, "text/html")
        
        logger.info(f"  EmailMultiAlternatives object created")
        logger.info(f"  Attempting to send email...")
        
        result = email.send(fail_silently=False)
        
        logger.info(f"[SUCCESS] EMAIL SENT SUCCESSFULLY")
        logger.info(f"[SUCCESS] Result: {result} email(s) sent")
        logger.info(f"Email sent successfully to {recipient_list}")
        return result
    except Exception as e:
        logger.error(f"[FAILED] FAILED TO SEND TEMPLATE EMAIL: {str(e)}")
        logger.error(f"  Subject: {subject}")
        logger.error(f"  Recipients: {recipient_list}")
        logger.error(f"  Template: {template_name}")
        logger.error(f"  Error Type: {type(e).__name__}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        logger.error(f"Failed to send template email to {recipient_list}: {str(e)}")
        return 0


def send_email_with_attachments(subject, message, recipient_list, attachments=None, 
                               html_message=None, from_email=None):
    """
    Send an email with file attachments.
    
    Args:
        subject (str): Email subject
        message (str): Email body (plain text)
        recipient_list (list): List of recipient email addresses
        attachments (list, optional): List of file paths to attach
        html_message (str, optional): HTML version of email body
        from_email (str, optional): Sender email. Defaults to DEFAULT_FROM_EMAIL
    
    Returns:
        int: Number of emails sent, 0 if failed
    """
    if from_email is None:
        from_email = settings.DEFAULT_FROM_EMAIL
    
    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=message,
            from_email=from_email,
            to=recipient_list,
        )
        
        if html_message:
            email.attach_alternative(html_message, "text/html")
        
        # Attach files
        if attachments:
            for file_path in attachments:
                try:
                    with open(file_path, 'rb') as attachment:
                        email.attach(
                            filename=file_path.split('/')[-1],
                            content=attachment.read(),
                        )
                except FileNotFoundError:
                    logger.warning(f"Attachment file not found: {file_path}")
        
        result = email.send(fail_silently=False)
        logger.info(f"Email with attachments sent to {recipient_list}")
        return result
    except Exception as e:
        logger.error(f"Failed to send email with attachments to {recipient_list}: {str(e)}")
        return 0


def send_bulk_email(subject, message, recipient_list, from_email=None, html_message=None):
    """
    Send bulk emails efficiently.
    
    Args:
        subject (str): Email subject
        message (str): Email body (plain text)
        recipient_list (list): List of recipient email addresses
        from_email (str, optional): Sender email. Defaults to DEFAULT_FROM_EMAIL
        html_message (str, optional): HTML version of email body
    
    Returns:
        int: Number of emails sent, 0 if failed
    """
    if from_email is None:
        from_email = settings.DEFAULT_FROM_EMAIL
    
    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=message,
            from_email=from_email,
            to=recipient_list,
        )
        
        if html_message:
            email.attach_alternative(html_message, "text/html")
        
        result = email.send(fail_silently=False)
        logger.info(f"Bulk email sent to {len(recipient_list)} recipients")
        return result
    except Exception as e:
        logger.error(f"Failed to send bulk email: {str(e)}")
        return 0


def send_travel_grant_notification(recipient_email, full_name, status, grant_id=None):
    """
    Send travel grant status notification email.
    
    Args:
        recipient_email (str): Recipient email address
        full_name (str): Recipient's full name
        status (str): Travel grant status (e.g., 'Approved', 'Rejected', 'Pending')
        grant_id (str, optional): Travel grant ID
    
    Returns:
        int: 1 if sent successfully, 0 if failed
    """
    context = {
        'full_name': full_name,
        'status': status,
        'grant_id': grant_id,
    }
    
    subject = f"Travel Grant Status Update - {status}"
    
    return send_template_email(
        template_name='emails/travel_grant_notification.html',
        context=context,
        subject=subject,
        recipient_list=[recipient_email],
    )


def send_welcome_email(recipient_email, full_name, username):
    """
    Send welcome email to new users.
    
    Args:
        recipient_email (str): Recipient email address
        full_name (str): User's full name
        username (str): User's username
    
    Returns:
        int: 1 if sent successfully, 0 if failed
    """
    context = {
        'full_name': full_name,
        'username': username,
    }
    
    subject = "Welcome to Student Travel Grant Portal"
    
    return send_template_email(
        template_name='emails/welcome.html',
        context=context,
        subject=subject,
        recipient_list=[recipient_email],
    )


def send_password_reset_email(recipient_email, reset_link, username):
    """
    Send password reset email.
    
    Args:
        recipient_email (str): Recipient email address
        reset_link (str): Password reset link
        username (str): User's username
    
    Returns:
        int: 1 if sent successfully, 0 if failed
    """
    context = {
        'username': username,
        'reset_link': reset_link,
    }
    
    subject = "Password Reset Request - Travel Grant Portal"
    
    return send_template_email(
        template_name='emails/password_reset.html',
        context=context,
        subject=subject,
        recipient_list=[recipient_email],
    )
