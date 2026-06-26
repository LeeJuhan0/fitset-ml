from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import data, deploy, model, runs, train

app = FastAPI(title="FitSet ML Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(data.router)
app.include_router(train.router)
app.include_router(deploy.router)
app.include_router(model.router)
app.include_router(runs.router)

app.mount("/", StaticFiles(directory="static", html=True), name="static")
