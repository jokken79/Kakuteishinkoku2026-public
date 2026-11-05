"""Lectura temporal local de documentos de remesas."""

from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from app.services.remittance_reading import MAX_BYTES, RemittanceReadingError, read_remittance

router = APIRouter(tags=["remittances"])


@router.post("/remittances/read")
async def read_document(
    response: Response,
    file: UploadFile = File(...),
    language: Literal["pt", "japan"] = Form(default="pt"),
) -> dict[str, object]:
    data = await file.read(MAX_BYTES + 1)
    await file.close()
    try:
        result = await run_in_threadpool(read_remittance, data, language)
    except RemittanceReadingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response.headers["Cache-Control"] = "no-store"
    return result
