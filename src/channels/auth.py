# src/channels/auth.py
"""
Centralised authorisation policy for all channel adapters.

Auth modes
----------
strict   – allowed_user_ids non-empty; only listed users pass
open     – allow_all_users=True explicitly set in config; everyone passes
unset    – allowed_user_ids empty AND allow_all_users not set; denies all
           (conservative default — prevents accidental open-access deployments)
"""
import logging

logger = logging.getLogger(__name__)


class AuthPolicy:
    def __init__(self, allowed_user_ids: list[int], allow_all_users: bool = False):
        self._allowed = set(allowed_user_ids)
        self._allow_all = allow_all_users

    @property
    def mode(self) -> str:
        if self._allow_all:
            return "open"
        if self._allowed:
            return "strict"
        return "unset"

    def is_authorized(self, user_id: int) -> bool:
        if self._allow_all:
            return True
        if not self._allowed:
            # No allowlist and allow_all_users not set → deny all (conservative)
            return False
        return user_id in self._allowed

    def describe(self) -> str:
        if self._allow_all:
            return "open (all users allowed)"
        if self._allowed:
            return f"strict allowlist ({len(self._allowed)} users)"
        return "unset — all requests denied until ALLOWED_USER_IDS is configured"
