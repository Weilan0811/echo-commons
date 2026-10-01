from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from echo_commons import __version__
from echo_commons.app.lifecycle import lifespan_for
from echo_commons.app.settings import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or load_settings()
    app = FastAPI(title="Echo Commons", version=__version__, lifespan=lifespan_for(config))
    app.state.settings = config
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.cors_origins),
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health/live")
    def liveness():
        return {"status": "ok", "service": "echo-commons-server", "version": __version__}

    return app
