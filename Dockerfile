FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir --default-timeout=100 -r requirements.txt

COPY . .

# Commande pour lancer l'application quand le conteneur démarre
CMD ["python", "tengo.py"]