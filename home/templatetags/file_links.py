from django import template

register = template.Library()


@register.filter
def file_url(path):
    """Link target for a stored application document.

    Uploads made through the portal are stored as paths relative to MEDIA_ROOT
    and served from /media/. Applications imported from the old Google Form
    point at Google Drive instead, so an http(s) URL is used as it is.

    Only those two schemes pass through untouched; anything else is treated as a
    relative path, so a stored value can never turn into a javascript: link.
    """
    value = (path or "").strip()
    if value.lower().startswith(("https://", "http://")):
        return value
    return "/media/" + value
