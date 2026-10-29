"""
Servico 2 - RECUPERACAO: dada uma pergunta, acha os trechos mais relevantes.

Busca o indice no servico de ingestao (REST), vetoriza a pergunta com o
mesmo vocabulario e ordena os trechos pela similaridade do cosseno.

Rodar: uvicorn servicos.recuperacao.app:app --port 8002
"""
import logging
import os
import re
import threading
import time

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from servicos.comum.embeddings import Vetorizador, similaridade

logging.basicConfig(level=logging.INFO, format="%(asctime)s [recuperacao] %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Recuperacao - C2.A2")
URL_INGESTAO = os.getenv("URL_INGESTAO", "http://localhost:8001")

# guarda o vetorizador da ultima versao do indice pra nao reajustar toda hora
_cache = {"versao": None, "vet": None}
_trava = threading.Lock()

SCORE_MINIMO = float(os.getenv("SCORE_MINIMO", "0.05"))

# palavras que nao ajudam na busca (senao "bolo de cenoura" casa pelo "de")
STOPWORDS = set("""a o e de da do das dos em no na nos nas um uma uns umas que
qual quais como por para pra com sem se ao aos as os ou e é sobre diz fala""".split())


class Consulta(BaseModel):
    pergunta: str
    top_k: int = 3


def vetorizador_para(versao, itens):
    # TF-IDF e deterministico: ajustando nos mesmos textos, na mesma ordem,
    # da o mesmo vocabulario que a ingestao usou pra gerar os vetores
    with _trava:
        if _cache["versao"] != versao:
            vet = Vetorizador()
            vet.ajustar([i["texto"] for i in itens])
            _cache.update(versao=versao, vet=vet)
        return _cache["vet"]


@app.post("/buscar")
def buscar(consulta: Consulta):
    inicio = time.time()
    try:
        r = requests.get(f"{URL_INGESTAO}/indice", timeout=5)
        r.raise_for_status()
    except requests.RequestException as e:
        log.error("ingestao indisponivel: %s", e)
        raise HTTPException(503, "servico de ingestao indisponivel")
    dados = r.json()
    itens = dados["itens"]
    if not itens:
        return {"pergunta": consulta.pergunta, "resultados": []}

    vet = vetorizador_para(dados["versao"], itens)
    palavras = [w for w in re.findall(r"\w+", consulta.pergunta.lower()) if w not in STOPWORDS]
    vp = vet.vetorizar(" ".join(palavras))

    pontuados = [(similaridade(vp, i["vetor"]), i) for i in itens]
    pontuados.sort(key=lambda x: x[0], reverse=True)
    resultados = [{"texto": i["texto"], "origem": i["origem"], "score": round(s, 4)}
                  for s, i in pontuados[:consulta.top_k] if s >= SCORE_MINIMO]

    log.info("busca '%s' -> %d resultados (%.0f ms)", consulta.pergunta[:40],
             len(resultados), (time.time() - inicio) * 1000)
    return {"pergunta": consulta.pergunta, "resultados": resultados}


@app.get("/saude")
def saude():
    return {"status": "ok", "versao_indice_em_cache": _cache["versao"]}
