from fastapi import FastAPI

from control_plane.api.routes import auth, folders, nodes, file
from control_plane.db.session import engine
from control_plane.db.base import Base  # ensures Base is imported
import control_plane.models  # noqa: F401  # import models so metadata is populated


control_plane = FastAPI(title="Cloud Drive Backend")


# include routers
control_plane.include_router(auth.router)
control_plane.include_router(folders.router)
control_plane.include_router(nodes.router)
control_plane.include_router(file.router)


