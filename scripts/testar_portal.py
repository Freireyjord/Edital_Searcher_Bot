"""
Testa um portal (scraper) SEM gravar nada no banco. Use ANTES de mergear ou rodar um scraper novo.

    python scripts/testar_portal.py bndes                    # dry-run: coleta as URLs, não grava nada
    python scripts/testar_portal.py bndes --max 15 --amostra 3
    python scripts/testar_portal.py --contrato               # só confere o contrato de TODOS os portais (sem rede)

O dry-run troca a gravação por um stub e bloqueia insert/update/delete/rpc no Supabase (só leitura).
Mostra: URLs coletadas (e quantas já existem no banco), duplicatas, e a qualidade do texto de uma amostra
(tamanho, tela de erro, PDFs anexos). O --max limita só a etapa de despacho: a coleta/paginação roda inteira.
"""
import argparse
import importlib
import inspect
import os
import pkgutil
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)


class LimiteAtingido(Exception):
    pass


class _TabelaSomenteLeitura:
    def __init__(self, tabela):
        self._t = tabela

    def __getattr__(self, nome):
        if nome in ("insert", "update", "upsert", "delete"):
            raise RuntimeError(f"[dry-run] gravação bloqueada: .{nome}()")
        return getattr(self._t, nome)


class SomenteLeitura:
    """Proxy do cliente Supabase que só deixa LER."""
    def __init__(self, cliente):
        self._c = cliente

    def table(self, nome):
        return _TabelaSomenteLeitura(self._c.table(nome))

    def __getattr__(self, nome):
        if nome == "rpc":
            raise RuntimeError("[dry-run] rpc bloqueado")
        return getattr(self._c, nome)


def contrato(modulo):
    """Lista de (nivel, mensagem); nivel: 'ok' | 'aviso' | 'erro'."""
    r = []
    nome = getattr(modulo, "NOME_PORTAL", None)
    if not isinstance(nome, str) or not nome.strip():
        r.append(("erro", "falta NOME_PORTAL (texto). É o nome gravado no banco e usado no filtro da UI."))
    else:
        r.append(("ok", f"NOME_PORTAL = {nome!r}"))
        if " - " not in nome:
            r.append(("aviso", "convenção 'Nome - Descrição' (ex.: 'BNDES - Chamadas'): o filtro da UI usa o texto antes do ' - '."))
    varrer = getattr(modulo, "varrer", None)
    if not callable(varrer):
        r.append(("erro", "falta a função varrer(log, atualizar_tabela_func=None)."))
    elif len(inspect.signature(varrer).parameters) < 1:
        r.append(("erro", "varrer() precisa receber ao menos o parâmetro 'log'."))
    else:
        r.append(("ok", "varrer(log, ...) presente"))
    r.append(("ok" if callable(getattr(modulo, "recuperar", None)) else "aviso",
              "recuperar(page, url) presente" if callable(getattr(modulo, "recuperar", None))
              else "sem recuperar(): o retrabalho usa o extrator genérico (ok para páginas simples; SPAs precisam de um próprio)."))
    return r


def dry_run(modulo, scraper_utils, max_chamadas, log):
    """Executa varrer() com a gravação trocada por um stub. Retorna (chamadas, erro)."""
    chamadas = []

    def stub(url, ignorar_links, nome_portal, log_, atualizar_tabela_func=None, texto_pre_extraido="", links_extra=None):
        chamadas.append({"url": url, "portal": nome_portal,
                         "texto_pre": len(texto_pre_extraido or ""), "links": len(links_extra or [])})
        if len(chamadas) >= max_chamadas:
            raise LimiteAtingido()
        return True

    alvos = [(scraper_utils, scraper_utils.processar_pagina_interna)]
    scraper_utils.processar_pagina_interna = stub
    if hasattr(modulo, "processar_pagina_interna"):        # portal que importou a função direto
        alvos.append((modulo, modulo.processar_pagina_interna))
        modulo.processar_pagina_interna = stub

    erro = None
    try:
        modulo.varrer(log, None)
    except LimiteAtingido:
        pass
    except Exception as e:
        erro = e
    finally:
        for obj, original in alvos:
            obj.processar_pagina_interna = original
    return chamadas, erro


