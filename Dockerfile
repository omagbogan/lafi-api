FROM python:3.11-slim

WORKDIR /app

# Dépendances système légères pour PyTorch et Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Installation des dépendances avec PyTorch CPU (très rapide et léger)
COPY requirements.txt .
RUN pip install --no-cache-dir torch torchvision --extra-index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# Copie de l'API et des modèles IA
COPY . .

# Dossier d'upload pour les photos de produits
RUN mkdir -p /app/uploads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

