from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ..services.repository import TradeRepository
from .dashboard import _LEADERBOARD_HTML


def create_app(repo: TradeRepository | None = None) -> FastAPI:
    if repo is None:
        repo = TradeRepository()

    app = FastAPI(title="Ayumi Copy Trading API", version="0.1.0")

    @app.get("/", response_class=HTMLResponse)
    async def leaderboard_page() -> HTMLResponse:
        return HTMLResponse(_LEADERBOARD_HTML)

    @app.get("/api/leaderboard")
    async def get_leaderboard(limit: int = 10) -> list[dict]:
        return repo.get_leaderboard(limit)

    @app.get("/api/signals")
    async def get_recent_signals(limit: int = 20) -> list[dict]:
        return repo.get_recent_signals(limit)

    @app.get("/api/providers/{provider_id}/stats", response_model=None)
    async def get_provider_stats(provider_id: str):
        stats = repo.get_provider_stats(provider_id)
        if not stats:
            return JSONResponse({"error": "Provider not found"}, status_code=404)
        return stats

    @app.post("/api/webhook/signal", response_model=None)
    async def receive_signal(request: Request):
        payload = await request.json()
        required = {"symbol", "direction", "entry_price", "stop_loss", "take_profit"}
        missing = required - payload.keys()
        if missing:
            return JSONResponse(
                {"error": f"Missing fields: {', '.join(missing)}"},
                status_code=400,
            )

        provider_id = payload.get("provider_id", "")
        conn = repo._connect()
        provider = conn.execute(
            "SELECT provider_id FROM providers WHERE provider_id = ?",
            (provider_id,),
        ).fetchone()
        conn.close()

        if not provider:
            return JSONResponse(
                {"error": f"Unknown provider: {provider_id}"},
                status_code=403,
            )

        signal_id = repo.save_signal({
            "provider_id": provider_id,
            "symbol": payload["symbol"],
            "direction": payload["direction"].lower(),
            "entry_price": float(payload["entry_price"]),
            "stop_loss": float(payload["stop_loss"]),
            "take_profit": float(payload["take_profit"]),
            "lot_size": float(payload.get("lot_size", 0)),
            "signal_time": payload.get("signal_time", ""),
            "strategy_name": payload.get("strategy_name", ""),
            "confluence_count": int(payload.get("confluence_count", 0)),
            "strength": payload.get("strength", "moderate"),
        })

        return {"status": "ok", "signal_id": signal_id}

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "service": "ayumi-copy-trading"}

    return app
