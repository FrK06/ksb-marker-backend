\# KSB Coursework Marker



AI-powered coursework grading tool for apprenticeship programmes.

Grades student reports against KSB (Knowledge, Skills, Behaviours) criteria using Google Gemini AI.



\## Live App

🌐 \*\*Frontend:\*\* https://webrag-451411.web.app

🔧 \*\*Backend API:\*\* https://kb-chatbot-api-937599122816.europe-west2.run.app



\## Supported Modules

\- \*\*DSP\*\* — Data Science Principles (19 KSBs)

\- \*\*MLCC\*\* — Machine Learning Cloud Computing (11 KSBs)

\- \*\*AIDI\*\* — AI \& Digital Innovation (19 KSBs)



\## Architecture

\- \*\*Frontend:\*\* React, deployed on Firebase Hosting

\- \*\*Backend:\*\* FastAPI + Python, deployed on Google Cloud Run

\- \*\*AI:\*\* Google Gemini 2.5 Flash via Google AI Studio API

\- \*\*Document parsing:\*\* pdfplumber (PDF), python-docx (DOCX)



\## Google Cloud Setup

\- \*\*GCP Project:\*\* `webrag-451411`

\- \*\*Region:\*\* `europe-west2` (London)

\- \*\*Cloud Run service:\*\* `kb-chatbot-api`

\- \*\*Firebase project:\*\* `webrag-451411` (WebRAG)

\- \*\*Cloud Storage bucket:\*\* `gs://kb-chatbot-docs-webrag`

\- \*\*Vertex AI data store:\*\* `kb-datastore` (location: eu)

\- \*\*Vertex AI search engine:\*\* `kb-chatbot-engine`



\## API Keys \& Credentials

\- \*\*Gemini API key:\*\* stored as Cloud Run env var `GEMINI\_API\_KEY`

&#x20; - Manage at: https://aistudio.google.com/apikey (project: webrag-451411)

\- \*\*GCP account:\*\* dario.dinuzzo@gmail.com



\## Local Development



\### Prerequisites

\- Python 3.11+

\- Node.js 18+

\- Google Cloud CLI (`gcloud`)

\- Git



\### Backend Setup

```bash

cd kb-chatbot

python -m venv venv

venv\\Scripts\\activate        # Windows

pip install -r requirements.txt

gcloud auth application-default login --scopes=https://www.googleapis.com/auth/cloud-platform

uvicorn main:app --reload

\# Runs at http://127.0.0.1:8000

```



\### Frontend Setup

```bash

cd kb-frontend

npm install

npm start

\# Runs at http://localhost:3000

\# Make sure API\_URL in src/App.js points to http://127.0.0.1:8000 for local dev

```



\## Deployment



\### Deploy Backend (Cloud Run)

```bash

cd kb-chatbot

gcloud config set project webrag-451411

gcloud run deploy kb-chatbot-api \\

&#x20; --source . \\

&#x20; --region europe-west2 \\

&#x20; --allow-unauthenticated \\

&#x20; --set-env-vars GEMINI\_API\_KEY=YOUR\_API\_KEY\_HERE

```



\### Deploy Frontend (Firebase Hosting)

```bash

cd kb-frontend

\# Make sure API\_URL in src/App.js points to Cloud Run URL

npm run build

firebase deploy

```



\### Cloud Run URL

```

https://kb-chatbot-api-937599122816.europe-west2.run.app

```



\### Firebase Hosting URL

```

https://webrag-451411.web.app

```



\## Key Commands



\### GCP / gcloud

```bash

\# Set active project

gcloud config set project webrag-451411



\# Check active project

gcloud config get project



\# Enable APIs

gcloud services enable aiplatform.googleapis.com

gcloud services enable run.googleapis.com

gcloud services enable storage.googleapis.com

gcloud services enable discoveryengine.googleapis.com



\# Authenticate Python SDK

gcloud auth application-default login --scopes=https://www.googleapis.com/auth/cloud-platform

```



\### Cloud Storage

```bash

\# Upload document to bucket

gcloud storage cp docs/report.pdf gs://kb-chatbot-docs-webrag/



\# List bucket contents

gcloud storage ls gs://kb-chatbot-docs-webrag/

```



\## Project Structure

```

kb-chatbot/          ← Backend (FastAPI)

├── main.py          ← API routes + grading logic

├── ingest.py        ← Vertex AI data store ingestion

├── requirements.txt

├── Dockerfile

└── .env             ← Local env vars (not committed)



kb-frontend/         ← Frontend (React)

├── src/

│   └── App.js       ← Main React component

├── public/

└── build/           ← Production build (generated)

```



\## Environment Variables

| Variable | Description | Where |

|----------|-------------|-------|

| `GEMINI\_API\_KEY` | Google AI Studio API key | Cloud Run env var |

| `PROJECT\_ID` | GCP project ID (`webrag-451411`) | .env (local) |

| `REGION` | GCP region (`us-central1`) | .env (local) |



\## Costs (approximate)

\- \*\*Cloud Run:\*\* \~£0/month (scales to zero, free tier covers light usage)

\- \*\*Firebase Hosting:\*\* Free tier (10GB storage, 360MB/day transfer)

\- \*\*Gemini API:\*\* Free tier for low usage, then per-token pricing

\- \*\*Vertex AI Search:\*\* \~£3-8/month if using the data store



\## Notes

\- The `.env` file is excluded from git (contains secrets)

\- The Gemini API key in Cloud Run is set as an environment variable — rotate it at aistudio.google.com if compromised

\- Cloud Run scales to zero when not in use — first request after idle may take 2-3 seconds to cold start

