import os
from pathlib import Path
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
DATASET_PATH=ROOT/'data'/'healthcare_dataset.csv'
POLICY_DIR=ROOT/'data'/'policies'
GROQ_API_KEY=os.getenv('GROQ_API_KEY','')
GROQ_MODEL=os.getenv('GROQ_MODEL','llama-3.3-70b-versatile')
EMBEDDING_MODEL=os.getenv('EMBEDDING_MODEL','sentence-transformers/all-MiniLM-L6-v2')
TOP_K=int(os.getenv('TOP_K','4'))
