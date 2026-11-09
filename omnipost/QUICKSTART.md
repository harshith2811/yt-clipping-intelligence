# ⚡ 5-Minute Quickstart Guide

Get the **Advocate Social Media Automation & Video Publishing Suite** running locally or deployed to production in minutes.

---

## 🏃 Method 1: Local Docker (Easiest)

### 1. Copy the Environment Template
In the root directory, create your `.env` file:
```bash
cp .env.example .env
```

### 2. Set Your Security Passkeys
Open `.env` and set these two keys:
```env
CHAMBERS_ADMIN_SECRET_KEY=my_secure_chambers_key_2026
AUTOMATION_SECRET_KEY=my_secure_automation_key_2026
N8N_ENCRYPTION_KEY=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

### 3. Launch with 1-Click
On Windows:
```cmd
double-click start-all.bat
```
Or on Linux / macOS / PowerShell:
```bash
docker compose up -d --build
```

### 4. Access Your Portals
- **Video & Social Posting Portal**: Open [http://localhost:3300](http://localhost:3300)
- **n8n Workflow Hub**: Open [http://localhost:5678](http://localhost:5678)

Log into the Web Portal using your `CHAMBERS_ADMIN_SECRET_KEY` or `AUTOMATION_SECRET_KEY`.

---

## 💻 Method 2: Native Node.js (No Docker Required)

If you only want to test the Web Portal and social media publishing on your local machine:

### 1. Install & Build
```bash
cd web
npm install
```

### 2. Start Both Backend Server & React Client
```bash
npm run dev
```
- Frontend with hot-reload: [http://localhost:5173](http://localhost:5173)
- Express API server: [http://localhost:3300](http://localhost:3300)

### 3. Run the Automated Tests
Verify all 68 tests pass:
```bash
npm test
```

---

## ☁️ Method 3: Free Cloud Deployment on Render ($0/month)

1. Push this folder to a new private GitHub repository.
2. Sign up or log into [Render](https://render.com/).
3. Click **New +** -> **Blueprint**.
4. Select your GitHub repository.
5. Render reads [`render.yaml`](render.yaml) and automatically creates:
   - `advocate-content-portal` (Web Service)
   - `n8n-automation` (Web Service)
6. Under the Environment settings in the Render dashboard, input your secrets (Supabase database details, Meta API tokens, YouTube OAuth).
7. Click **Apply** — Render builds the Docker containers and goes live!

---

## 📹 How to Publish a Video

1. Open the Web Portal ([http://localhost:3300](http://localhost:3300) or your production domain).
2. Click **New Post / Video** in the top navigation.
3. Select your channels (e.g. **YouTube**, **Instagram**, **Facebook**, **LinkedIn**).
4. Drag and drop your `.mp4` video into the uploader.
5. Enter your Title, Description, and Tags. Observe live platform preview cards.
6. Choose:
   - **Publish Now**: Sends immediately to all selected networks.
   - **Schedule**: Pick a date and time in `Asia/Kolkata` (IST).
7. View your post's status and live links in the **Content Calendar Feed**!
