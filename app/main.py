from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.web.data.router import router as data_router
from app.web.training.router import router as train_router
from app.web.training.runs import router as runs_router
from app.web.deployment.router import router as deploy_router
from app.web.deployment.model import router as model_router

app = FastAPI(title="FitSet ML Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(data_router)
app.include_router(train_router)
app.include_router(deploy_router)
app.include_router(model_router)
app.include_router(runs_router)

app.mount("/", StaticFiles(directory="static", html=True), name="static")
