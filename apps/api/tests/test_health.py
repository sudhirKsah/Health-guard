from app.routers.health import liveness


def test_liveness_is_available_without_external_services() -> None:
    assert liveness() == {"status": "ok"}
