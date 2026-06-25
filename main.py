from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import os
import base64
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS demos (
            id SERIAL PRIMARY KEY,
            slug TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS slides (
            id SERIAL PRIMARY KEY,
            demo_id INTEGER REFERENCES demos(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            image_data TEXT NOT NULL,
            hotspot_x FLOAT NOT NULL DEFAULT 50,
            hotspot_y FLOAT NOT NULL DEFAULT 50,
            tooltip_title TEXT NOT NULL DEFAULT '',
            tooltip_body TEXT NOT NULL DEFAULT '',
            tooltip_position TEXT NOT NULL DEFAULT 'right'
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

try:
    init_db()
except Exception as e:
    print(f"DB init error: {e}")

class DemoCreate(BaseModel):
    slug: str
    title: str
    description: Optional[str] = ""

class SlideCreate(BaseModel):
    demo_id: int
    position: int
    image_data: str
    hotspot_x: float
    hotspot_y: float
    tooltip_title: str
    tooltip_body: str
    tooltip_position: str = "right"

class SlideUpdate(BaseModel):
    hotspot_x: Optional[float] = None
    hotspot_y: Optional[float] = None
    tooltip_title: Optional[str] = None
    tooltip_body: Optional[str] = None
    tooltip_position: Optional[str] = None

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.post("/api/demos")
def create_demo(demo: DemoCreate):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO demos (slug, title, description) VALUES (%s, %s, %s) RETURNING *",
            (demo.slug, demo.title, demo.description)
        )
        row = dict(cur.fetchone())
        conn.commit()
        return row
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Slug already exists")
    finally:
        cur.close()
        conn.close()

@app.get("/api/demos")
def list_demos():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM demos ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows

@app.get("/api/demos/{slug}")
def get_demo(slug: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM demos WHERE slug = %s", (slug,))
    demo = cur.fetchone()
    if not demo:
        raise HTTPException(status_code=404, detail="Demo not found")
    demo = dict(demo)
    cur.execute(
        "SELECT * FROM slides WHERE demo_id = %s ORDER BY position ASC",
        (demo["id"],)
    )
    slides = [dict(r) for r in cur.fetchall()]
    demo["slides"] = slides
    cur.close()
    conn.close()
    return demo

@app.post("/api/slides")
async def create_slide(
    demo_id: int,
    position: int,
    hotspot_x: float,
    hotspot_y: float,
    tooltip_title: str,
    tooltip_body: str,
    tooltip_position: str = "right",
    file: UploadFile = File(...)
):
    content = await file.read()
    b64 = base64.b64encode(content).decode()
    mime = file.content_type or "image/png"
    image_data = f"data:{mime};base64,{b64}"

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO slides
           (demo_id, position, image_data, hotspot_x, hotspot_y, tooltip_title, tooltip_body, tooltip_position)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (demo_id, position, image_data, hotspot_x, hotspot_y, tooltip_title, tooltip_body, tooltip_position)
    )
    row = dict(cur.fetchone())
    conn.commit()
    cur.close()
    conn.close()
    # Don't return the full image_data in response to keep it fast
    row["image_data"] = "[stored]"
    return row

@app.patch("/api/slides/{slide_id}")
def update_slide(slide_id: int, update: SlideUpdate):
    conn = get_conn()
    cur = conn.cursor()
    fields = {k: v for k, v in update.dict().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Nothing to update")
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values()) + [slide_id]
    cur.execute(f"UPDATE slides SET {set_clause} WHERE id = %s RETURNING id", values)
    conn.commit()
    cur.close()
    conn.close()
    return {"updated": slide_id}

@app.delete("/api/slides/{slide_id}")
def delete_slide(slide_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM slides WHERE id = %s", (slide_id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"deleted": slide_id}

@app.delete("/api/demos/{slug}")
def delete_demo(slug: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM demos WHERE slug = %s", (slug,))
    conn.commit()
    cur.close()
    conn.close()
    return {"deleted": slug}

# Serve frontend for all non-API routes
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

@app.get("/share/{slug}")
def serve_share(slug: str):
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

@app.get("/manage-xk92")
def serve_admin():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

@app.get("/")
def serve_root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

# Mount static assets last
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")
