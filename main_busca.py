"""Worker de BUSCA: percorre os portais e grava os editais novos (status PENDENTE). Rode junto com main_ia.py."""
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.instancia_unica import garantir_instancia_unica
from core.workers import criar_logger, loop_busca

if __name__ == "__main__":
    log = criar_logger("BUSCA")
    garantir_instancia_unica("busca", log)
    log("=== WORKER DE BUSCA INICIALIZADO ===")
    try:
        loop_busca(log)
    except KeyboardInterrupt:
        log("Encerrado pelo usuário.")