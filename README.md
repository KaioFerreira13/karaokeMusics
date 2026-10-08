# Karaoke Musics

Pipeline orientado a tarefas: **download → remoção de voz → transcrição (palavra/timestamp) → legendas dinâmicas → render final (instrumental + legendas)**.

## Estrutura
```
backend/   FastAPI (Python)
  app/api/               rotas HTTP
  app/core/              config, modelos de job
  app/pipeline/          orquestrador de tarefas
  app/pipeline/tasks/    uma tarefa por etapa (download, separate, transcribe, subtitles, render)
frontend/  React + Vite
data/jobs/ artefatos por job (ignorado no git)
```

## Setup
Requisitos: **Python 3.12** (WhisperX não suporta 3.13+), Node 18+, FFmpeg no PATH.

### Backend

A partir da pasta raiz do projeto (`karaokeMusics`), abra um terminal e execute:

```powershell
# 1. Entre na pasta do backend
cd backend

# 2. Crie o ambiente virtual (Certifique-se de usar o Python 3.12)
# Dica: No Windows, use `py -3.12` para garantir a versão correta.
py -3.12 -m venv .venv 

# 3. Instale as dependências básicas
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 4. Instale as dependências de Machine Learning (Demucs, WhisperX, etc)
.\.venv\Scripts\python.exe -m pip install -r requirements-ml.txt

# 5. Inicie o servidor
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```
> **Nota:** Se você receber um erro `[WinError 10013]`, significa que a porta 8000 já está em uso por outro processo (pode ser que o servidor já esteja rodando em uma janela separada!).

Health check: http://localhost:8000/api/health

### Frontend

Abra um **novo terminal** a partir da pasta raiz do projeto (`karaokeMusics`) e execute:

```powershell
# 1. Entre na pasta do frontend
cd frontend

# 2. Instale as dependências
npm install

# 3. Inicie o servidor de desenvolvimento
npm run dev
```

Acesse a interface no seu navegador: http://localhost:5173
