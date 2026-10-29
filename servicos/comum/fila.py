"""
Fila de mensagens usando Redis (lista + BLPOP).

A API de ingestao so publica a tarefa aqui e devolve 202.
O worker de ingestao consome, gera os embeddings e grava o indice.
"""
import json
import os
import uuid

import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

FILA_INGESTAO = "fila_ingestao"
FILA_MORTA = "fila_ingestao_morta"   # dead-letter: tarefas que falharam todas as tentativas


def conectar():
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)


def publicar(r, docs):
    tarefa_id = str(uuid.uuid4())
    r.hset(f"tarefa:{tarefa_id}", mapping={"status": "na_fila", "documentos": len(docs)})
    r.rpush(FILA_INGESTAO, json.dumps({"id": tarefa_id, "docs": docs}))
    return tarefa_id


def consumir(r, timeout=5):
    """Bloqueia ate chegar mensagem (ou timeout). Devolve dict ou None."""
    item = r.blpop(FILA_INGESTAO, timeout=timeout)
    if item is None:
        return None
    return json.loads(item[1])


def atualizar_status(r, tarefa_id, **campos):
    r.hset(f"tarefa:{tarefa_id}", mapping={k: str(v) for k, v in campos.items()})
    r.expire(f"tarefa:{tarefa_id}", 24 * 3600)


def status(r, tarefa_id):
    return r.hgetall(f"tarefa:{tarefa_id}")
