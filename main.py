import time, sys, os, traceback, importlib
from datetime import datetime

# Vincula as pastas locais ao caminho global de importação
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.db_cleaner import limpar_editais_expirados_no_banco
from core.ai_engine import consumir_fila_pendente_ia, executar_retrabalho_editais_com_erro
from core.reporter import iniciar_agendador_relatorio

def log_worker(mensagem):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {mensagem}")
    sys.stdout.flush()

def executar_ciclo_varredura():
    log_worker("=== INICIANDO VARREDURA AUTOMATIZADA ===")
    
    # 1. Limpeza
    limpar_editais_expirados_no_banco(log_worker)
    
    # 2. Execução dos Portais (Scrapers dinâmicos)
    DIRETORIO_PORTAIS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portais")
    arquivos_portais = [f[:-3] for f in os.listdir(DIRETORIO_PORTAIS) if f.endswith(".py") and f != "__init__.py"]

    for modulo_nome in arquivos_portais:
        try:
            portal_ativo = importlib.import_module(f"portais.{modulo_nome}")
            importlib.reload(portal_ativo) 
            if hasattr(portal_ativo, "varrer"):
                portal_ativo.varrer(log_worker, None)
        except Exception as err:
            log_worker(f"[X] Erro no motor '{modulo_nome}': {err}")

    # 3. Processamento Core (IA, Retrabalho, Relatórios)
    status_ia = consumir_fila_pendente_ia(log_worker, None)
    log_worker(f"Esteira IA finalizada com status: {status_ia}")
    
    executar_retrabalho_editais_com_erro(log_worker)
    # O relatório semanal NÃO roda mais aqui: tem agendador próprio (core/reporter.py).
    log_worker("=== CICLO DE TRABALHO CONCLUÍDO ===")

if __name__ == "__main__":
    INTERVALO_SEGUNDOS = 7200 
    log_worker("=== SERVIÇO BACKGROUND INICIALIZADO ===")

    # Agendador do relatório semanal: thread própria, confere a agenda a cada 30 s.
    # Um ciclo de scraping/IA demorado não atrasa nem pula o envio de segunda 07:00.
    thread_relatorio, parar_relatorio = iniciar_agendador_relatorio(log_worker)

    while True:
        try: executar_ciclo_varredura()
        except KeyboardInterrupt:
            parar_relatorio.set()
            break
        except Exception as e: traceback.print_exc()
        time.sleep(INTERVALO_SEGUNDOS)