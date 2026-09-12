# 🚀 How to Run

This project has two parts that run separately: a **FastAPI backend** and a **static frontend**. Start the backend first, then the frontend.

## Prerequisites

- Python 3.10+
- (Optional) A [Groq API key](https://console.groq.com/) — the app works without one using local fallbacks, but you'll get much better answers with it

## 1. Start the Backend

```bash
cd backend

# Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate      # on Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# (Optional) Add your Groq API key
cp .env.example .env
# then open .env and set GROQ_API_KEY=your_key_here

# Run the server
uvicorn main:app --reload --port 8000
```

The backend will:
- Load the synthetic patient dataset into a local SQLite database (first run only)
- Build the policy embedding index for the RAG agent (first run only — falls back to TF-IDF automatically if `sentence-transformers` isn't installed)

Once running, check it's healthy:

```bash
curl http://localhost:8000/api/health
```

## 2. Start the Frontend

Open a **new terminal** (leave the backend running) and serve the static frontend:

```bash
cd frontend
python -m http.server 5500
```

Then open your browser to:

```
http://localhost:5500
```

> If your backend is running on a different host/port, point the frontend at it by adding this line to `frontend/index.html`, above the `<script src="app.js">` tag:
> ```html
> <script>window.HEALTHCARE_API_BASE = "https://your-backend-host";</script>
> ```

## 3. Try It Out

In the app sidebar:
1. (Optional) Paste your Groq API key for LLM-powered answers
2. Pick an access role (`front_desk`, `clinician`, `billing`, or `admin`) to see role-based access control in action
3. Ask a question, e.g.:
   - *"How many patients have diabetes?"* → routes to the patient-records (SQL) agent
   - *"What is the HIPAA minimum necessary standard?"* → routes to the hospital-policy (RAG) agent, with citations
   - *"I have a cold, what should I do?"* → routes to the general health assistant

## Stopping the App

Press `Ctrl+C` in each terminal to stop the backend and frontend servers.
