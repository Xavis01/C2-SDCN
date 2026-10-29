"""
Worker de INGESTAO: consome a fila, quebra os textos em trechos,
gera os embeddings e salva o indice em disco.

Rodar: python -m servicos.ingestao.worker
"""
import hashlib
import json
import logging
import re
import time

import redis

from servicos.comum import fila
from servicos.comum.embeddings import Vetorizador
from servicos.ingestao import indice

logging.basicConfig(level=logging.INFO, format="%(asctime)s [worker-ingestao] %(message)s")
log = logging.getLogger(__name__)

TENTATIVAS = 3
TAMANHO_TRECHO = 400  # caracteres, mais ou menos


def quebrar_em_trechos(texto):
    """Junta frases ate dar ~TAMANHO_TRECHO caracteres."""
    frases = re.split(r"(?<=[.!?])\s+", texto.strip())
    trechos, atual = [], ""
    for f in frases:
        if atual and len(atual) + len(f) > TAMANHO_TRECHO:
            trechos.append(atual)
            atual = f
        else:
            atual = f"{atual} {f}".strip()
    if atual:
        trechos.append(atual)
    return trechos


def processar(docs):
    dados = indice.carregar()
    itens = [{"texto": i["texto"], "origem": i["origem"], "hash": i["hash"]}
             for i in dados["itens"]]
    vistos = {i["hash"] for i in itens}

    novos = 0
    for d in docs:
        for t in quebrar_em_trechos(d["texto"]):
            h = hashlib.sha1(t.encode("utf-8")).hexdigest()
            if h in vistos:
                continue  # trecho repetido, ignora
            vistos.add(h)
            itens.append({"texto": t, "origem": d.get("origem", "desconhecida"), "hash": h})
            novos += 1

    if novos == 0:
        return 0, len(itens)

    # TF-IDF depende do vocabulario todo, entao reajusta e revetoriza tudo
    vet = Vetorizador()
    vet.ajustar([i["texto"] for i in itens])
    for i in itens:
        i["vetor"] = vet.vetorizar(i["texto"])

    indice.salvar({"versao": dados["versao"] + 1, "itens": itens})
    return novos, len(itens)


def tratar(r, msg):
    tid = msg["id"]
    fila.atualizar_status(r, tid, status="processando")
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            inicio = time.time()
            novos, total = processar(msg["docs"])
            fila.atualizar_status(r, tid, status="concluida", trechos_novos=novos,
                                  total_indice=total)
            log.info("tarefa %s ok: %d trechos novos, indice com %d (%.0f ms)",
                     tid, novos, total, (time.time() - inicio) * 1000)
            return
        except Exception as e:
            log.warning("tarefa %s falhou (tentativa %d/%d): %s", tid, tentativa, TENTATIVAS, e)
            time.sleep(tentativa)
    # nao deu, manda pra dead-letter
    r.rpush(fila.FILA_MORTA, json.dumps(msg))
    fila.atualizar_status(r, tid, status="falhou")
    log.error("tarefa %s foi pra fila morta", tid)


def main():
    log.info("worker iniciado, esperando mensagens em '%s'", fila.FILA_INGESTAO)
    r = fila.conectar()
    while True:
        try:
            msg = fila.consumir(r)
        except redis.RedisError as e:
            log.error("sem conexao com o redis (%s), tentando de novo em 3s", e)
            time.sleep(3)
            continue
        if msg:
            tratar(r, msg)


if __name__ == "__main__":
    main()
