# home/context_processors.py
import os
from django.conf import settings
from django.db import connection

def user_profile(request):
    """Inject user's profile image and name into all templates"""
    profile_image_url = None
    user_name = None

    if request.user.is_authenticated:
        email = request.user.email
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT "USERNAME", "NAME", "PHOTO"
                FROM "USERS"
                WHERE "EMAIL" = %s
            """, [email])
            row = cursor.fetchone()

        if row:
            username, name, photo = row
            user_name = name or username
            if photo:
                image_path = os.path.join(settings.MEDIA_ROOT, photo)
                if os.path.exists(image_path):
                    timestamp = int(os.path.getmtime(image_path))
                    profile_image_url = f"/media/{photo}?v={timestamp}"
                else:
                    profile_image_url = None

    return {
        'global_profile_image_url': profile_image_url,
        'global_user_name': user_name,
    }
