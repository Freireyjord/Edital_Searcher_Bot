"""
Utilitários de texto (sem dependências externas).

O texto bruto de um edital é composto por "fontes" (página HTML + PDFs anexos),
cada uma iniciada por uma linha marcadora. Isso permite que, ao enviar para a IA,
o orçamento de caracteres seja dividido entre as fontes (e não que um PDF enorme
engula todo o contexto).
"""
import re
import unicodedata

MARCADOR_FONTE = "=== FONTE:"
_MARCA_OMISSAO = "\n[... trecho intermediário omitido por tamanho ...]\n"


def limpar_texto_extraido(texto):
    if not texto:
        return ""
    texto = re.sub(r'[ \t]+', ' ', texto)
    texto = re.sub(r'[\r\n]+', '\n', texto)
    linhas = [linha.strip() for linha in texto.split('\n') if linha.strip()]
    return '\n'.join(linhas)


def montar_texto_com_fontes(fontes, max_chars):
    """fontes: lista de (tipo, origem, texto). Ignora fontes vazias."""
    partes = []
    for tipo, origem, texto in fontes:
        limpo = limpar_texto_extraido(texto)
        if limpo:
            partes.append(f"{MARCADOR_FONTE} {tipo} | {origem} ===\n{limpo}")
    return "\n\n".join(partes)[:max_chars]


def tamanho_util(texto):
    """Tamanho do texto sem contar as linhas marcadoras."""
    sem_marcas = re.sub(rf"(?m)^{re.escape(MARCADOR_FONTE)}.*$", "", texto or "")
    return len(sem_marcas.strip())


def cortar_head_tail(texto, limite, prop_cabeca=0.7):
    """Reduz para no máximo `limite` chars, mantendo início e fim (prazos/verbas costumam estar nas pontas)."""
    if len(texto) <= limite:
        return texto
    util = max(limite - len(_MARCA_OMISSAO), 0)
    cabeca = int(util * prop_cabeca)
    cauda = util - cabeca
    return texto[:cabeca] + _MARCA_OMISSAO + texto[len(texto) - cauda:]


def distribuir_orcamento(tamanhos, limite):
    """
    Divide `limite` entre as fontes: as pequenas ficam inteiras, e o que sobra
    é repartido igualmente entre as grandes (water-filling).
    """
    cotas = [0] * len(tamanhos)
    restante = limite
    pendentes = sorted(range(len(tamanhos)), key=lambda i: tamanhos[i])
    while pendentes:
        justa = restante // len(pendentes)
        menor = pendentes[0]
        if tamanhos[menor] <= justa:
            cotas[menor] = tamanhos[menor]
            restante -= tamanhos[menor]
            pendentes.pop(0)
        else:
            for i in pendentes:
                cotas[i] = justa
            break
    return cotas


def preparar_texto_para_ia(texto, limite):
    """Garante que o texto cabe em `limite` caracteres, respeitando as fontes."""
    texto = texto.strip()
    if len(texto) <= limite:
        return texto

    secoes = [s.strip() for s in re.split(rf"(?m)^(?={re.escape(MARCADOR_FONTE)})", texto) if s.strip()]
    if len(secoes) <= 1:
        return cortar_head_tail(texto, limite)

    disponivel = limite - 2 * (len(secoes) - 1)   # separadores "\n\n"
    cotas = distribuir_orcamento([len(s) for s in secoes], disponivel)
    return "\n\n".join(cortar_head_tail(s, c) for s, c in zip(secoes, cotas))


# ---------------------------------------------------------------------------
# Detectores de conteúdo imprestável / edital já encerrado
# ---------------------------------------------------------------------------
def _sem_acentos(txt):
    txt = unicodedata.normalize("NFD", str(txt or "").lower())
    return "".join(c for c in txt if unicodedata.category(c) != "Mn")


# Mensagens de erro que SPAs/portais mostram no lugar do conteúdo (a IA as "resumiria" como se fossem edital)
_PAGINA_ERRO = re.compile(
    r"(oportunidade nao encontrada|pagina nao encontrada|conteudo nao encontrado|"
    r"page not found|404 not found|acesso negado|access denied)"
)
_LIMITE_PAGINA_ERRO = 2000   # só é "página de erro" se o conteúdo útil for curto (edital de verdade é longo)


def texto_parece_pagina_erro(texto):
    """True se o conteúdo útil é basicamente uma tela de erro do portal (ex.: 'Oportunidade não encontrada')."""
    sem_marcas = re.sub(rf"(?m)^{re.escape(MARCADOR_FONTE)}.*$", "", texto or "").strip()
    return len(sem_marcas) < _LIMITE_PAGINA_ERRO and bool(_PAGINA_ERRO.search(_sem_acentos(sem_marcas)))


# Situação que indica que NÃO há mais submissão aberta
_ENCERRADO = re.compile(
    r"(aguardando resultado|cancelad[oa]|encerrad[oa]|resultado do certame|"
    r"finalizad[oa]|suspens[oa]|homologad[oa]|certame concluido)"
)


def status_indica_encerrado(texto):
    """True para 'Aguardando resultado do certame', 'Cancelada', 'Encerrada'... (não casa 'encerramento')."""
    return bool(_ENCERRADO.search(_sem_acentos(texto)))