"""
Compara modelos do Ollama nos MESMOS editais reais (os já CONCLUIDOS no banco).

Uso (na raiz do projeto):
    python scripts/comparar_modelos.py --modelos qwen2.5:14b-instruct qwen3.5:9b --think auto off --n 5 --timeout 300

Para cada combinação modelo x think roda os mesmos N editais e mostra: respostas válidas, timeouts, tempo mediano,
tokens de saída (modelos de raciocínio gastam MUITOS), e quantos acharam prazo e data de início.
Também lista os editais em que os modelos DISCORDAM no prazo (vale conferir à mão).
Demora: N x combinações x até --timeout segundos. Comece com --n 5. Não precisa parar os workers.
"""
import argparse
import csv
import os
import statistics
import sys
from datetime import datetime

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)


def executar_benchmark(amostra, combos, extrair, validar, timeout, log=print):
    """Roda cada (modelo, think) em todos os editais da amostra. Retorna lista de dicts (uma linha por chamada)."""
    linhas = []
    for modelo, think in combos:
        log(f"\n>>> {modelo}  (think={think})")
        for i, ed in enumerate(amostra, start=1):
            metricas = {}
            bruto = extrair(ed["texto_extracao"], ed["url"], ed["portal"],
                            modelo=modelo, think=think, metricas=metricas, timeout=timeout)
            linha = {"modelo": modelo, "think": think, "url": ed["url"], "ok": False, "erro": "",
                     "titulo": "", "prazo": "", "inicio": "", "tags": 0,
                     "segundos": metricas.get("total_s", 0), "tokens": metricas.get("tokens_saida", 0),
                     "tps": metricas.get("tps", 0)}
            if "erro" in bruto:
                linha["erro"] = bruto.get("tipo", "erro")
            else:
                try:
                    d = validar(bruto)
                    linha.update(
                        ok=True, titulo=d["titulo"],
                        prazo=d["prazo_submissao"].isoformat() if d["prazo_submissao"] else "",
                        inicio=d["inicio_edital"].isoformat() if d["inicio_edital"] else "",
                        tags=len([t for t in d["tags_ia"].split(",") if t.strip() and t.strip() != "Geral"]),
                    )
                except ValueError as e:
                    linha["erro"] = "titulo_invalido" if type(e).__name__ == "ConteudoInvalido" else "resposta_invalida"
            rotulo = "OK" if linha["ok"] else linha["erro"]
            log(f"  [{i}/{len(amostra)}] {linha['segundos']:6.1f}s {linha['tokens']:6d} tok  {rotulo:>17}  {linha['titulo'][:55]}")
            linhas.append(linha)
    return linhas


def resumir(linhas):
    grupos = {}
    for l in linhas:
        grupos.setdefault((l["modelo"], l["think"]), []).append(l)
    resumo = []
    for (modelo, think), ls in grupos.items():
        oks = [l for l in ls if l["ok"]]
        tempos = [l["segundos"] for l in ls if l["segundos"]]
        tokens = [l["tokens"] for l in oks if l["tokens"]]
        resumo.append({
            "modelo": modelo, "think": think, "n": len(ls), "validas": len(oks),
            "timeouts": sum(l["erro"] == "timeout" for l in ls),
            "mediana_s": round(statistics.median(tempos), 1) if tempos else 0,
            "tokens_med": int(statistics.median(tokens)) if tokens else 0,
            "com_prazo": sum(bool(l["prazo"]) for l in oks),
            "com_inicio": sum(bool(l["inicio"]) for l in oks),
        })
    return resumo


def divergencias(linhas):
    """URLs em que as combinações válidas discordam no prazo."""
    por_url = {}
    for l in linhas:
        if l["ok"]:
            por_url.setdefault(l["url"], {})[(l["modelo"], l["think"])] = l["prazo"] or "—"
    return {url: v for url, v in por_url.items() if len(set(v.values())) > 1}


def formatar_resumo(resumo):
    cab = f"{'modelo':28} {'think':5} {'válidas':>8} {'timeouts':>8} {'mediana':>8} {'tokens':>7} {'prazo':>6} {'início':>6}"
    linhas = [cab, "-" * len(cab)]
    for r in resumo:
        linhas.append(f"{r['modelo']:28} {r['think']:5} {str(r['validas']) + '/' + str(r['n']):>8} {r['timeouts']:>8} "
                      f"{r['mediana_s']:>7.1f}s {r['tokens_med']:>7} {r['com_prazo']:>6} {r['com_inicio']:>6}")
    return "\n".join(linhas)


def _carregar_amostra(supabase, n):
    dados = (supabase.table("editais")
             .select("url,portal,texto_extracao")
             .eq("status_ia", "CONCLUIDO").not_.is_("texto_extracao", "null")
             .order("created_at", desc=True).limit(n * 4).execute().data) or []
    passo = max(1, len(dados) // n)
    return dados[::passo][:n]          # espalhados, não só os mais recentes


def _aquecer(config, modelo):
    """Carrega o modelo na memória antes de medir (senão o 1º edital paga o tempo de carga)."""
    import requests
    try:
        requests.post(config.OLLAMA_URL, timeout=600, json={
            "model": modelo, "prompt": "ok", "stream": False,
            "options": {"num_predict": 1, "num_ctx": config.OLLAMA_NUM_CTX}})
    except Exception as e:
        print(f"  [aviso] não consegui aquecer {modelo}: {e}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modelos", nargs="+", help="padrão: o OLLAMA_MODEL do .env")
    ap.add_argument("--think", nargs="+", default=["auto"], choices=["auto", "on", "off"])
    ap.add_argument("--n", type=int, default=5, help="quantidade de editais (padrão 5)")
    ap.add_argument("--timeout", type=int, default=300, help="segundos por chamada (padrão 300)")
    args = ap.parse_args(argv)

    import config
    from core.ai_engine import extrair_dados_com_ia
    from core.ai_validator import validar_resultado

    modelos = args.modelos or [config.OLLAMA_MODEL]
    combos = [(m, t) for m in modelos for t in args.think]
    amostra = _carregar_amostra(config.supabase, args.n)
    if not amostra:
        print("Nenhum edital CONCLUIDO com texto_extracao para usar como amostra.")
        return 1
    print(f"Amostra: {len(amostra)} editais | combinações: {len(combos)} | timeout: {args.timeout}s")

    linhas = []
    for modelo in modelos:
        print(f"\nAquecendo {modelo}...")
        _aquecer(config, modelo)
        linhas += executar_benchmark(amostra, [c for c in combos if c[0] == modelo],
                                     extrair_dados_com_ia, validar_resultado, args.timeout)

    print("\n" + "=" * 90 + "\n" + formatar_resumo(resumir(linhas)))
    div = divergencias(linhas)
    if div:
        print(f"\nEditais em que os modelos DISCORDAM no prazo ({len(div)}):")
        for url, v in div.items():
            print(f"  {url}")
            for (m, t), prazo in v.items():
                print(f"      {m} (think={t}): {prazo}")

    pasta = os.path.join(config.DIRETORIO_PAI, "logs_auditoria")
    os.makedirs(pasta, exist_ok=True)
    caminho = os.path.join(pasta, f"benchmark_modelos_{datetime.now():%Y%m%d_%H%M%S}.csv")
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        w.writeheader()
        w.writerows(linhas)
    print(f"\nDetalhes por edital: {caminho}")
    return 0


if __name__ == "__main__":
    sys.exit(main())