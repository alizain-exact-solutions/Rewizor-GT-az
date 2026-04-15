"""FastAPI application entry point for the Rewizor project."""

import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from src.api.accounting_api import router as accounting_router
from src.api.documents_api import router as documents_router
from src.api.exports_api import router as exports_router
from src.api.rewizor_api import router as rewizor_router

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

app = FastAPI(
    title="Rewizor GT EPP Export API",
    version="1.0.0",
    description="Document OCR and Rewizor GT EDI++ (.epp) file generation.",
)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please try again later."},
    )


app.include_router(rewizor_router, prefix="/api/v1/rewizor")
app.include_router(accounting_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(exports_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
