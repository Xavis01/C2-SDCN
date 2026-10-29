"""
Servico 1 - INGESTAO (API): recebe documentos e publica na fila.

Quem gera os embeddings e salva o indice e o worker (worker.py), que roda
como outro processo. Assim o POST /indexar nao fica preso esperando.

Rodar: uvicorn servicos.ingestao.app:app --port 8001
"""
import logging

import redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from servicos.comum import fila
from servicos.ingestao import indice

logging.basicConfig(level=logging.INFO, format="%(asctime)s [ingestao] %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Ingestao - C2.A2")
r = fila.conectar()


class Documento(BaseModel):
    texto: str
    origem: str = "desconhecida"


@app.post("/indexar", status_code=202)
def indexar(docs: list[Documento]):
    if not docs:
        raise HTTPException(400, "mande ao menos um documento")
    try:
        tarefa_id = fila.publicar(r, [d.model_dump() for d in docs])
    except redis.RedisError as e:
        log.error("redis fora do ar: %s", e)
        raise HTTPException(503, "fila indisponivel, tente de novo")
    log.info("tarefa %s publicada com %d docs", tarefa_id, len(docs))
    return {"tarefa": tarefa_id, "status": "na_fila"}


@app.get("/tarefas/{tarefa_id}")
def ver_tarefa(tarefa_id: str):
    st = fila.status(r, tarefa_id)
    if not st:
        raise HTTPException(404, "tarefa nao encontrada")
    return {"tarefa": tarefa_id, **st}


@app.get("/indice")
def ver_indice():
    """Consumido pelo servico de recuperacao."""
    dados = indice.carregar()
    return {"versao": dados["versao"], "total": len(dados["itens"]),
            "itens": dados["itens"]}


@app.get("/saude")
def saude():
    try:
        r.ping()
        redis_ok = True
    except redis.RedisError:
        redis_ok = False
    dados = indice.carregar()
    return {"status": "ok", "redis": redis_ok, "documentos": len(dados["itens"]),
            "versao_indice": dados["versao"]}
