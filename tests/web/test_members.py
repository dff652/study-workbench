"""Synthetic HTTP tests for owner-only household membership management."""
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from app.persistence import services as core
from app.persistence.models import EntityRecord, HouseholdMember
from app.persistence.services import PersistenceError
from app.web import member_services


def key(prefix):
    return f"{prefix}-{uuid4().hex}"


class MemberManagementHTTPTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username=key("member-owner"), password="Synthetic-owner-123")
        self.household = core.create_household(self.owner, key("member-house"))
        self.reviewer = user_model.objects.create_user(username=key("member-reviewer"), password="Synthetic-reviewer-123")
        self.viewer = user_model.objects.create_user(username=key("member-viewer"), password="Synthetic-viewer-123")
        self.reviewer_membership = HouseholdMember.objects.create(
            household=self.household, user=self.reviewer, role=HouseholdMember.Role.REVIEWER,
        )
        self.viewer_membership = HouseholdMember.objects.create(
            household=self.household, user=self.viewer, role=HouseholdMember.Role.VIEWER,
        )

        self.other_owner = user_model.objects.create_user(username=key("other-owner"), password="Synthetic-other-123")
        self.other_household = core.create_household(self.other_owner, key("other-house"))
        self.foreign_member = user_model.objects.create_user(username=key("foreign-member"), password="Synthetic-foreign-123")
        self.foreign_membership = HouseholdMember.objects.create(
            household=self.other_household, user=self.foreign_member, role=HouseholdMember.Role.VIEWER,
        )
        HouseholdMember.objects.create(
            household=self.other_household, user=self.owner, role=HouseholdMember.Role.VIEWER,
        )

        self.client = Client()
        self.client.force_login(self.owner)
        self.url = reverse("web:members")

    def post_data(self, action, **values):
        return {"action": action, "household_id": self.household.pk, **values}

    def test_only_active_owner_can_view_and_get_has_no_write_side_effect(self):
        user_count = get_user_model().objects.count()
        membership_count = HouseholdMember.objects.count()
        response = self.client.get(self.url, {"household_id": self.household.pk})
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertContains(response, self.reviewer.username)
        self.assertContains(response, self.viewer.username)
        self.assertEqual(get_user_model().objects.count(), user_count)
        self.assertEqual(HouseholdMember.objects.count(), membership_count)
        bare = self.client.get(self.url)
        self.assertEqual(bare.status_code, 200)
        self.assertContains(bare, self.household.pk)
        self.assertNotContains(bare, self.other_household.pk)

        anonymous = Client()
        self.assertEqual(anonymous.get(self.url, {"household_id": self.household.pk}).status_code, 302)
        for user in (self.reviewer, self.viewer, self.other_owner):
            with self.subTest(user=user.username):
                denied = Client()
                denied.force_login(user)
                self.assertEqual(denied.get(self.url, {"household_id": self.household.pk}).status_code, 404)
        self.assertEqual(self.client.get(self.url, {"household_id": self.other_household.pk}).status_code, 404)
        self.assertEqual(self.client.get(self.url, {"household_id": key("missing-house")}).status_code, 404)

        other_owned = core.create_household(self.owner, key("another-owned-house"))
        multi = self.client.get(self.url)
        self.assertEqual(multi.status_code, 200)
        self.assertContains(multi, "选择家庭")
        self.assertContains(multi, other_owned.pk)
        self.assertNotContains(multi, self.other_household.pk)
        selected = self.client.get(self.url, {"household_id": other_owned.pk})
        self.assertEqual(selected.status_code, 200)
        self.assertContains(selected, other_owned.pk)

        inactive_owner = get_user_model().objects.create_user(username=key("inactive-owner"), password="Synthetic-inactive-123")
        inactive_household = core.create_household(inactive_owner, key("inactive-house"))
        get_user_model().objects.filter(pk=inactive_owner.pk).update(is_active=False)
        inactive_client = Client()
        inactive_client.force_login(inactive_owner)
        inactive_response = inactive_client.get(self.url, {"household_id": inactive_household.pk})
        self.assertEqual(inactive_response.status_code, 302)
        self.assertIn("/accounts/login/", inactive_response.headers["Location"])
        with self.assertRaises(PersistenceError) as scoped_error:
            member_services.list_members(inactive_owner, inactive_household.pk)
        self.assertEqual(scoped_error.exception.code, "permission_denied")
        with self.assertRaises(PersistenceError) as households_error:
            member_services.list_owner_households(inactive_owner)
        self.assertEqual(households_error.exception.code, "permission_denied")

    def test_csrf_is_required_before_any_account_or_membership_write(self):
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.owner)
        response = protected.get(self.url, {"household_id": self.household.pk})
        self.assertEqual(response.status_code, 200)
        counts = (get_user_model().objects.count(), HouseholdMember.objects.count())
        response = protected.post(self.url, self.post_data(
            "create",
            username=key("csrf-blocked"),
            password1="Synthetic-CSRF-Password-123",
            password2="Synthetic-CSRF-Password-123",
            role=HouseholdMember.Role.REVIEWER,
        ))
        self.assertEqual(response.status_code, 403)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual((get_user_model().objects.count(), HouseholdMember.objects.count()), counts)

        missing_household = self.client.post(self.url, {
            "action": "remove", "member_id": self.viewer_membership.pk,
        })
        self.assertEqual(missing_household.status_code, 404)
        self.assertTrue(HouseholdMember.objects.filter(pk=self.viewer_membership.pk).exists())

    def test_owner_can_create_hashed_standard_accounts_and_duplicate_rolls_back(self):
        username = key("new-reviewer")
        password = "Synthetic-New-Member-Password-123"
        response = self.client.post(self.url, self.post_data(
            "create", username=username, password1=password, password2=password,
            role=HouseholdMember.Role.REVIEWER,
        ))
        self.assertEqual(response.status_code, 302, response.content.decode("utf-8"))
        account = get_user_model().objects.get(username=username)
        self.assertTrue(account.check_password(password))
        self.assertNotEqual(account.password, password)
        self.assertTrue(account.is_active)
        self.assertFalse(account.is_staff)
        self.assertFalse(account.is_superuser)
        membership = HouseholdMember.objects.get(household=self.household, user=account)
        self.assertEqual(membership.role, HouseholdMember.Role.REVIEWER)

        viewer_username = key("new-viewer")
        viewer_password = "Synthetic-New-Viewer-Password-123"
        viewer_response = self.client.post(self.url, self.post_data(
            "create", username=viewer_username, password1=viewer_password, password2=viewer_password,
            role=HouseholdMember.Role.VIEWER,
        ))
        self.assertEqual(viewer_response.status_code, 302)
        viewer_account = get_user_model().objects.get(username=viewer_username)
        self.assertTrue(viewer_account.check_password(viewer_password))
        self.assertEqual(
            HouseholdMember.objects.get(household=self.household, user=viewer_account).role,
            HouseholdMember.Role.VIEWER,
        )

        page = self.client.get(self.url, {"household_id": self.household.pk})
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(password.encode(), page.content)

        before_count = get_user_model().objects.count()
        duplicate = self.client.post(self.url, self.post_data(
            "create", username=self.foreign_member.username,
            password1=password, password2=password, role=HouseholdMember.Role.VIEWER,
        ))
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(get_user_model().objects.count(), before_count)
        self.assertFalse(HouseholdMember.objects.filter(household=self.household, user=self.foreign_member).exists())

        injected_username = key("injected-flags")
        injected = self.client.post(self.url, self.post_data(
            "create", username=injected_username, password1=password, password2=password,
            role=HouseholdMember.Role.VIEWER, is_staff="on", is_superuser="on", is_active="off",
        ))
        self.assertEqual(injected.status_code, 400)
        self.assertFalse(get_user_model().objects.filter(username=injected_username).exists())

    @override_settings(AUTH_PASSWORD_VALIDATORS=[{
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 16},
    }])
    def test_password_validation_failure_creates_no_account_and_does_not_echo_password(self):
        username = key("short-password")
        response = self.client.post(self.url, self.post_data(
            "create", username=username, password1="tiny-password", password2="tiny-password",
            role=HouseholdMember.Role.VIEWER,
        ))
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(b"tiny-password", response.content)
        self.assertFalse(get_user_model().objects.filter(username=username).exists())
        self.assertFalse(HouseholdMember.objects.filter(household=self.household, user__username=username).exists())

    def test_service_rejects_empty_wrong_type_and_overlong_credentials_before_creating_accounts(self):
        user_count = get_user_model().objects.count()
        membership_count = HouseholdMember.objects.count()
        invalid_usernames = (None, 7, "", "   ", "u" * 151)
        for username in invalid_usernames:
            with self.subTest(username=username), self.assertRaises((ValidationError, PersistenceError)):
                member_services.create_member(
                    self.owner, self.household.pk, username, "Synthetic-Valid-Password-123", HouseholdMember.Role.VIEWER,
                )
        invalid_passwords = (None, 7, "", " \t\n", "x" * 1025)
        for index, password in enumerate(invalid_passwords):
            with self.subTest(password_type=type(password).__name__, index=index), self.assertRaises(PersistenceError):
                member_services.create_member(
                    self.owner, self.household.pk, key("service-boundary"), password, HouseholdMember.Role.VIEWER,
                )
        self.assertEqual(get_user_model().objects.count(), user_count)
        self.assertEqual(HouseholdMember.objects.count(), membership_count)

    def test_role_change_and_removal_preserve_household_learning_history(self):
        history = EntityRecord.objects.create(
            household=self.household,
            kind=EntityRecord.EntityKind.LEARNER,
            stable_id="learner-history-synthetic",
            identity={"learner_id": "learner-history-synthetic"},
        )
        changed = self.client.post(self.url, self.post_data(
            "change", member_id=self.reviewer_membership.pk, role=HouseholdMember.Role.VIEWER,
        ))
        self.assertEqual(changed.status_code, 302, changed.content.decode("utf-8"))
        self.reviewer_membership.refresh_from_db()
        self.assertEqual(self.reviewer_membership.role, HouseholdMember.Role.VIEWER)

        removed = self.client.post(self.url, self.post_data("remove", member_id=self.viewer_membership.pk))
        self.assertEqual(removed.status_code, 302, removed.content.decode("utf-8"))
        self.assertFalse(HouseholdMember.objects.filter(pk=self.viewer_membership.pk).exists())
        self.assertTrue(get_user_model().objects.filter(pk=self.viewer.pk).exists())
        self.assertTrue(EntityRecord.objects.filter(pk=history.pk, household=self.household).exists())

    def test_owner_staff_superuser_and_cross_household_targets_are_rejected(self):
        owner_membership = HouseholdMember.objects.get(household=self.household, user=self.owner)
        protected_owner = self.client.post(self.url, self.post_data(
            "change", member_id=owner_membership.pk, role=HouseholdMember.Role.VIEWER,
        ))
        self.assertEqual(protected_owner.status_code, 400)
        protected_owner_remove = self.client.post(self.url, self.post_data("remove", member_id=owner_membership.pk))
        self.assertEqual(protected_owner_remove.status_code, 400)
        owner_membership.refresh_from_db()
        self.assertEqual(owner_membership.role, HouseholdMember.Role.OWNER)

        user_model = get_user_model()
        staff = user_model.objects.create_user(username=key("staff"), password="Synthetic-staff-123", is_staff=True)
        superuser = user_model.objects.create_user(username=key("superuser"), password="Synthetic-superuser-123", is_superuser=True)
        staff_member = HouseholdMember.objects.create(household=self.household, user=staff, role=HouseholdMember.Role.REVIEWER)
        superuser_member = HouseholdMember.objects.create(household=self.household, user=superuser, role=HouseholdMember.Role.VIEWER)
        for member in (staff_member, superuser_member):
            with self.subTest(member=member.pk):
                changed = self.client.post(self.url, self.post_data(
                    "change", member_id=member.pk, role=HouseholdMember.Role.VIEWER,
                ))
                self.assertEqual(changed.status_code, 400)
                denied = self.client.post(self.url, self.post_data("remove", member_id=member.pk))
                self.assertEqual(denied.status_code, 400)
                self.assertTrue(HouseholdMember.objects.filter(pk=member.pk).exists())

        foreign = self.client.post(self.url, self.post_data("remove", member_id=self.foreign_membership.pk))
        self.assertEqual(foreign.status_code, 404)
        self.assertTrue(HouseholdMember.objects.filter(pk=self.foreign_membership.pk).exists())


if __name__ == "__main__":
    import unittest

    unittest.main()
