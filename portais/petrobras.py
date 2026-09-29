import time
import sys
import os
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

# Garante que o Python localize o módulo web_utils na pasta raiz do projeto
PASTA_RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PASTA_RAIZ not in sys.path:
    sys.path.append(PASTA_RAIZ)

from utils import scraper_utils as web_utils

NOME_PORTAL = "Petrobras - Sigitec"
URL_REAL_PETROBRAS = "https://sigitec-competitividade.petrobras.com.br/v2/public/opportunities"
URL_BASE = "https://sigitec-competitividade.petrobras.com.br"

def varrer(log, atualizar_tabela_func=None):
    log(f"\n===> [INÍCIO REAL] Sincronizando com o ecossistema React do Sigitec Petrobras")
    log(f"    [ALVO] Navegando para: {URL_REAL_PETROBRAS}")
    
    urls_validas = set()
    inicio_triagem = time.time()

    with sync_playwright() as p:
        # Lança o navegador Chromium usando a camada enxuta de shell para emulação desktop perfeita
        browser = p.chromium.launch(headless=True, args=["--headless=shell"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            locale="pt-BR"
        )
        page = context.new_page()
        
        try:
            log("    [Navegação] Solicitando interface ao servidor da Petrobras...")
            page.goto(URL_REAL_PETROBRAS, timeout=60000, wait_until="networkidle")
            
            # Limpeza do loader do React via injeção JavaScript imediata
            page.evaluate("""() => {
                const loader = document.getElementById('loader');
                if (loader) loader.remove();
                const backdrops = document.querySelectorAll('.modal-backdrop, .sc-biOXLh');
                backdrops.forEach(b => b.remove());
                document.body.style.overflow = 'initial';
            }""")
            
            # Tempo de respiro para consolidação inicial do barramento
            time.sleep(5.0)
            
            pagina_atual = 1
            pagina_atual = 1
            while True:
                log(f"    [Análise de DOM] Executando varredura interna na página {pagina_atual}...")
                
                # Executa o mapeamento molecular por dentro da árvore de memória do próprio navegador
                dados_pagina = page.evaluate("""
                    () => {
                        const resultados = [];
                        
                        // Captura links de submissão direta ou detalhes que contenham o identificador padrão do portal v2
                        const links = document.querySelectorAll("a[href*='opportunity'], a[href*='opportunities'], a[href*='submit']");
                        
                        links.forEach(el => {
                            const href = el.getAttribute("href");
                            
                            // IGNORA apenas o link genérico que volta para a listagem principal vazia
                            if (!href || href === "#" || href === "/public/opportunities" || href === "/v2/public/opportunities") return;
                            
                            const titulo = el.textContent.trim().replace(/\\n/g, " ");
                            
                            // Localiza o container do card para capturar o prazo se disponível
                            const container = el.closest('.sc-gTgAbX') || el.closest('.row') || el.parentElement;
                            let prazo = "Não Localizado";
                            
                            if (container) {
                                const elDeadline = container.querySelector('.card-deadline') || container.querySelector('[class*="deadline"]');
                                if (elDeadline) {
                                    prazo = elDeadline.textContent.trim();
                                }
                            }
                            
                            resultados.push({
                                href: href,
                                titulo: titulo,
                                prazo: prazo
                            });
                        });
                        return resultados;
                    }
                """)

                
                links_na_pagina = 0
                for item in dados_pagina:
                    url_completa = urljoin(URL_BASE, item["href"])
                    if url_completa not in urls_validas:
                        urls_validas.add(url_completa)
                        links_na_pagina += 1
                
                log(f"        [+] Sucesso: {links_na_pagina} novos editais catalogados na página {pagina_atual}.")

                # --- NOVO COMANDO DE AVANÇO DE PÁGINA (SELETOR SEMÂNTICO GLOBAL) ---
                # Captura o texto ou estado do botão ativo antes de clicar
                pagina_ativa_antes = page.evaluate("""
                    () => {
                        // Busca o span ativo dentro de estruturas de paginação comum ou nav/ul
                        const ativo = document.querySelector("ul.pagination li.active, [class*='pagination'] span.active, .active");
                        return ativo ? ativo.textContent.trim() : null;
                    }
                """)

                clicou = page.evaluate("""
                    () => {
                        // Busca por botões que contenham o texto 'próximo', '>' ou setas direcionais de paginação
                        const botoes = Array.from(document.querySelectorAll("button, li a, span"));
                        const btnProximo = botoes.find(b => {
                            const texto = b.textContent.toLowerCase();
                            return (texto.includes('próximo') || texto === '>') && !b.disabled && !b.classList.contains('disabled');
                        });
                        
                        if (btnProximo) {
                            btnProximo.scrollIntoView();
                            btnProximo.click();
                            return true;
                        }
                        return false;
                    }
                """)
                
                if clicou:
                    mudou_pagina = False
                    # Aguarda a alteração real do estado/Virtual DOM
                    for tentativa in range(30):
                        time.sleep(0.3)
                        pagina_ativa_agora = page.evaluate("""
                            () => {
                                const ativo = document.querySelector("ul.pagination li.active, [class*='pagination'] span.active, .active");
                                return ativo ? ativo.textContent.trim() : null;
                            }
                        """)
                        if pagina_ativa_agora != pagina_ativa_antes:
                            mudou_pagina = True
                            break
                    
                    if mudou_pagina:
                        pagina_atual += 1
                        time.sleep(1.5)
                    else:
                        # Se o DOM não mudar em 9 segundos, o catálogo terminou ou travou
                        log("        [Paginação] Avisando: A página não alterou o estado interno. Encerrando catálogo por segurança.")
                        break
                else:
                    log("        [✓] Botão 'próximo' não localizado ou desabilitado. Fim do catálogo alcançado.")
                    break


        except Exception as e:
            log(f"        [❌ ERRO NO MOTOR] Falha crítica de leitura na interface do Sigitec: {e}")
        finally:
            try: browser.close()
            except: pass

    # --- FILA DE HIDRATAÇÃO COM ROTAÇÃO DE CONTEXTO ANTIBLOQUEIO ---
    if len(urls_validas) == 0:
        log("    [⚠️ ALERTA] Nenhuma oportunidade legítima capturada no barramento dinâmico.")
        return

    import random # Necessário importar para o jitter dinâmico

    with sync_playwright() as p_interna:
        browser_int = p_interna.chromium.launch(headless=True, args=["--headless=shell"])
        
        def criar_novo_contexto(browser):
            return browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 768}, 
                locale="pt-BR"
            )

        context_int = criar_novo_contexto(browser_int)
        page_int = context_int.new_page()
        
        for idx, url_edital in enumerate(sorted(urls_validas), start=1):
            # 🔥 ESTRATÉGIA 1: A cada 50 editais, reinicia o contexto para limpar cache e despistar o Rate Limit
            if idx % 50 == 0:
                log(f"        [🔄 Reciclagem] Renovando sessão do navegador para evitar bloqueio por Rate Limit...")
                try:
                    page_int.close()
                    context_int.close()
                except:
                    pass
                context_int = criar_novo_contexto(browser_int)
                page_int = context_int.new_page()
                time.sleep(3.0) # Respiro para o servidor

            log(f"        [Fila {idx}/{len(urls_validas)}] Extraindo conteúdo real via SPA: {url_edital}")
            texto_renderizado = ""
            
            try:
                page_int.goto(url_edital, timeout=35000, wait_until="domcontentloaded")
                
                # 🔥 ESTRATÉGIA 2: Alvo duplo flexível para evitar travamentos caso a página mude de layout
                page_int.wait_for_selector("div.text-justify, main h4, .sc-ehSEfb", timeout=20000)
                time.sleep(1.5)
                
                # Captura todo o texto gerado dinamicamente
                texto_renderizado = page_int.evaluate("() => document.body.innerText")
            except Exception as e:
                log(f"        [⚠️ Alerta] Falha de renderização assíncrona na página interna: {e}")
            
            # Persiste os dados no web_utils sem o parâmetro da palavra-chave
            web_utils.processar_pagina_interna(
                url_edital, [], NOME_PORTAL, log, None, texto_pre_extraido=texto_renderizado
            )
            
            # 🔥 ESTRATÉGIA 3: Jitter dinâmico (tempo aleatório entre 1s e 2.5s) para quebrar o padrão mecânico
            time.sleep(random.uniform(1.0, 2.5))
            
        try: 
            context_int.close()
            browser_int.close()
        except: 
            pass
        
    log(f"[✓] O motor integrado com sincronizador interno da {NOME_PORTAL} finalizou com sucesso!")