def avaliar_amostra(chamadas, scraper_utils, canonicalizar, parece_erro, candidatos_pdf, n, log):
    """Baixa o texto de n URLs (ou usa o texto já renderizado do portal) e mede a qualidade."""
    linhas = []
    for c in chamadas[:n]:
        url = canonicalizar(c["url"])
        if c["texto_pre"]:
            linhas.append(f"  {url}\n      texto renderizado pelo portal: {c['texto_pre']} chars | links coletados: {c['links']}")
            continue
        tipo, conteudo = scraper_utils.baixar_pagina(url, log)
        if tipo == "html":
            texto, pares = scraper_utils.analisar_html(conteudo, url)
            pdfs = len(candidatos_pdf(pares, url))
            alerta = "  ⚠️ PARECE TELA DE ERRO" if parece_erro(texto) else ("  ⚠️ POUCO TEXTO" if len(texto) < 300 else "")
            linhas.append(f"  {url}\n      HTML: {len(texto)} chars | PDFs candidatos: {pdfs}{alerta}")
        elif tipo == "pdf":
            linhas.append(f"  {url}\n      PDF direto")
        else:
            linhas.append(f"  {url}\n      ⚠️ não foi possível baixar")
    return linhas


def checar_contratos_de_todos(log=print):
    import portais
    problemas, nomes = 0, {}
    for info in sorted(pkgutil.iter_modules(portais.__path__), key=lambda i: i.name):
        try:
            modulo = importlib.import_module(f"portais.{info.name}")
        except Exception as e:
            log(f"✗ portais/{info.name}.py: erro ao importar: {e}")
            problemas += 1
            continue
        log(f"\nportais/{info.name}.py")
        for nivel, msg in contrato(modulo):
            log(f"  {'✓' if nivel == 'ok' else ('⚠️' if nivel == 'aviso' else '✗')} {msg}")
            problemas += nivel == "erro"
        nomes.setdefault(getattr(modulo, "NOME_PORTAL", None), []).append(info.name)
    duplicados = {n: m for n, m in nomes.items() if n and len(m) > 1}
    for n, m in duplicados.items():
        log(f"\n✗ NOME_PORTAL repetido {n!r}: {', '.join(m)}")
        problemas += 1
    return problemas


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("portal", nargs="?", help="nome do arquivo em portais/ (sem .py)")
    ap.add_argument("--max", type=int, default=15, help="máximo de URLs despachadas no teste (padrão 15)")
    ap.add_argument("--amostra", type=int, default=2, help="URLs cujo texto será baixado para avaliar (padrão 2)")
    ap.add_argument("--contrato", action="store_true", help="só confere o contrato de todos os portais")
    args = ap.parse_args(argv)

    if args.contrato:
        return 1 if checar_contratos_de_todos() else 0
    if not args.portal:
        ap.error("informe o portal (ex.: bndes) ou use --contrato")

    import config
    from utils import scraper_utils
    from utils.pdf_links import coletar_candidatos
    from utils.texto_utils import texto_parece_pagina_erro
    from utils.url_utils import canonicalizar_url

    modulo = importlib.import_module(f"portais.{args.portal}")
    print(f"=== Contrato de portais/{args.portal}.py")
    erros = 0
    for nivel, msg in contrato(modulo):
        print(f"  {'✓' if nivel == 'ok' else ('⚠️' if nivel == 'aviso' else '✗')} {msg}")
        erros += nivel == "erro"
    if erros:
        return 1

    config.supabase = SomenteLeitura(config.supabase)
    print(f"\n=== Dry-run (nada será gravado; máx. {args.max} URLs despachadas)")
    chamadas, erro = dry_run(modulo, scraper_utils, args.max, print)

    unicas = {canonicalizar_url(c["url"]) for c in chamadas}
    ja_existem = 0
    for url in unicas:
        try:
            ja_existem += bool(config.supabase.table("editais").select("url").eq("url", url).execute().data)
        except Exception:
            pass
    print(f"\n=== Resultado")
    print(f"  URLs despachadas: {len(chamadas)} | únicas (sem #fragmento): {len(unicas)} | já existem no banco: {ja_existem}")
    nomes = {c["portal"] for c in chamadas}
    if nomes and nomes != {modulo.NOME_PORTAL}:
        print(f"  ⚠️ o portal passa nome diferente de NOME_PORTAL ao despachar: {nomes}")
    if erro:
        print(f"  ✗ varrer() terminou com erro: {type(erro).__name__}: {erro}")
    if not chamadas:
        print("  ✗ nenhuma URL foi despachada: o scraper não encontrou editais (seletor quebrado?)")
        return 1
    print("\n=== Amostra de conteúdo")
    for linha in avaliar_amostra(chamadas, scraper_utils, canonicalizar_url, texto_parece_pagina_erro,
                                 coletar_candidatos, args.amostra, print):
        print(linha)
    return 1 if erro else 0


if __name__ == "__main__":
    sys.exit(main())