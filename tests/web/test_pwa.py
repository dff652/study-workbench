"""The install endpoints expose no learning data or authenticated offline shell."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase


class PWABoundaryTests(TestCase):
    def test_install_metadata_is_public_and_login_stays_required(self):
        response = self.client.get('/manifest.webmanifest')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/manifest+json')
        self.assertEqual(response.json()['start_url'], '/')
        self.assertEqual(response.json()['scope'], '/')
        self.assertRedirects(self.client.get('/'), '/accounts/login/?next=/', fetch_redirect_response=False)
        self.assertNotContains(response, 'household')

    def test_install_routes_reject_writes(self):
        for path in ('/manifest.webmanifest', '/sw.js', '/mobile/'):
            self.assertEqual(self.client.post(path).status_code, 405)

    def test_authenticated_install_and_learning_pages_keep_no_store(self):
        user = get_user_model().objects.create_user(username='pwa-boundary', password='synthetic-only')
        self.client.force_login(user)
        for path in ('/manifest.webmanifest', '/sw.js', '/mobile/', '/'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn('no-store', response['Cache-Control'])
            self.assertNotContains(response, user.username)

    def test_worker_is_revalidated_and_logout_still_requires_csrf(self):
        response = self.client.get('/sw.js')
        self.assertEqual(response['Service-Worker-Allowed'], '/')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('application/javascript', response['Content-Type'])
        client = Client(enforce_csrf_checks=True)
        user = get_user_model().objects.create_user(username='pwa-csrf', password='synthetic-only')
        client.force_login(user)
        self.assertEqual(client.post('/accounts/logout/').status_code, 403)

    def test_anonymous_private_redirect_is_not_cacheable(self):
        response = self.client.get('/page/00000000-0000-0000-0000-000000000001/preview/0/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('private', response['Cache-Control'])
