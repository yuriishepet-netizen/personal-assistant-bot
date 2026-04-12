"""FastAPI application — REST API for the Lovable frontend."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import tasks, users, calendar, attachments, auth, projects

app = FastAPI(title="Personal Assistant API", version="1.0.0")

# CORS for Lovable frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://agile-calendar-hub.lovable.app",
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files for uploads
import os
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# API routes
app.include_router(tasks.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(calendar.router, prefix="/api")
app.include_router(attachments.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(projects.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok"}
