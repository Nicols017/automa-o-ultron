FROM python:3.11-slim

WORKDIR /app

# Instala dependências de rede e sistema necessárias para compilação e WinRM
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libkrb5-dev \
    gcc \
    curl \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# Copia e instala as dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código da aplicação
COPY . .

EXPOSE 7000

# Executa o servidor FastAPI com Uvicorn
CMD ["python", "main.py"]
