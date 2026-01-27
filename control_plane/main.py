from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from control_plane.api.routes import auth, folders, nodes, file, users, notifications
from control_plane.db.session import engine
from control_plane.db.base import Base  # ensures Base is imported
import control_plane.models  # noqa: F401  # import models so metadata is populated
from control_plane.core.config import settings


control_plane = FastAPI(title="Cloud Drive Backend")


control_plane.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# include routers
control_plane.include_router(auth.router)
control_plane.include_router(folders.router)
control_plane.include_router(nodes.router)
control_plane.include_router(file.router)
control_plane.include_router(users.router)
control_plane.include_router(notifications.router)


