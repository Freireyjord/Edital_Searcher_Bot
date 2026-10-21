"""
Os dois workers do robô. Cada um roda no seu próprio processo (main_busca.py / main_ia.py)
e a comunicação é só pelo banco: a busca grava editais 'PENDENTE'; a IA os consome.
"""
import importlib
import os
import sys
import threading
import time
import traceback
from datetime import datetime

import config
from core.ai_engine import consumir_fila_pendente_ia, executar_retrabalho_editais_com_erro
from core.db_cleaner import limpar_editais_expirados_no_banco

MAX_LOTES_SEGUIDOS = 500    # trava de segurança contra loop sem fim (ex.: banco recusando gravações)


def criar_logger(prefixo):
    def log(mensagem):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{prefixo}] {mensagem}")
        sys.stdout.flush()
    return log


# ---------------------------------------------------------------------------
# Worker de BUSCA: percorre os portais e grava os editais novos como PENDENTE
# ---------------------------------------------------------------------------
def executar_ciclo_busca(log):
    log("=== INICIANDO VARREDURA DE PORTAIS ===")
    limpar_editais_expirados_no_banco(log)

    pasta_portais = os.path.join(config.DIRETORIO_PAI, "portais")
    nomes = sorted(f[:-3] for f in os.listdir(pasta_portais) if f.endswith(".py") and f != "__init__.py")

    for nome in nomes:
        try:
            modulo = importlib.import_module(f"portais.{nome}")
            importlib.reload(modulo)
            if hasattr(modulo, "varrer"):
                modulo.varrer(log, None)
        except Exception as err:
            log(f"[X] Erro no motor '{nome}': {err}")

    log("=== VARREDURA CONCLUÍDA ===")


def loop_busca(log, parar=None):
    parar = parar or threading.Event()
    while not parar.is_set():
        try:
            executar_ciclo_busca(log)
        except Exception:
            traceback.print_exc()
        log(f"Próxima varredura em {config.INTERVALO_BUSCA_SEGUNDOS // 60} min.")
        parar.wait(config.INTERVALO_BUSCA_SEGUNDOS)


# ---------------------------------------------------------------------------
# Worker de IA: consome a fila continuamente
# ---------------------------------------------------------------------------
def loop_ia(log, parar=None):
    """
    1) Fluxo contínuo: editais NOVOS (tentativas = 0) são analisados assim que aparecem no banco,
       em lotes pequenos, sem esperar o fim da varredura.
    2) Retentativas (erro_ia) e retrabalho (re-scraping) rodam espaçados: um edital que falhou
       não é repetido em sequência (ex.: timeout), e sim a cada IA_INTERVALO_RETRY_SEGUNDOS.
    3) Ollama fora do ar: espera IA_BACKOFF_OLLAMA_SEGUNDOS em vez de insistir.
    """
    parar = parar or threading.Event()
    ultimo_retry = None
    lentidao = 0                # passadas seguidas com 'ia_lenta' (backoff exponencial)

    while not parar.is_set():
        espera = config.IA_POLL_SEGUNDOS
        try:
            status = "vazio"
            for _ in range(MAX_LOTES_SEGUIDOS):
                if parar.is_set():
                    break
                status = consumir_fila_pendente_ia(log, apenas_novos=True, limite=config.IA_TAMANHO_LOTE)
                if status != "sucesso":          # 'vazio', 'erro' ou 'ollama_offline'
                    break

            if status != "ia_lenta":
                lentidao = 0

            if status == "ia_lenta":
                lentidao += 1
                espera = min(config.IA_BACKOFF_OLLAMA_SEGUNDOS * 2 ** (lentidao - 1), 3600)
                log(f"[⏸️] IA lenta demais (timeouts seguidos). Nova tentativa em {espera / 60:.0f} min "
                    f"(dobra a cada falha, até 60 min). Corrija OLLAMA_MODEL/OLLAMA_THINK.")
            elif status == "ollama_offline":
                log(f"[⏸️] Ollama indisponível. Nova tentativa em {config.IA_BACKOFF_OLLAMA_SEGUNDOS // 60} min.")
                espera = config.IA_BACKOFF_OLLAMA_SEGUNDOS
            elif status == "erro":
                espera = max(espera, 60)
            elif ultimo_retry is None or time.monotonic() - ultimo_retry >= config.IA_INTERVALO_RETRY_SEGUNDOS:
                ultimo_retry = time.monotonic()
                resultado = consumir_fila_pendente_ia(log, apenas_novos=False, limite=config.IA_TAMANHO_LOTE)
                if resultado in ("ollama_offline", "ia_lenta"):
                    espera = config.IA_BACKOFF_OLLAMA_SEGUNDOS
                else:
                    executar_retrabalho_editais_com_erro(log)
        except Exception:
            traceback.print_exc()

        parar.wait(espera)