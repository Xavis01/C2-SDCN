"""
Manda todos os .txt da pasta documentos/ pro servico de ingestao
e espera o worker terminar de indexar.

Uso: python scripts/carregar_documentos.py [url_ingestao]
"""
import pathlib
import sys
import time

import requests

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001"
PASTA = pathlib.Path(__file__).resolve().parent.parent / "documentos"

docs = [{"texto": p.read_text(encoding="utf-8"), "origem": p.stem}
        for p in sorted(PASTA.glob("*.txt"))]
r = requests.post(f"{URL}/indexar", json=docs, timeout=10)
r.raise_for_status()
tarefa = r.json()["tarefa"]
print(f"{len(docs)} documentos enviados, tarefa {tarefa} (status {r.status_code})")

for _ in range(30):
    st = requests.get(f"{URL}/tarefas/{tarefa}", timeout=5).json()
    print("status:", st["status"])
    if st["status"] in ("concluida", "falhou"):
        print(st)
        break
    time.sleep(1)
