# 🚀 Pro Web Scraper - Deployment Guide

## Free Hosting Options

### 1️⃣ **Render.com (Recommended - Best Free Option)**

**Steps:**
1. Go to https://render.com
2. Sign up with GitHub
3. Click "New +" → "Web Service"
4. Connect your GitHub repo or upload files
5. Settings:
   - **Name**: pro-scraper
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT --timeout 300`
   - **Instance Type**: Free
6. Add Environment Variables:
   - `PYTHON_VERSION` = `3.11.0`
7. Click "Create Web Service"
8. Wait 5-10 minutes for deployment
9. Your app will be live at: `https://pro-scraper.onrender.com`

**Pros:**
- ✅ Free SSL
- ✅ Auto-deploy from GitHub
- ✅ 750 hours/month free
- ✅ Supports Selenium

---

### 2️⃣ **Railway.app (Fast & Easy)**

**Steps:**
1. Go to https://railway.app
2. Sign up with GitHub
3. Click "New Project" → "Deploy from GitHub repo"
4. Select your repo
5. Railway auto-detects Python
6. Add Environment Variables:
   - `PORT` = `5000`
7. Deploy automatically
8. Get your URL: `https://your-app.up.railway.app`

**Pros:**
- ✅ $5 free credit/month
- ✅ Very fast deployment
- ✅ Easy to use

---

### 3️⃣ **PythonAnywhere (Simple)**

**Steps:**
1. Go to https://www.pythonanywhere.com
2. Sign up for free account
3. Go to "Web" tab → "Add a new web app"
4. Choose Flask
5. Upload your files via "Files" tab
6. Install requirements: `pip install -r requirements.txt`
7. Configure WSGI file to point to `app.py`
8. Reload web app
9. Access at: `https://yourusername.pythonanywhere.com`

**Pros:**
- ✅ Simple setup
- ✅ Free tier available
- ❌ Limited Selenium support

---

### 4️⃣ **Fly.io (Advanced)**

**Steps:**
1. Install flyctl: `curl -L https://fly.io/install.sh | sh`
2. Sign up: `flyctl auth signup`
3. In project folder: `flyctl launch`
4. Follow prompts
5. Deploy: `flyctl deploy`
6. Access at: `https://your-app.fly.dev`

**Pros:**
- ✅ Free tier
- ✅ Good performance
- ✅ Supports Selenium

---

## 📦 Quick Deploy Files

All files are ready in `/tmp/scraper_project/`:
- `app.py` - Main application
- `templates/index.html` - Frontend
- `requirements.txt` - Dependencies
- `Procfile` - For Heroku/Render
- `runtime.txt` - Python version

---

## 🔧 Local Testing

```bash
cd /tmp/scraper_project
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open: http://localhost:5000

---

## 🌐 Share with Team

Once deployed, share the URL with your team:
- `https://your-app.onrender.com`
- Everyone can access simultaneously
- No installation needed
- Works on any device

---

## ⚠️ Important Notes

1. **Free tier limitations:**
   - Render: Sleeps after 15 min inactivity
   - Railway: $5 credit/month
   - May need to upgrade for heavy usage

2. **Selenium on free hosting:**
   - Render supports it
   - Railway supports it
   - PythonAnywhere has limitations

3. **For production:**
   - Consider paid plans for better performance
   - Use environment variables for sensitive data
   - Monitor usage and costs

---

## 🚀 Recommended: Render.com

**Best for your team because:**
- ✅ Free forever
- ✅ Easy setup (5 minutes)
- ✅ Supports Selenium
- ✅ Auto-deploy from GitHub
- ✅ Free SSL certificate
- ✅ Multiple team members can use

**Deploy now:** https://render.com
