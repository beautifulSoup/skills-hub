from django.conf import settings


def is_email_allowed(email: str) -> bool:
    """Return True iff email domain is in EMAIL_DOMAIN_WHITELIST."""
    email = email.lower().strip()
    whitelist = getattr(settings, "EMAIL_DOMAIN_WHITELIST", [])
    if not whitelist:
        return False
    domain = email.split("@")[-1] if "@" in email else ""
    return domain in whitelist
