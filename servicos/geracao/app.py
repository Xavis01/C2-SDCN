"""
Servico 3 - GERACAO: chama a recuperacao, monta o prompt e chama o LLM.

A chamada ao LLM passa por: tempo-limite -> retentativa -> circuit breaker.
Se o LLM nao responder, devolve 503 com os trechos recuperados (degrada
sem quebrar).

Rodar: uvicorn servicos.geracao.app:app --port 8003
"""
import logging
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturoTimeout

import requests
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from servicos.comum.circuit_breaker import CircuitBreaker, CircuitoAberto
from servicos.comum.llm import gerar

logging.basicConfig(level=logging.INFO, format="%(asctime)s [geracao] %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Geracao - C2.A2")
URL_RECUPERACAO = os.getenv("URL_RECUPERACAO", "http://localhost:8002")

LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "20"))
LLM_TENTATIVAS = int(os.getenv("LLM_TENTATIVAS", "3"))
LLM_ESPERA_BASE = float(os.getenv("LLM_ESPERA_BASE", "0.5"))  # backoff: 0.5s, 1s, 2s...

disjuntor = CircuitBreaker(limite_falhas=3, espera_segundos=20)
# disjuntor separado pra recuperacao, se ela cair a gente para de insistir
disjuntor_recuperacao = CircuitBreaker(limite_falhas=3, espera_segundos=10)

_executor = ThreadPoolExecutor(max_workers=8)

# falha simulada pra testar o disjuntor sem precisar derrubar a internet
SIMULACAO = {
    "taxa_falha": float(os.getenv("LLM_TAXA_FALHA", "0")),
    "atraso": float(os.getenv("LLM_ATRASO", "0")),
}


class Pergunta(BaseModel):
    pergunta: str
    top_k: int = 3


class Simulacao(BaseModel):
    taxa_falha: float = 0.0   # 0 a 1
    atraso: float = 0.0       # segundos


def _gerar_simulando(pergunta, contexto):
    if SIMULACAO["atraso"]:
        time.sleep(SIMULACAO["atraso"])
    if random.random() < SIMULACAO["taxa_falha"]:
        raise RuntimeError("falha simulada do LLM")
    return gerar(pergunta, contexto)


def chamar_llm_com_timeout(pergunta, contexto):
    # o requests ja tem timeout, mas aqui garante tambem no modo simulado
    futuro = _executor.submit(_gerar_simulando, pergunta, contexto)
    try:
        return futuro.result(timeout=LLM_TIMEOUT)
    except FuturoTimeout:
        raise TimeoutError(f"LLM nao respondeu em {LLM_TIMEOUT}s")


def chamar_llm(pergunta, contexto):
    """Retentativa com backoff, cada tentativa passa pelo disjuntor."""
    ultimo_erro = None
    for tentativa in range(1, LLM_TENTATIVAS + 1):
        try:
            return disjuntor.chamar(chamar_llm_com_timeout, pergunta, contexto)
        except CircuitoAberto:
            raise
        except Exception as e:
            ultimo_erro = e
            log.warning("LLM falhou (tentativa %d/%d): %s | disjuntor=%s",
                        tentativa, LLM_TENTATIVAS, e, disjuntor.estado)
            if tentativa < LLM_TENTATIVAS:
                time.sleep(LLM_ESPERA_BASE * 2 ** (tentativa - 1))
    raise ultimo_erro


def buscar_trechos(pergunta, top_k):
    def _buscar():
        r = requests.post(f"{URL_RECUPERACAO}/buscar",
                          json={"pergunta": pergunta, "top_k": top_k}, timeout=10)
        r.raise_for_status()
        return r.json()["resultados"]
    return disjuntor_recuperacao.chamar(_buscar)


def _fontes(resultados):
    vistas = []
    for t in resultados:
        if t["origem"] not in vistas:
            vistas.append(t["origem"])
    return vistas


@app.post("/perguntar")
def perguntar(p: Pergunta):
    inicio = time.time()
    try:
        resultados = buscar_trechos(p.pergunta, p.top_k)
    except CircuitoAberto:
        return JSONResponse(status_code=503, content={
            "erro": "servico de recuperacao indisponivel (disjuntor aberto), tente mais tarde"})
    except requests.RequestException as e:
        log.error("recuperacao falhou: %s", e)
        return JSONResponse(status_code=503, content={
            "erro": "servico de recuperacao indisponivel"})

    if not resultados:
        return {"pergunta": p.pergunta,
                "resposta": "Nao encontrei nada nos documentos indexados sobre isso.",
                "fontes": [], "trechos": []}

    contexto = [t["texto"] for t in resultados]
    try:
        resposta = chamar_llm(p.pergunta, contexto)
    except CircuitoAberto:
        log.warning("disjuntor aberto, recusando chamada ao LLM")
        return JSONResponse(status_code=503, content={
            "erro": "LLM indisponivel no momento (disjuntor aberto), tente em alguns segundos",
            "disjuntor": disjuntor.estado,
            "fontes": _fontes(resultados), "trechos": resultados})
    except Exception as e:
        return JSONResponse(status_code=503, content={
            "erro": f"LLM falhou depois de {LLM_TENTATIVAS} tentativas: {e}",
            "disjuntor": disjuntor.estado,
            "fontes": _fontes(resultados), "trechos": resultados})

    log.info("pergunta '%s' respondida (%.0f ms)", p.pergunta[:40], (time.time() - inicio) * 1000)
    return {"pergunta": p.pergunta, "resposta": resposta,
            "fontes": _fontes(resultados), "trechos": resultados}


@app.post("/simular-falha")
def simular_falha(s: Simulacao):
    """So pra teste: faz o LLM falhar ou demorar de proposito."""
    SIMULACAO.update(taxa_falha=s.taxa_falha, atraso=s.atraso)
    log.info("simulacao alterada: %s", SIMULACAO)
    return SIMULACAO


@app.get("/saude")
def saude():
    return {"status": "ok", "disjuntor": disjuntor.estado, "falhas": disjuntor.falhas,
            "disjuntor_recuperacao": disjuntor_recuperacao.estado, "simulacao": SIMULACAO}
