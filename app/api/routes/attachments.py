"""Attachment routes for file uploads."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.api.deps import get_current_user
from app.models.user import User
from app.models.attachment import FileType
from app.services import task_service

router = APIRouter(prefix="/tasks/{task_id}/attachments", tags=["attachments"])

# For MVP, store files locally. In production, use S3/R2.
UPLOAD_DIR = "uploads"


@router.get("")
async def list_attachments(
    task_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    task = await task_service.get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return [
        {
            "id": a.id,
            "file_type": a.file_type.value,
            "file_url": a.file_url,
            "original_name": a.original_name,
            "created_at": a.created_at,
        }
        for a in task.attachments
    ]


@router.post("", status_code=201)
async def upload_attachment(
    task_id: int,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    import os

    os.makedirs(UPLOAD_DIR, exist_ok=True)

    # Determine file type
    content_type = file.content_type or ""
    if content_type.startswith("image/"):
        file_type = FileType.IMAGE
    elif content_type.startswith("audio/"):
        file_type = FileType.VOICE
    else:
        file_type = FileType.DOCUMENT

    # Save file
    filename = f"{task_id}_{file.filename}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    attachment = await task_service.add_attachment(
        session, task_id, file_type.value, f"/uploads/{filename}", file.filename
    )

    return {
        "id": attachment.id,
        "file_type": attachment.file_type.value,
        "file_url": attachment.file_url,
        "original_name": attachment.original_name,
    }
