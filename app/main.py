from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from .routers import questoes

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Questão Viva API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(questoes.router)

@app.get("/")
def root():
    return {"message": "Questão Viva API"}

@app.get("/health")
def health():
    return {"status": "ok"}
