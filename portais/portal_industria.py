import time
import random
import re
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

# Importa o utilitário padrão do sistema responsável por gerenciar duplicados e salvar no Supabase
from utils import scraper_utils as web_utils

# ---------------------------------------------------------------------------
# CONFIGURAÇÕES DO PORTAL
# ---------------------------------------------------------------------------
# Nome exato que será mapeado na coluna 'portal' do banco e nas chaves do dicionário de recovery
NOME_PORTAL = "Plataforma Inovação para a Indústria"
URL_ALVO_PRINCIPAL = "https://www.portaldaindustria.com.br/canais/plataforma-inovacao-para-industria/#categorias"
URL_BASE = "https://portaldaindustria.com.br"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


# ---------------------------------------------------------------------------
# 1. MOTOR DE RECOVERY (Obrigatório para o core.ai_engine)
# ---------------------------------------------------------------------------
def recuperar(page, url):
    """
    Invocado pelo robô de retrabalho (ai_engine.py) caso a primeira tentativa 
    de extração de texto de um link dê erro. Força o carregamento via navegador real.
    """
    try:
        # Usa wait_until="commit" para acelerar a extração em servidores instáveis
        page.goto(url, wait_until="commit", timeout=35000)
        time.sleep(2.0)
        return page.evaluate("() => document.body.innerText")
    except Exception:
        return page.evaluate("() => document.body.innerText")


# ---------------------------------------------------------------------------
# 2. ORQUESTRADOR CENTRAL DO PORTAL (Invocado pelo main.py)
# ---------------------------------------------------------------------------
def varrer(log, atualizar_tabela_func=None):
    """
    Ponto de entrada obrigatório executado automaticamente pelo ciclo global de background.
    """
    log(f"\n===> [INÍCIO REAL] Iniciando varredura automatizada: {NOME_PORTAL}")
    log(f"    [DEEP SCAN BLINDADO] Mapeando diretórios de categorias e isolando abas ativas...")
    
    inicio_triagem = time.time()
    pastas_categorias = set()
    editais_finais_encontrados = set()
    
    with sync_playwright() as p:
        # Inicializa o navegador Headless aplicando o padrão estável de execução do robô
        browser = p.chromium.launch(headless=True, args=["--headless=shell"])
        context = browser.new_context(user_agent=USER_AGENT, locale="pt-BR")
        page = context.new_page()
        
        # -------------------------------------------------------------------
        # NÍVEL 1: Descobrir as Pastas de Categorias
        # -------------------------------------------------------------------
        try:
            # wait_until="commit" garante a descida do HTML estático antes dos trackers de terceiros
            page.goto(URL_ALVO_PRINCIPAL, timeout=60000, wait_until="commit")
            time.sleep(3.0)
            
            links_pastas = page.evaluate("""
                () => Array.from(document.querySelectorAll('.card-pequeno, .item')).map(el => el.getAttribute('href'))
            """)
            
            for href in links_pastas:
                if href and "/categoria/" in href:
                    url_completa = urljoin(URL_BASE, href.strip())
                    if "#resultados" not in url_completa:
                        pastas_categorias.add(url_completa)
                        
            log(f"    [Nível 1] Sucesso! Mapeadas {len(pastas_categorias)} pastas de categorias para exploração.")
            
        except Exception as e_level1:
            log(f"    [❌ ERRO CRÍTICO NÍVEL 1] Falha de contato inicial com a Home do portal: {e_level1}")
            browser.close()
            return

        # -------------------------------------------------------------------
        # NÍVEL 2: Varredura Dinâmica e Resiliente de Links Abertos
        # -------------------------------------------------------------------
        for idx, pasta_url in enumerate(sorted(pastas_categorias), start=1):
            sucesso_pasta = False
            urls_pasta_atual = set()
            
            # Executa até 3 tentativas automáticas por pasta em caso de congestionamento do servidor
            for tentativa in range(1, 4):
                try:
                    page.goto(pasta_url, timeout=45000, wait_until="commit")
                    time.sleep(4.0) # Delay técnico estável para o Bootstrap processar as abas
                    
                    # Conclui a busca estritamente dentro do container de chamadas abertas
                    urls_chamadas_abertas = page.evaluate("""
                        () => {
                            const containerAberta = document.getElementById('chamadas-aberta');
                            if (!containerAberta) return [];
                            const links = Array.from(containerAberta.querySelectorAll('.card-chamada a[href], a.btn[href]'));
                            return links.map(a => a.getAttribute('href'));
                        }
                    """)
                    
                    for href in urls_chamadas_abertas:
                        if href:
                            url_completa_interna = urljoin(URL_BASE, href.strip())
                            if url_completa_interna.rstrip("/") != URL_BASE:
                                urls_pasta_atual.add(url_completa_interna)
                                
                    sucesso_pasta = True
                    break # Se deu certo, sai do loop de retries da pasta atual
                except Exception:
                    time.sleep(2.5) # Respiro rápido antes do próximo retry
                    
            if not sucesso_pasta:
                log(f"    [⚠️ Pasta Ignorada por Timeout] Salva para o próximo ciclo de 2h: {pasta_url}")
                continue

            for url_filtrada in urls_pasta_atual:
                editais_finais_encontrados.add(url_filtrada)

        context.close()
        browser.close()

    log(f"    [✓] Triagem profunda finalizada em {time.time() - inicio_triagem:.2f}s.")
    log(f"    [Esteira Supabase] Enviando {len(editais_finais_encontrados)} oportunidades ativas detectadas para o banco...")

    if not editais_finais_encontrados:
        log("    [✨] Varredura limpa: nenhuma oportunidade ativa em aberto nas pastas.")
        return

    # -----------------------------------------------------------------------
    # 3. PIPELINE DE REGISTRO E CONTROLE DE DUPLICIDADES NO SUPABASE
    # -----------------------------------------------------------------------
    for idx_edital, url_edital in enumerate(sorted(editais_finais_encontrados), start=1):
        log(f"        [Fila {idx_edital}/{len(editais_finais_encontrados)}] Processando link alvo: {url_edital}")
        
        # Despacha o link para o módulo core do sistema.
        # Ele verifica se a URL já existe no Supabase. Se for nova, lê o texto bruto 
        # (seja página HTML ou arquivo .pdf), injeta em 'texto_extracao' 
        # e joga o status para 'PENDENTE' liberando para a IA local do Ollama ler.
        web_utils.processar_pagina_interna(
            url_edital=url_edital,
            ignorar_links=[],
            nome_portal=NOME_PORTAL,
            log=log,
            atualizar_tabela_func=None
        )
        
        # Delay regulamentar (Politeness Policy) para evitar bloqueios de IP / Firewall
        time.sleep(random.uniform(1.5, 3.0))

    log(f"[✓] O motor integrado da '{NOME_PORTAL}' finalizou suas operações com sucesso!")
