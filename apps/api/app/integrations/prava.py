import httpx

from app.config import Settings, get_settings


class PravaUnavailableError(RuntimeError):
    """Raised when Prava cannot be reached or returns a non-success response."""


class PravaClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def health(self) -> dict[str, object]:
        try:
            async with httpx.AsyncClient(
                base_url=str(self._settings.prava_api_base_url), timeout=10.0
            ) as client:
                response = await client.get("/health")
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise PravaUnavailableError("Prava sandbox is unavailable") from error

        return {
            "status": payload.get("status"),
            "timestamp": payload.get("timestamp"),
        }
