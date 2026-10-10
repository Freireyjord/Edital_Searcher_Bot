import time
import random
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

from utils import scraper_utils as web_utils

NOME_PORTAL = "Petrobras - Sigitec"
URL_REAL_PETROBRAS = "https://sigitec-competitividade.petrobras.com.br/v2/public/opportunities"
URL_BASE = "https://sigitec-competitividade.petrobras.com.br"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Regex de texto (Playwright): qualquer um dos termos indica que o React renderizou o conteúdo
SELETOR_CONTEUDO = "text=/Desafio|Objetivo|Prazo/"

JS_PAGINA_ATIVA = """
() => {
    const ativo = document.querySelector("ul.pagination li.active, [class*='pagination'] span.active, .active");
    return ativo ? ativo.textContent.trim() : null;
}
"""


def recuperar(page, url):
    """Usada pelo retrabalho (core.ai_engine) para re-extrair o texto de um edital."""
    page.goto(url, wait_until="networkidle", timeout=45000)
    try:
        page.wait_for_selector(SELETOR_CONTEUDO, timeout=10000)
    except Exception:
        time.sleep(3.0)
    return page.evaluate("() => document.body.innerText")


def _criar_contexto(browser):
    return browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1366, "height": 768},
        locale="pt-BR"
    )


def _coletar_urls(log):
    urls_validas = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--headless=shell"])
        context = _criar_contexto(browser)
        page = context.new_page()

        try:
            log("    [Navegação] Solicitando interface ao servidor da Petrobras...")
            page.goto(URL_REAL_PETROBRAS, timeout=60000, wait_until="networkidle")

            # Remove loader/backdrops do React
            page.evaluate("""() => {
                const loader = document.getElementById('loader');
                if (loader) loader.remove();
                const backdrops = document.querySelectorAll('.modal-backdrop, .sc-biOXLh');
                backdrops.forEach(b => b.remove());
                document.body.style.overflow = 'initial';
            }""")

            time.sleep(5.0)

            pagina_atual = 1
            while True:
                log(f"    [Análise de DOM] Executando varredura interna na página {pagina_atual}...")

                dados_pagina = page.evaluate("""
                    () => {
                        const resultados = [];
                        const links = document.querySelectorAll("a[href*='opportunity'], a[href*='opportunities'], a[href*='submit']");

                        links.forEach(el => {
                            const href = el.getAttribute("href");
                            if (!href || href === "#" || href === "/public/opportunities" || href === "/v2/public/opportunities") return;

                            const titulo = el.textContent.trim().replace(/\\n/g, " ");
                            const container = el.closest('.sc-gTgAbX') || el.closest('.row') || el.parentElement;
                            let prazo = "Não Localizado";

                            if (container) {
                                const elDeadline = container.querySelector('.card-deadline') || container.querySelector('[class*="deadline"]');
                                if (elDeadline) prazo = elDeadline.textContent.trim();
                            }

                            resultados.push({ href: href, titulo: titulo, prazo: prazo });
                        });
                        return resultados;
                    }
                """)

                novos = 0
                for item in dados_pagina:
                    url_completa = urljoin(URL_BASE, item["href"])
                    if url_completa not in urls_validas:
                        urls_validas.add(url_completa)
                        novos += 1

                log(f"        [+] Sucesso: {novos} novos editais catalogados na página {pagina_atual}.")

                pagina_ativa_antes = page.evaluate(JS_PAGINA_ATIVA)

                clicou = page.evaluate("""
                    () => {
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

                if not clicou:
                    log("        [✓] Botão 'próximo' não localizado ou desabilitado. Fim do catálogo alcançado.")
                    break

                mudou_pagina = False
                for _ in range(30):
                    time.sleep(0.3)
                    if page.evaluate(JS_PAGINA_ATIVA) != pagina_ativa_antes:
                        mudou_pagina = True
                        break

                if mudou_pagina:
                    pagina_atual += 1
                    time.sleep(1.5)
                else:
                    log("        [Paginação] A página não alterou o estado interno. Encerrando catálogo por segurança.")
                    break

        except Exception as e:
            log(f"        [❌ ERRO NO MOTOR] Falha crítica de leitura na interface do Sigitec: {e}")
        finally:
            try:
                browser.close()
            except Exception:
                pass

    return urls_validas


def varrer(log, atualizar_tabela_func=None):
    log("\n===> [INÍCIO REAL] Sincronizando com o ecossistema React do Sigitec Petrobras")
    log(f"    [ALVO] Navegando para: {URL_REAL_PETROBRAS}")

    inicio_triagem = time.time()
    urls_validas = _coletar_urls(log)
    log(f"    [✓] Triagem concluída em {time.time() - inicio_triagem:.2f}s. Total: {len(urls_validas)}")

    if not urls_validas:
        log("    [⚠️ ALERTA] Nenhuma oportunidade legítima capturada no barramento dinâmico.")
        return

    # --- FILA DE HIDRATAÇÃO COM ROTAÇÃO DE CONTEXTO ANTIBLOQUEIO ---
    with sync_playwright() as p_interna:
        browser_int = p_interna.chromium.launch(headless=True, args=["--headless=shell"])
        context_int = _criar_contexto(browser_int)
        page_int = context_int.new_page()

        for idx, url_edital in enumerate(sorted(urls_validas), start=1):
            if idx % 50 == 0:
                log("        [🔄 Reciclagem] Renovando sessão do navegador para evitar bloqueio...")
                try:
                    page_int.close()
                    context_int.close()
                except Exception:
                    pass
                context_int = _criar_contexto(browser_int)
                page_int = context_int.new_page()   # CORREÇÃO: antes era page_int.new_page()
                time.sleep(3.0)

            log(f"        [Fila {idx}/{len(urls_validas)}] Extraindo conteúdo via SPA v2: {url_edital}")
            texto_renderizado = ""

            try:
                page_int.goto(url_edital, timeout=35000, wait_until="networkidle")

                try:
                    # CORREÇÃO: vírgula não funciona como "OU" em text=; usa-se regex
                    page_int.wait_for_selector(SELETOR_CONTEUDO, timeout=15000)
                except Exception:
                    time.sleep(3.0)

                texto_renderizado = page_int.evaluate("() => document.body.innerText")

            except Exception as e:
                log(f"        [⚠️ Alerta] Falha de renderização assíncrona na página interna: {e}")

            web_utils.processar_pagina_interna(
                url_edital, [], NOME_PORTAL, log, None, texto_pre_extraido=texto_renderizado
            )

            time.sleep(random.uniform(1.0, 2.0))

        try:
            context_int.close()
            browser_int.close()
        except Exception:
            pass

    log(f"[✓] O motor da {NOME_PORTAL} finalizou com sucesso!")