from app.config import Settings
from app.integrations.ucp import UcpAdapter


def test_ucp_refuses_to_use_any_profile_until_health_guard_profile_is_configured() -> None:
    readiness = UcpAdapter(Settings(health_guard_ucp_profile_url=None)).readiness()

    assert readiness.ready is False
    assert readiness.reason == "health_guard_ucp_profile_url_not_configured"


def test_ucp_accepts_a_public_https_health_guard_profile() -> None:
    settings = Settings(health_guard_ucp_profile_url="https://health-guard.example/.well-known/ucp")

    assert UcpAdapter(settings).readiness().ready is True
