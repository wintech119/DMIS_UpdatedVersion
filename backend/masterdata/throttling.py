from rest_framework.throttling import UserRateThrottle


class MasterDataWriteThrottle(UserRateThrottle):
    scope = "masterdata-write"
    rate = "40/minute"
    write_methods = frozenset({"POST", "PATCH", "PUT", "DELETE"})

    def allow_request(self, request, view):
        if request.method not in self.write_methods:
            return True
        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        if request.method not in self.write_methods:
            return None
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            ident = (
                getattr(user, "pk", None)
                or getattr(user, "user_id", None)
                or getattr(user, "id", None)
                or self.get_ident(request)
            )
        else:
            ident = self.get_ident(request)
        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }
