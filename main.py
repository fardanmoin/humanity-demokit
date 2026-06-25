from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import os, base64, json, io
import psycopg2
from psycopg2.extras import RealDictCursor

# Try to import Pillow for image compression
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

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
            hotspots JSONB NOT NULL DEFAULT '[]'
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

try:
    init_db()
except Exception as e:
    print(f"DB init error: {e}")

def compress_image(content: bytes, mime: str) -> tuple[str, str]:
    """Compress image using Pillow if available, else return as-is."""
    if not HAS_PIL:
        b64 = base64.b64encode(content).decode()
        return f"data:{mime};base64,{b64}", mime

    try:
        img = Image.open(io.BytesIO(content))
        # Convert RGBA to RGB if needed
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        # Resize if wider than 1600px
        max_w = 1600
        if img.width > max_w:
            ratio = max_w / img.width
            img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)
        # Save as JPEG with quality 75
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75, optimize=True)
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode()
        return f"data:image/jpeg;base64,{b64}", "image/jpeg"
    except Exception as e:
        print(f"Compression error: {e}")
        b64 = base64.b64encode(content).decode()
        return f"data:{mime};base64,{b64}", mime

class DemoCreate(BaseModel):
    slug: str
    title: str
    description: Optional[str] = ""

class Hotspot(BaseModel):
    x: float
    y: float
    title: str
    body: str
    position: str = "right"

class SlideHotspotsUpdate(BaseModel):
    hotspots: List[Hotspot]

@app.get("/api/health")
def health():
    return {"status": "ok", "pil": HAS_PIL}

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
    cur.execute("SELECT * FROM slides WHERE demo_id = %s ORDER BY position ASC", (demo["id"],))
    slides = []
    for r in cur.fetchall():
        s = dict(r)
        if isinstance(s["hotspots"], str):
            s["hotspots"] = json.loads(s["hotspots"])
        slides.append(s)
    demo["slides"] = slides
    cur.close()
    conn.close()
    return demo

@app.post("/api/slides")
async def create_slide(
    demo_id: int,
    position: int,
    hotspots: str = "[]",
    file: UploadFile = File(...)
):
    content = await file.read()
    mime = file.content_type or "image/png"
    image_data, _ = compress_image(content, mime)

    try:
        hotspots_data = json.loads(hotspots)
    except:
        hotspots_data = []

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO slides (demo_id, position, image_data, hotspots) VALUES (%s, %s, %s, %s) RETURNING id, demo_id, position, hotspots",
        (demo_id, position, image_data, json.dumps(hotspots_data))
    )
    row = dict(cur.fetchone())
    conn.commit()
    cur.close()
    conn.close()
    return row

@app.patch("/api/slides/{slide_id}/hotspots")
def update_hotspots(slide_id: int, update: SlideHotspotsUpdate):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE slides SET hotspots = %s WHERE id = %s RETURNING id",
        (json.dumps([h.dict() for h in update.hotspots]), slide_id)
    )
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

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "index.html")

@app.get("/share/{slug}")
def serve_share(slug: str):
    return FileResponse(INDEX)

@app.get("/manage-xk92")
def serve_admin():
    return FileResponse(INDEX)

@app.get("/")
def serve_root():
    return FileResponse(INDEX)
