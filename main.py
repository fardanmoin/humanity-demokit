from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import os, base64, json, io
import psycopg2
from psycopg2.extras import RealDictCursor

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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
            slide_type TEXT NOT NULL DEFAULT 'desktop'
        );
    """)
    conn.commit()
    migrations = [
        "ALTER TABLE demos ADD COLUMN IF NOT EXISTS product TEXT NOT NULL DEFAULT 'humanity'",
        "ALTER TABLE demos ADD COLUMN IF NOT EXISTS calendar_link TEXT NOT NULL DEFAULT 'https://hello.tcpsoftware.com/c/aaron-josetcpsoftware-com'",
        "ALTER TABLE demos ADD COLUMN IF NOT EXISTS app_screenshots JSONB NOT NULL DEFAULT '[]'",
        "ALTER TABLE slides ADD COLUMN IF NOT EXISTS hotspots JSONB NOT NULL DEFAULT '[]'",
        "ALTER TABLE slides ADD COLUMN IF NOT EXISTS slide_type TEXT NOT NULL DEFAULT 'desktop'",
    ]
    for m in migrations:
        try:
            cur.execute(m)
            conn.commit()
        except Exception as e:
            print(f"Migration skipped: {e}")
            conn.rollback()
    cur.close()
    conn.close()

try:
    init_db()
except Exception as e:
    print(f"DB init error: {e}")

def compress_image(content: bytes, mime: str, max_w: int = 1600) -> str:
    if not HAS_PIL:
        return f"data:{mime};base64,{base64.b64encode(content).decode()}"
    try:
        img = Image.open(io.BytesIO(content))
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        if img.width > max_w:
            img = img.resize((max_w, int(img.height * (max_w / img.width))), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=78, optimize=True)
        return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"
    except Exception as e:
        print(f"Compress error: {e}")
        return f"data:{mime};base64,{base64.b64encode(content).decode()}"

def compress_mobile(content: bytes, mime: str) -> str:
    return compress_image(content, mime, max_w=600)

class DemoCreate(BaseModel):
    product: Optional[str] = "humanity"
    slug: str
    title: str
    description: Optional[str] = ""
    calendar_link: Optional[str] = "https://hello.tcpsoftware.com/c/aaron-josetcpsoftware-com"

class Hotspot(BaseModel):
    x: float
    y: float
    title: str
    body: str
    position: str = "right"

@app.get("/api/health")
def health():
    return {"status": "ok", "pil": HAS_PIL}

@app.get("/api/debug")
def debug():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='demos' ORDER BY ordinal_position")
        dc = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='slides' ORDER BY ordinal_position")
        sc = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) as c FROM demos"); demo_c = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) as c FROM slides"); slide_c = cur.fetchone()["c"]
        cur.close(); conn.close()
        return {"status":"ok","pil":HAS_PIL,"demos_cols":dc,"slides_cols":sc,"demos":demo_c,"slides":slide_c}
    except Exception as e:
        return {"status":"error","error":str(e)}

@app.post("/api/demos")
def create_demo(demo: DemoCreate):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO demos (slug, title, description, product, calendar_link) VALUES (%s,%s,%s,%s,%s) RETURNING *",
            (demo.slug, demo.title, demo.description, demo.product or "humanity",
             demo.calendar_link or "https://hello.tcpsoftware.com/c/aaron-josetcpsoftware-com")
        )
        row = dict(cur.fetchone())
        conn.commit()
        return row
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Slug already exists")
    finally:
        cur.close(); conn.close()

@app.get("/api/demos")
def list_demos():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM demos ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows

@app.get("/api/demos/{slug}")
def get_demo(slug: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM demos WHERE slug=%s", (slug,))
    demo = cur.fetchone()
    if not demo:
        raise HTTPException(status_code=404, detail="Demo not found")
    demo = dict(demo)
    if isinstance(demo.get("app_screenshots"), str):
        demo["app_screenshots"] = json.loads(demo["app_screenshots"])
    cur.execute("SELECT * FROM slides WHERE demo_id=%s ORDER BY position ASC", (demo["id"],))
    slides = []
    for r in cur.fetchall():
        s = dict(r)
        if isinstance(s.get("hotspots"), str):
            s["hotspots"] = json.loads(s["hotspots"])
        slides.append(s)
    demo["slides"] = slides
    cur.close(); conn.close()
    return demo

@app.post("/api/slides")
async def create_slide(
    demo_id: int,
    position: int,
    hotspots: str = "[]",
    slide_type: str = "desktop",
    file: UploadFile = File(...)
):
    content = await file.read()
    mime = file.content_type or "image/png"
    if slide_type == "mobile":
        image_data = compress_mobile(content, mime)
    else:
        image_data = compress_image(content, mime)
    try:
        hotspots_data = json.loads(hotspots)
    except:
        hotspots_data = []
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO slides (demo_id, position, image_data, hotspots, slide_type) VALUES (%s,%s,%s,%s,%s) RETURNING id, demo_id, position, hotspots, slide_type",
        (demo_id, position, image_data, json.dumps(hotspots_data), slide_type)
    )
    row = dict(cur.fetchone())
    conn.commit()
    cur.close(); conn.close()
    return row

@app.post("/api/demos/{slug}/app-screenshots")
async def upload_app_screenshot(slug: str, file: UploadFile = File(...)):
    content = await file.read()
    mime = file.content_type or "image/png"
    image_data = compress_mobile(content, mime)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, app_screenshots FROM demos WHERE slug=%s", (slug,))
    demo = cur.fetchone()
    if not demo:
        raise HTTPException(status_code=404, detail="Demo not found")
    shots = demo["app_screenshots"] or []
    if isinstance(shots, str):
        shots = json.loads(shots)
    shots.append(image_data)
    cur.execute("UPDATE demos SET app_screenshots=%s WHERE slug=%s", (json.dumps(shots), slug))
    conn.commit()
    cur.close(); conn.close()
    return {"count": len(shots)}

@app.delete("/api/demos/{slug}/app-screenshots/{idx}")
def delete_app_screenshot(slug: str, idx: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT app_screenshots FROM demos WHERE slug=%s", (slug,))
    demo = cur.fetchone()
    shots = demo["app_screenshots"] or []
    if isinstance(shots, str):
        shots = json.loads(shots)
    if 0 <= idx < len(shots):
        shots.pop(idx)
    cur.execute("UPDATE demos SET app_screenshots=%s WHERE slug=%s", (json.dumps(shots), slug))
    conn.commit()
    cur.close(); conn.close()
    return {"count": len(shots)}

@app.delete("/api/slides/{slide_id}")
def delete_slide(slide_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM slides WHERE id=%s", (slide_id,))
    conn.commit()
    cur.close(); conn.close()
    return {"deleted": slide_id}

class SlideReorder(BaseModel):
    demo_id: int
    order: List[int]  # slide ids in new order

@app.post("/api/slides/reorder")
def reorder_slides(body: SlideReorder):
    conn = get_conn()
    cur = conn.cursor()
    for pos, slide_id in enumerate(body.order, start=1):
        cur.execute("UPDATE slides SET position=%s WHERE id=%s AND demo_id=%s", (pos, slide_id, body.demo_id))
    conn.commit()
    cur.close(); conn.close()
    return {"reordered": True}

@app.delete("/api/demos/{slug}")
def delete_demo(slug: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM demos WHERE slug=%s", (slug,))
    conn.commit()
    cur.close(); conn.close()
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
