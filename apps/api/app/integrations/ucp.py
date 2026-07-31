from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings


@dataclass(frozen=True)
class UcpReadiness:
    ready: bool
    reason: str | None = None


class UcpConfigurationError(RuntimeError):
    """Direct UCP cannot run until Health Guard's own public profile is configured."""


class UcpAdapter:
    """Server-side boundary for real Shopify UCP calls introduced in Phase 4.

    It deliberately refuses to use a shared/public test profile. Merchant calls only begin after the
    deployed Health Guard profile is supplied through configuration.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def profile_url(self) -> str | None:
        return (
            str(self._settings.health_guard_ucp_profile_url)
            if self._settings.health_guard_ucp_profile_url
            else None
        )

    def readiness(self) -> UcpReadiness:
        if self.profile_url is None:
            return UcpReadiness(False, "health_guard_ucp_profile_url_not_configured")
        if not self.profile_url.startswith("https://"):
            return UcpReadiness(False, "health_guard_ucp_profile_url_must_use_https")
        return UcpReadiness(True)

    def require_ready(self) -> str:
        readiness = self.readiness()
        if not readiness.ready:
            raise UcpConfigurationError(readiness.reason or "ucp_not_ready")
        return self.profile_url or ""
