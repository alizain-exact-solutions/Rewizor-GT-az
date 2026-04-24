"""FastAPI application entry point for the Rewizor GT EPP service."""

import logging

from dotenv import load_dotenv
from fastapi import FastAPI

from src.api.business_api import router as business_router
from src.api.exports_api import router as exports_router
from src.api.rewizor_api import router as rewizor_router

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="Rewizor GT EPP Export API",
    version="2.0.0",
    description=(
        "Upload a PDF invoice, receive a Rewizor GT EDI++ (.epp) file. "
        "Exports are stored for re-download. Sender details are managed "
        "through /api/v1/business-details."
    ),
)


app.include_router(rewizor_router, prefix="/api/v1")
app.include_router(exports_router, prefix="/api/v1")
app.include_router(business_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
