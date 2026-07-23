from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401  (register tables with Base.metadata)
from app.database import Base, engine
from app.errors import register_error_handlers
from app.routers import customers, data_quality, metrics, orders


@asynccontextmanager
async def lifespan(app: FastAPI):
    # For a take-home this is simpler than migrations; production would use
    # Alembic (see README "What I'd do next").
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Evernine Orders API",
    description=(
        "Analytics over a simulated e-commerce feed (orders.json + "
        "customers.csv). The feed is treated as untrusted input; see "
        "/api/data-quality for everything the ingest flagged."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# No auth per the brief, local development only — permissive CORS is fine here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

app.include_router(metrics.router, prefix="/api")
app.include_router(customers.router, prefix="/api")
app.include_router(orders.router, prefix="/api")
app.include_router(data_quality.router, prefix="/api")


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
