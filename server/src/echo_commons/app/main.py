from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from echo_commons import __version__
from echo_commons.app.health import router as health_router
from echo_commons.app.http import register_errors
from echo_commons.app.lifecycle import lifespan_for
from echo_commons.app.management import router as management_router
from echo_commons.app.realtime import router as realtime_router
from echo_commons.app.settings import Settings, load_settings
from echo_commons.modules.assets.api.routes import router as assets_router
from echo_commons.modules.characters.api.authoring_routes import router as authoring_router
from echo_commons.modules.characters.api.routes import router as characters_router
from echo_commons.modules.communities.api.routes import router as communities_router
from echo_commons.modules.conversations.api.routes import router as conversations_router
from echo_commons.modules.social.api.routes import router as social_router


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or load_settings()
    app = FastAPI(title="Echo Commons", version=__version__, lifespan=lifespan_for(config))
    app.state.settings = config
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.cors_origins),
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )
    register_errors(app)
    app.include_router(assets_router)
    app.include_router(communities_router)
    app.include_router(characters_router)
    app.include_router(authoring_router)
    app.include_router(conversations_router)
    app.include_router(social_router)
    app.include_router(realtime_router)
    app.include_router(management_router)
    app.include_router(health_router)

    @app.get("/health/live")
    def liveness():
        return {"status": "ok", "service": "echo-commons-server", "version": __version__}

    return app
