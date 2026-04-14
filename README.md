# AI Cloud Agent

An AI-powered cloud infrastructure deployment agent.
Deploy EC2 servers, S3 buckets, Docker containers, and more using plain English.

---

## Setup (First Time)

### 1. Create virtual environment
```bash
cd C:\Users\sumit\ai-cloud-agent
python -m venv venv
venv\Scripts\activate
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Set up environment variables
```bash
copy .env.example .env
# Open .env and fill in your ANTHROPIC_API_KEY and APP_SECRET_KEY
```

### 4. Initialize the database
```bash
python db/init_db.py
```

### 5. Run the app
```bash
streamlit run app.py
```

---

## Project Structure

```
ai-cloud-agent/
├── app.py                  # Streamlit entry point + all pages
├── requirements.txt
├── .env.example
├── .gitignore
│
├── agent/                  # AI pipeline (intent → extract → execute)
│   ├── intent.py
│   ├── extractor.py
│   ├── gap_filler.py
│   └── executor.py
│
├── auth/                   # Login, signup, credential encryption
│   ├── register.py
│   └── session.py
│
├── db/
│   ├── init_db.py          # SQLite schema setup
│   └── users.db            # Created on first run (gitignored)
│
├── templates/              # Jinja2 Terraform templates (.tf.j2)
├── policies/               # Policy validator
├── workspaces/             # Per-user Terraform state (gitignored)
└── monitoring/             # CloudWatch integration
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| UI | Streamlit |
| LLM | Claude API (Sonnet) |
| Orchestration | LangChain |
| IaC | Terraform |
| AWS SDK | boto3 |
| Encryption | Fernet (cryptography) + bcrypt |
| Database | SQLite |
| Templates | Jinja2 |
| Docker (remote) | docker-py + Paramiko |
