import time
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

from utils import scraper_utils as web_utils

NOME_PORTAL = "Finep - Oportunidades"
URL_REAL_FINEP = "https://www.finep.gov.br/oportunidades"
URL_BASE = "https://finep.gov.br"

def varrer(log, atualizar_tabela_func=None):
    log(f"\n===> [INÍCIO REAL] Sincronizando com o ecossistema Liferay da Finep")
    log(f"    [ALVO] Navegando para: {URL_REAL_FINEP}")
    
    urls_validas = set()
    inicio_triagem = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        page = context.new_page()
        
        try:
            log("    [Navegação] Carregando a estrutura base da página...")
            page.goto(URL_REAL_FINEP, timeout=45000, wait_until="domcontentloaded")
            
            log("    [Aguardando Renderização] Aguardando o componente de chamadas públicas...")
            page.wait_for_selector("finep-busca-chamadas-publicas", timeout=20000)
            
            # Estabilização inicial para garantir o carregamento do lote 1
            time.sleep(5.0)
            
            pagina_atual = 1
            while True:
                log(f"    [Análise de DOM] Escaneando os cards visíveis na página {pagina_atual}...")
                
                # Seletores robustos para mapear links em qualquer variação de página do Liferay
                elementos_link = page.query_selector_all(".produto-card h2 a, .produto-card .link-interna a, .card h2 a, .card-body a, finep-busca-chamadas-publicas a")
                
                links_na_pagina = 0
                for el in elementos_link:
                    try:
                        href = el.get_attribute("href")
                        if not href:
                            continue
                            
                        href = href.strip()
                        if href.startswith("#") or href.startswith("javascript:"):
                            continue
                            
                        url_completa = urljoin(URL_BASE, href)
                        
                        # Filtros de segurança para ignorar links institucionais e menus fixos
                        urls_rejeitadas = [URL_REAL_FINEP.rstrip("/"), "https://finep.gov.br", "https://finep.gov.br"]
                        
                        if url_completa.rstrip("/") not in urls_rejeitadas and "/oportunidades" not in href:
                            if url_completa not in urls_validas:
                                urls_validas.add(url_completa)
                                links_na_pagina += 1
                    except Exception:
                        continue

                log(f"        [+] Sucesso: Mapeados {links_na_pagina} novos links na página {pagina_atual}.")

                # Captura o número da página ativa ANTES de forçar o avanço por JS
                pagina_ativa_antes = page.evaluate("""
                    () => {
                        const ativo = document.querySelector("ul.pagination li.active, ul.pagination li.page-item.active");
                        return ativo ? ativo.textContent.trim() : null;
                    }
                """)

                # --- PAGINAÇÃO CONTROLADA VIA JAVASCRIPT NATIVO ---
                clicou = page.evaluate("""
                    () => {
                        const liProximo = document.querySelector("ul.pagination li:not(.disabled):has(svg.lexicon-icon-angle-right)");
                        if (liProximo) {
                            const botao = liProximo.querySelector("button");
                            if (botao) {
                                botao.click();
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                
                if clicou:
                    log(f"    [Paginação] Botão avançar acionado via JS. Aguardando sincronização da página {pagina_atual + 1}...")
                    
                    # --- SINCRO POR TROCA DE ESTADO DE NÚMERO (SPA) ---
                    mudou_pagina = False
                    for tentativa in range(40):  # Aguarda até 8 segundos (40 * 0.2s)
                        time.sleep(0.2)
                        pagina_ativa_agora = page.evaluate("""
                            () => {
                                const ativo = document.querySelector("ul.pagination li.active, ul.pagination li.page-item.active");
                                return ativo ? ativo.textContent.trim() : null;
                            }
                        """)
                        if pagina_ativa_agora != pagina_ativa_antes:
                            mudou_pagina = True
                            break
                    
                    if mudou_pagina:
                        pagina_atual += 1
                        time.sleep(1.5)  # Respiro para consolidação visual do HTML renderizado
                    else:
                        log("    [⚠️ Alerta] O indicador de página não alterou. Aplicando delay fixo de contingência...")
                        pagina_atual += 1
                        time.sleep(5.0)
                else:
                    log("        [✓] Seta de avançar desabilitada no HTML (Fim do catálogo alcançado).")
                    break

        except Exception as e:
            log(f"        [⚠️ ERRO NO MOTOR] Falha durante a extração visual do HTML: {e}")
            
        finally:
            try:
                context.close()
                browser.close()
            except Exception:
                pass

    log(f"\n    [✓] Triagem concluída em {time.time() - inicio_triagem:.2f}s! Total de editais reais localizados: {len(urls_validas)}")

    if len(urls_validas) == 0:
        log("    [⚠️ CRÍTICO] Nenhuma oportunidade legítima capturada no mapeamento dinâmico.")
        return

    # Despacha a coleção de links única capturada para o processamento de IA / Supabase
    for idx, url_edital in enumerate(sorted(urls_validas), start=1):
        log(f"        [Fila {idx}/{len(urls_validas)}] Despachando edital real: {url_edital}")
        
        web_utils.processar_pagina_interna(
            url_edital, [], NOME_PORTAL, log, None
        )
        time.sleep(2.0)
        
    log(f"[✓] O motor integrado da {NOME_PORTAL} finalizou com sucesso!")
