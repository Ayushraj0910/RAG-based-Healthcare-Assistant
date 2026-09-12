# 🚀 How to Run

This project has two parts: a **FastAPI backend** and a **static frontend**. Normally they are separate processes, but the included launcher scripts can start both automatically.

## Prerequisites

- Python 3.10+
- Windows users: use `run.bat`
- Mac/Linux users: use `run.sh`
- (Optional) A [Groq API key](https://console.groq.com/) — the app works without one using local fallbacks, but you'll get better LLM-powered answers with it.

---

## ⭐ Recommended: Start Everything at Once

### Windows

Make sure `run.bat` is in the **project root**, next to the `backend/` and `frontend/` folders:

```text
healthcare_rag_assistant_app/
├── run.bat
├── backend/
└── frontend/
```

Then simply **double-click `run.bat`**.

It will:

1. Set up the backend virtual environment and install dependencies when needed.
2. Start the backend at `http://localhost:8000`.
3. Start the frontend at `http://localhost:5500`.
4. Wait until the backend is ready.
5. **Automatically open the main healthcare application in your browser.**

That's it — you do not need to manually start the backend and frontend in separate terminals.

### Mac/Linux

Place `run.sh` in the project root, next to `backend/` and `frontend/`:

```text
healthcare_rag_assistant_app/
├── run.sh
├── backend/
└── frontend/
```

Then run:

```bash
chmod +x run.sh
./run.sh
```

The script starts both services, waits for the backend health check to pass, and opens the application automatically.

---

## 🛠️ Manual Setup

If you don't want to use the launcher, you can start the backend and frontend separately.

### 1. Start the Backend

```bash
cd backend

# Create a virtual environment (recommended)
python -m venv .venv

# Windows
.venv\Scripts\activate

# Mac/Linux
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Optional: configure Groq
# Copy .env.example to .env and set:
# GROQ_API_KEY=your_key_here

# Run the backend
uvicorn main:app --reload --port 8000
```

The backend will:

- Load the synthetic patient dataset into a local SQLite database (first run only).
- Build the policy embedding index for the RAG agent (first run only).
- Fall back to TF-IDF automatically if `sentence-transformers` isn't installed.

Once running, check that the backend is healthy:

```bash
curl http://localhost:8000/api/health
```

---

### 2. Start the Frontend

Open a **new terminal** and leave the backend running:

```bash
cd frontend
python -m http.server 5500
```

Then open:

```text
http://localhost:5500
```

This is the main healthcare chat application where you can select roles and ask questions.

> If your backend is running on a different host/port, point the frontend at it by adding this line to `frontend/index.html`, above the `<script src="app.js">` tag:
>
> ```html
> <script>window.HEALTHCARE_API_BASE = "https://your-backend-host";</script>
> ```

---

## 🩺 Try It Out

In the app sidebar:

1. Pick an access role (`front_desk`, `clinician`, `billing`, or `admin`).
2. Ask a question, for example:
   - *"How many patients have diabetes?"* → patient-records (SQL) agent.
   - *"What is the HIPAA minimum necessary standard?"* → hospital-policy (RAG) agent with citations.
   - *"I have a cold, what should I do?"* → general health assistant.

---

## 🛑 Stopping the App

### When using `run.bat` / `run.sh`

Use `Ctrl+C` in the launcher terminal to stop the running services. On Windows, if the launcher opened separate command windows, closing those windows will also stop the corresponding processes.

### When running manually

Press `Ctrl+C` in each terminal to stop the backend and frontend servers.
