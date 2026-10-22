from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .audit import audit, redaction_summary
from .auth import UserStore, require_basic_auth, require_bearer_auth
from .config import get_settings
from .models import Message, MessageCreate
from .repository import MessageRepository
from .service import MessageService

_templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    repository = MessageRepository(settings.db_path)
    app.state.service = MessageService(repository)
    app.state.user_store = UserStore.load(settings.users_file)
    yield


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # FastAPI's default 422 body echoes the rejected "input" back to the
        # caller. A rejected message (e.g. too long) has not been redacted, so
        # return only where and why validation failed, never the value itself.
        errors = [
            {"type": e["type"], "loc": e["loc"], "msg": e["msg"]} for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        username: str = Depends(require_basic_auth),
    ) -> HTMLResponse:
        messages = app.state.service.list(limit=500, offset=0)
        return _templates.TemplateResponse(
            request, "index.html", {"username": username, "messages": messages}
        )

    @app.post("/api/messages", response_model=Message, status_code=201)
    def create_message(
        payload: MessageCreate,
        username: str = Depends(require_bearer_auth),
    ) -> dict:
        message = app.state.service.create(payload.content, username)
        audit(
            "message.created",
            id=message["id"],
            by=username,
            redactions=redaction_summary(message["redactions"]),
        )
        return message

    @app.get("/api/messages", response_model=list[Message])
    def list_messages(
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        username: str = Depends(require_bearer_auth),
    ) -> list[dict]:
        return app.state.service.list(limit, offset)

    @app.get("/api/messages/{message_id}", response_model=Message)
    def get_message(
        message_id: int,
        username: str = Depends(require_bearer_auth),
    ) -> dict:
        message = app.state.service.get(message_id)
        if message is None:
            raise HTTPException(status_code=404, detail="Message not found")
        return message

    @app.delete("/api/messages/{message_id}", status_code=204)
    def delete_message(
        message_id: int,
        username: str = Depends(require_bearer_auth),
    ) -> None:
        if not app.state.service.delete(message_id):
            raise HTTPException(status_code=404, detail="Message not found")
        audit("message.deleted", id=message_id, by=username)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "server.app.main:app",
        host="0.0.0.0",
        port=settings.port,
        ssl_certfile=settings.ssl_certfile,
        ssl_keyfile=settings.ssl_keyfile,
    )
