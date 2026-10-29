"""
Persistencia do indice vetorial em disco (arquivo JSON).

So o worker escreve. A API so le. A escrita e atomica (grava num .tmp
e renomeia) pra API nunca ler um arquivo pela metade.
"""
import json
import os

ARQUIVO = os.getenv("INDICE_ARQUIVO", "dados/indice.json")

_cache = {"mtime": None, "dados": None}


def vazio():
    return {"versao": 0, "itens": []}


def carregar():
    if not os.path.exists(ARQUIVO):
        return vazio()
    mtime = os.path.getmtime(ARQUIVO)
    if _cache["mtime"] != mtime:
        with open(ARQUIVO, encoding="utf-8") as f:
            _cache["dados"] = json.load(f)
        _cache["mtime"] = mtime
    return _cache["dados"]


def salvar(dados):
    pasta = os.path.dirname(ARQUIVO)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    tmp = ARQUIVO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False)
    os.replace(tmp, ARQUIVO)
