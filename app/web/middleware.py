"""Keep dynamic pages and private login redirects out of browser/shared caches."""

from django.utils.cache import patch_cache_control


class PrivateResponsesMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # WhiteNoise serves public static assets before this middleware in production.
        patch_cache_control(response, private=True, no_store=True, no_cache=True, max_age=0)
        return response
