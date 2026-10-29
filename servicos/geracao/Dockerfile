FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY servicos/__init__.py servicos/__init__.py
COPY servicos/comum servicos/comum
COPY servicos/geracao servicos/geracao
EXPOSE 8003
CMD ["uvicorn", "servicos.geracao.app:app", "--host", "0.0.0.0", "--port", "8003"]
