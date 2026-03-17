from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def health_check():
    return { "status": "ok", "service": "ProductPulse Scraper" }
```

**File 3 — `Procfile`** (no extension, exactly this name)
```
web: uvicorn main:app --host 0.0.0.0 --port $PORT
