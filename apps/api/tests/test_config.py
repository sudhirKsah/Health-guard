from app.config import Settings


def test_comma_separated_cors_origins_are_parsed() -> None:
    settings = Settings(cors_origins="http://localhost:3000,http://localhost:3001")

    assert settings.cors_origin_list == ["http://localhost:3000", "http://localhost:3001"]
