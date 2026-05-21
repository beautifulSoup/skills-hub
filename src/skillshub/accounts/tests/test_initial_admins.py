"""Tests for INITIAL_ADMIN_EMAILS post_migrate sync handler."""
import pytest

from django.contrib.auth.models import User
from django.test import override_settings

from skillshub.accounts.apps import _sync_initial_admins

pytestmark = pytest.mark.django_db


@override_settings(INITIAL_ADMIN_EMAILS=["alice@x.com", "bob@x.com"])
def test_initial_admins_created_and_promoted():
    _sync_initial_admins(sender=None)

    alice = User.objects.get(username="alice@x.com")
    bob = User.objects.get(username="bob@x.com")
    assert alice.is_staff is True
    assert alice.is_superuser is True
    assert bob.is_staff is True
    assert bob.is_superuser is True


@override_settings(INITIAL_ADMIN_EMAILS=["carol@x.com"])
def test_existing_member_gets_promoted():
    user = User.objects.create_user(username="carol@x.com", email="carol@x.com", is_staff=False)
    _sync_initial_admins(sender=None)

    user.refresh_from_db()
    assert user.is_staff is True
    assert user.is_superuser is True
