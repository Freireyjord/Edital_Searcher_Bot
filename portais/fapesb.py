import time
import random
import re
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

# Importa o utilitário oficial do seu sistema para gravação e controle de duplicados no Supabase
from utils import scraper_utils as web_utils

# ---------------------------------------------------------------------------
# CONFIGURAÇÕES DO PORTAL
# ---------------------------------------------------------------------------
NOME_PORTAL = "FAPESB"
URL_ALVO_PRINCIPAL = "https://www.fapesb.ba.gov.br/category/edital/"
URL_BASE = "https://fapesb.ba.gov.br"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


# ---------------------------------------------------------------------------
# 1. MOTOR DE RECOVERY (Obrigatório para o core.ai_engine)
# ---------------------------------------------------------------------------
def recuperar(page, url):
    """
    Invocado pelo ai_engine.py caso o texto de algum edital precise 
    ser re-extraído de forma assíncrona usando um navegador real.
    """
    try:
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
    Ponto de entrada padrão que o main.py executa a cada ciclo de 2 horas.
    """
    log(f"\n===> [INÍCIO REAL] Sincronizando com o portal: {NOME_PORTAL}")
    log(f"    [POST FORM] Rastreando todos os anos e isolando editais abertos...")
    
    inicio_triagem = time.time()
    editais_finais_encontrados = set()
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--headless=shell"])
        context = browser.new_context(user_agent=USER_AGENT, locale="pt-BR")
        page = context.new_page()
        
        # 1. Mapeia todos os anos disponíveis na barra de rolagem do site
        try:
            page.goto(URL_ALVO_PRINCIPAL, timeout=45000, wait_until="domcontentloaded")
            time.sleep(2.0)
            
            anos_disponiveis = page.evaluate("""
                () => Array.from(document.querySelectorAll('.filtro li button')).map(btn => btn.value)
            """)
            anos_para_buscar = sorted([ano for ano in anos_disponiveis if ano.isdigit()], reverse=True)
            log(f"    [Nível 1] Sucesso! Identificados {len(anos_para_buscar)} anos para processamento.")
        except Exception as e_init:
            log(f"    [❌ ERRO CRÍTICO] Não foi possível ler os anos na Home da FAPESB: {e_init}")
            browser.close()
            return

        # 2. Loop de submissão estável de formulários por ano
        for ano in anos_para_buscar:
            try:
                page.goto(URL_ALVO_PRINCIPAL, timeout=45000, wait_until="domcontentloaded")
                time.sleep(1.5)
                
                # Executa o POST nativo e aguarda com segurança a atualização da página
                with page.expect_navigation(wait_until="domcontentloaded", timeout=45000):
                    page.evaluate(f"""
                        () => {{
                            const inputAno = document.getElementById('ano_filtro');
                            const form = document.getElementById('form_filtro');
                            if (inputAno && form) {{
                                inputAno.value = '{ano}';
                                form.submit();
                            }}
                        }}
                    """)
                
                time.sleep(3.0) # Tempo para o WordPress estruturar o grid
                
                # Coleta os links estritamente da aba de Abertos (#tab1)
                links_abertos = page.evaluate("""
                    () => {
                        const containerAbertos = document.getElementById('tab1');
                        if (!containerAbertos) return [];
                        const anchors = Array.from(containerAbertos.querySelectorAll('.edital-item .edital-title h3 a[href]'));
                        return anchors.map(a => a.getAttribute('href'));
                    }
                """)
                
                for href in links_abertos:
                    if href:
                        editais_finais_encontrados.add(urljoin(URL_BASE, href.strip()))
                        
            except Exception as e_ano:
                log(f"    [⚠️ Ano Pulado] Falha ao processar o formulário do ano {ano}: {e_ano}")
                continue

        context.close()
        browser.close()

    log(f"    [✓] Triagem concluída em {time.time() - inicio_triagem:.2f}s.")
    log(f"    [Pipeline] Enviando {len(editais_finais_encontrados)} links ativos para a esteira do Supabase...")

    if not editais_finais_encontrados:
        return

    # -----------------------------------------------------------------------
    # 3. FILA DE ENVIOS E EXTRAÇÃO DE CONTEÚDO COMPOSTO (HTML + PDFs + Imagens)
    # -----------------------------------------------------------------------
    for idx, url_edital in enumerate(sorted(editais_finais_encontrados), start=1):
        log(f"        [Fila {idx}/{len(editais_finais_encontrados)}] Processando: {url_edital}")
        
        # web_utils vai abrir o edital, coletar o HTML, mapear os anexos,
        # verificar duplicados no banco e salvar com status 'PENDENTE'
        web_utils.processar_pagina_interna(
            url_edital=url_edital,
            ignorar_links=[],
            nome_portal=NOME_PORTAL,
            log=log,
            atualizar_tabela_func=None
        )
        
        # Delay de cortesia antibloqueio
        time.sleep(random.uniform(1.5, 3.0))

    log(f"[✓] O motor integrado da '{NOME_PORTAL}' foi finalizado com sucesso!")
