"""Tests for accounts.whitelist module."""
import pytest
from unittest.mock import patch


def test_email_in_whitelist():
    with patch("skillshub.accounts.whitelist.settings") as mock_settings:
        mock_settings.EMAIL_DOMAIN_WHITELIST = ["example.com", "corp.io"]
        from skillshub.accounts.whitelist import is_email_allowed
        assert is_email_allowed("alice@example.com") is True


def test_email_not_in_whitelist():
    with patch("skillshub.accounts.whitelist.settings") as mock_settings:
        mock_settings.EMAIL_DOMAIN_WHITELIST = ["example.com"]
        from skillshub.accounts.whitelist import is_email_allowed
        assert is_email_allowed("bob@gmail.com") is False


def test_empty_whitelist_rejects_all():
    with patch("skillshub.accounts.whitelist.settings") as mock_settings:
        mock_settings.EMAIL_DOMAIN_WHITELIST = []
        from skillshub.accounts.whitelist import is_email_allowed
        assert is_email_allowed("anyone@example.com") is False
