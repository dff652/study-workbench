"""Household-scoped login membership management."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from app.persistence.models import Household, HouseholdMember
from app.persistence.services import PersistenceError


MEMBER_ROLES = (HouseholdMember.Role.REVIEWER, HouseholdMember.Role.VIEWER)


def _error(code: str, message: str):
    raise PersistenceError(code, message)


def normalize_username(value: str) -> str:
    """Apply the configured User model's username normalization and field rules."""
    if type(value) is not str or not value.strip():
        raise ValidationError("A non-empty login name is required")
    user_model = get_user_model()
    field = user_model._meta.get_field(user_model.USERNAME_FIELD)
    max_length = min(field.max_length or 1024, 1024)
    if len(value) > max_length:
        raise ValidationError(f"Login name must be at most {max_length} characters")
    normalizer = getattr(user_model, "normalize_username", None)
    normalized = normalizer(value) if callable(normalizer) else value
    return field.clean(normalized, None)


def _active_owner(actor, household) -> None:
    if (not actor or not getattr(actor, "is_authenticated", False) or not getattr(actor, "pk", None)
            or not get_user_model()._default_manager.filter(pk=actor.pk, is_active=True).exists()):
        _error("permission_denied", "An active household owner is required")
    role = HouseholdMember.objects.filter(household=household, user_id=actor.pk).values_list("role", flat=True).first()
    if role != HouseholdMember.Role.OWNER:
        _error("permission_denied", "An active household owner is required")


def _household(actor, household_id, *, lock: bool):
    if type(household_id) is not str or not household_id.strip() or len(household_id) > 160 or "\x00" in household_id:
        _error("not_found", "Household not found")
    query = Household.objects
    if lock:
        query = query.select_for_update()
    household = query.filter(pk=household_id).first()
    if household is None:
        _error("not_found", "Household not found")
    _active_owner(actor, household)
    return household


def list_members(actor, household_id: str) -> dict:
    """Read memberships for an active owner without changing database state."""
    household = _household(actor, household_id, lock=False)
    members = list(
        HouseholdMember.objects.filter(household=household)
        .select_related("user")
        .order_by("user__username", "pk")
    )
    return {"household": household, "members": members}


def list_owner_households(actor) -> list[Household]:
    """List only active household memberships where this user is an owner."""
    if (not actor or not getattr(actor, "is_authenticated", False) or not getattr(actor, "pk", None)
            or not get_user_model()._default_manager.filter(pk=actor.pk, is_active=True).exists()):
        _error("permission_denied", "An active household owner is required")
    memberships = (
        HouseholdMember.objects.filter(
            user_id=actor.pk,
            user__is_active=True,
            role=HouseholdMember.Role.OWNER,
        )
        .select_related("household")
        .order_by("household_id")
    )
    return [membership.household for membership in memberships]


@transaction.atomic
def change_role(actor, household_id: str, member_id: int, role: str):
    household = _household(actor, household_id, lock=True)
    if not isinstance(role, str) or role not in MEMBER_ROLES:
        _error("invalid_input", "Only reviewer or viewer roles can be assigned")
    if type(member_id) is not int or member_id < 1:
        _error("not_found", "Household member not found")
    member = (
        HouseholdMember.objects.select_for_update()
        .select_related("user")
        .filter(pk=member_id, household=household)
        .first()
    )
    if member is None:
        _error("not_found", "Household member not found")
    if member.role == HouseholdMember.Role.OWNER or member.user.is_staff or member.user.is_superuser:
        _error("protected_member", "This account's household access cannot be changed here")
    member.role = role
    member.save(update_fields=["role"])
    return member


@transaction.atomic
def remove_member(actor, household_id: str, member_id: int) -> None:
    household = _household(actor, household_id, lock=True)
    if type(member_id) is not int or member_id < 1:
        _error("not_found", "Household member not found")
    member = (
        HouseholdMember.objects.select_for_update()
        .select_related("user")
        .filter(pk=member_id, household=household)
        .first()
    )
    if member is None:
        _error("not_found", "Household member not found")
    if member.role == HouseholdMember.Role.OWNER or member.user.is_staff or member.user.is_superuser:
        _error("protected_member", "This account's household access cannot be changed here")
    # Only the household membership is removed. The shared login and household history remain.
    member.delete()


def create_member(actor, household_id: str, username: str, password: str, role: str):
    """Create a new Django login and its household membership atomically."""
    try:
        return _create_member(actor, household_id, username, password, role)
    except IntegrityError:
        user_model = get_user_model()
        username_field = user_model.USERNAME_FIELD
        try:
            normalized = normalize_username(username)
        except (ValidationError, TypeError):
            raise
        if user_model._default_manager.filter(**{username_field: normalized}).exists():
            _error("username_taken", "That login name is already in use")
        raise


@transaction.atomic
def _create_member(actor, household_id: str, username: str, password: str, role: str):
    household = _household(actor, household_id, lock=True)
    if not isinstance(role, str) or role not in MEMBER_ROLES:
        _error("invalid_input", "Only reviewer or viewer roles can be assigned")
    if type(password) is not str or not password.strip() or len(password) > 1024:
        _error("invalid_input", "Password must contain 1 to 1024 non-whitespace characters")
    user_model = get_user_model()
    username_field = user_model.USERNAME_FIELD
    normalized = normalize_username(username)
    if user_model._default_manager.filter(**{username_field: normalized}).exists():
        _error("username_taken", "That login name is already in use")
    candidate = user_model()
    setattr(candidate, username_field, normalized)
    validate_password(password, user=candidate)

    user = user_model._default_manager.create_user(**{username_field: normalized, "password": password})
    if (not getattr(user, "is_active", False) or getattr(user, "is_staff", False)
            or getattr(user, "is_superuser", False)):
        _error("account_creation_failed", "The account manager did not create a standard active user")
    return HouseholdMember.objects.create(household=household, user=user, role=role)
