"""
Worker de IA: analisa os editais PENDENTES assim que aparecem e roda o agendador do relatório semanal.
Rode junto com main_busca.py. O agendador do relatório vive AQUI (precisa existir em um único processo).
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.instancia_unica import garantir_instancia_unica
from core.workers import criar_logger, loop_ia
from core.reporter import iniciar_agendador_relatorio

if __name__ == "__main__":
    log = criar_logger("IA")
    garantir_instancia_unica("ia", log)
    log("=== WORKER DE IA INICIALIZADO ===")

    # Relatório semanal (segunda 07:00): thread própria, independente da fila da IA.
    thread_relatorio, parar_relatorio = iniciar_agendador_relatorio(log)
    try:
        loop_ia(log)
    except KeyboardInterrupt:
        parar_relatorio.set()
        log("Encerrado pelo usuário.")