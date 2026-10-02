"""Keep authenticated learning pages out of shared and browser caches."""

from django.utils.cache import patch_cache_control


class PrivateResponsesMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated or request.path.startswith("/accounts/"):
            patch_cache_control(response, private=True, no_store=True, no_cache=True, max_age=0)
        return response
