"""FastAPI application entry point for the Rewizor project."""

import logging
import os

from fastapi import FastAPI
from dotenv import load_dotenv

from src.api.rewizor_api import router as rewizor_router

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="Rewizor GT EPP Export API",
    version="1.0.0",
    description="Document OCR and Rewizor GT EDI++ (.epp) file generation.",
)

app.include_router(rewizor_router, prefix="/api/v1/rewizor")


@app.get("/health")
async def health():
    return {"status": "ok"}
