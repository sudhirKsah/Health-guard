from app.config import Settings


def test_comma_separated_cors_origins_are_parsed() -> None:
    settings = Settings(cors_origins="http://localhost:3000,http://localhost:3001")

    assert settings.cors_origin_list == ["http://localhost:3000", "http://localhost:3001"]


def test_openai_model_friendly_name_is_normalized() -> None:
    assert Settings(openai_model="GPT-5.6Terra").openai_model == "gpt-5.6-terra"
