# Humanity Demo Player

Your own Storylane-style interactive demo tool. Self-hosted on Render + Neon.

---

## Folder Structure

```
demo-player/
  backend/
    main.py              ← FastAPI app
    requirements.txt
    .python-version      ← pins Python 3.12.3
  frontend/
    index.html           ← full player + admin UI
  render.yaml
```

---

## Deploy on Render

### 1. Push to GitHub
Create a new repo and push this entire folder.

### 2. Create Neon PostgreSQL
- Go to neon.tech → New Project
- Copy the connection string (postgres://...)

### 3. Create Web Service on Render
- New → Web Service → connect your GitHub repo
- Root Directory: `backend`
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Add environment variable: `DATABASE_URL` = your Neon connection string

### 4. Done!
Render will build and deploy. DB tables auto-create on first boot.

---

## URLs

| URL | What it does |
|-----|-------------|
| `yourapp.onrender.com/manage-xk92` | Admin panel (password protected) |
| `yourapp.onrender.com/share/your-demo-slug` | Prospect-facing demo |

---

## Admin Password

Default: `tcp2024admin`

To change it, open `frontend/index.html` and find:
```js
const ADMIN_PASSWORD = "tcp2024admin";
```
Change it to whatever you want before deploying.

---

## How to create a demo

1. Go to `/manage-xk92` → enter password
2. **Create Demo tab** → enter title + slug (e.g. `humanity-schedule`)
3. **Add Slides tab** → select your demo → upload screenshots one by one
   - Click on the screenshot to place the hotspot (pulsing circle)
   - Write tooltip title + body for each slide
   - Set tooltip position (right/left/top/bottom)
4. Share: `yourapp.onrender.com/share/humanity-schedule`

---

## End screen

At the end of every demo, prospects see:
- "That's the full tour!"
- **"Let's Book a Demo"** button → links to your calendar
- Option to watch again

Calendar link: https://hello.tcpsoftware.com/c/aaron-josetcpsoftware-com
