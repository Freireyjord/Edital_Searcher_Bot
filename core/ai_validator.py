"""
Validação e normalização da resposta do LLM.

O modelo pode devolver: campos ausentes, listas no lugar de texto, datas em
formatos variados, anos absurdos (9999), "Não encontrada" como string etc.
Tudo passa por aqui antes de tocar no banco.
"""
import re
import unicodedata
from datetime import date

from utils.texto_utils import status_indica_encerrado

# Valores que significam "vazio" (comparados sem acento e em minúsculas)
_VAZIOS = {
    "", "nao encontrada", "nao encontrado", "nao localizada", "nao localizado",
    "nao informada", "nao informado", "nao identificada", "nao identificado",
    "n/a", "na", "null", "none", "nenhum", "nenhuma", "-",
}

# Tags que o prompt proíbe, reforçadas por código (LLM às vezes ignora a regra)
_TAGS_PROIBIDAS_EXATAS = {
    "edital", "editais", "chamada", "chamada publica", "chamadas", "processo seletivo",
    "convenio", "termo de referencia", "governo federal", "oportunidade", "oportunidades",
    "geral", "inovacao", "pesquisa",
}
_TAGS_PROIBIDAS_PALAVRAS = re.compile(
    r"\b(finep|cnpq|fundep|petrobras|sigitec|capes|bndes|mctic|ministerio|fapesb|fapemig)\b"
)

ANO_MIN, ANO_MAX = 2000, 2100

# Títulos que são cabeçalho/placeholder (o modelo copia o cabeçalho do portal em vez do título do edital)
_TITULOS_GENERICOS = {
    "edital sem titulo", "sem titulo", "edital", "oportunidade", "oportunidades",
    "oportunidades de inovacao", "oportunidades de inovacao do cenpes",
}


class ConteudoInvalido(ValueError):
    """Resposta sem informação aproveitável. Repetir a IA não adianta (entrada ruim, temperatura 0)."""


def _norm(txt):
    txt = unicodedata.normalize("NFD", str(txt).strip().lower())
    return "".join(c for c in txt if unicodedata.category(c) != "Mn")


def texto_ou_none(valor, max_len=4000):
    """Converte qualquer coisa que o LLM devolver em str limpa, ou None se vazio."""
    if valor is None:
        return None
    if isinstance(valor, (list, tuple)):
        valor = "; ".join(str(v).strip() for v in valor if str(v).strip())
    elif isinstance(valor, dict):
        valor = "; ".join(f"{k}: {v}" for k, v in valor.items())
    else:
        valor = str(valor)

    valor = valor.strip()
    if _norm(valor) in _VAZIOS:
        return None
    return valor[:max_len]


def parse_data_iso(valor):
    """
    Aceita 'YYYY-MM-DD' (com ou sem hora), 'DD/MM/YYYY' e 'DD-MM-YYYY'.
    Retorna datetime.date ou None. Rejeita anos fora de 2000-2100
    (isso elimina sentinelas como 9999 e alucinações grosseiras).
    """
    txt = texto_ou_none(valor)
    if not txt:
        return None

    ano = mes = dia = None
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", txt)
    if m:
        ano, mes, dia = map(int, m.groups())
    else:
        m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})", txt)
        if m:
            dia, mes, ano = map(int, m.groups())

    if ano is None or not (ANO_MIN <= ano <= ANO_MAX):
        return None
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def normalizar_tags(valor, maximo=10):
    """Devolve string 'tag1, tag2, ...' sem duplicatas, sem termos proibidos."""
    if valor is None:
        return "Geral"

    if isinstance(valor, (list, tuple)):
        itens = [str(v) for v in valor]
    else:
        itens = re.split(r"[,;\n]", str(valor))

    tags, vistas = [], set()
    for item in itens:
        tag = item.strip().strip("-•*\"'[] ").strip()
        if not tag or len(tag) > 60:
            continue
        n = _norm(tag)
        if n in _VAZIOS or n in _TAGS_PROIBIDAS_EXATAS or _TAGS_PROIBIDAS_PALAVRAS.search(n):
            continue
        if n in vistas:
            continue
        vistas.add(n)
        tags.append(tag)
        if len(tags) >= maximo:
            break

    return ", ".join(tags) if tags else "Geral"


def _limpar_datas(txt):
    """
    Tira partes "Não encontrada" do texto de datas ("02-09-20 - Não encontrada" -> "Iniciado em 02-09-20").
    O prompt pede 'DD-MM-YY - DD-MM-YY' (abertura - encerramento); quando o modelo preenche o lado
    que faltou com "Não encontrada", isso vazava para a coluna Prazo da UI.
    """
    if not txt:
        return None
    partes = [p.strip() for p in re.split(r"\s+-\s+", txt)]
    partes = [p for p in partes if p and _norm(p) not in _VAZIOS and "nao encontrad" not in _norm(p)]
    if not partes:
        return None
    limpo = " - ".join(partes)
    if re.fullmatch(r"\d{2}[-/]\d{2}[-/]\d{2,4}", limpo):      # sobrou só uma data: é a de abertura
        limpo = f"Iniciado em {limpo}"
    return limpo


def _titulo_utilizavel(titulo):
    n = _norm(titulo or "")
    return bool(n) and n not in _TITULOS_GENERICOS and "nao encontrad" not in n


def validar_resultado(bruto):
    """
    Recebe o JSON devolvido pelo LLM e retorna um dict pronto para o banco.
    Levanta ValueError se a resposta for inutilizável.
    """
    if not isinstance(bruto, dict):
        raise ValueError(f"JSON raiz não é um objeto ({type(bruto).__name__})")

    titulo = texto_ou_none(bruto.get("titulo"), 300)
    escopo = texto_ou_none(bruto.get("escopo"), 6000)

    if not _titulo_utilizavel(titulo):
        # Antes virava "Edital sem título" e entrava como CONCLUIDO. Agora é descartado.
        raise ConteudoInvalido(f"sem título específico do edital (veio: {titulo!r})")

    prazo = parse_data_iso(bruto.get("prazo_iso"))
    inicio = parse_data_iso(bruto.get("inicio_iso"))
    if inicio and prazo and inicio > prazo:
        inicio = None   # incoerente (início depois do prazo): o modelo errou ou trocou as datas

    datas = _limpar_datas(texto_ou_none(bruto.get("datas"), 200))

    return {
        "titulo": titulo,
        "datas": datas or "A consultar",
        # situação "Cancelada" / "Aguardando resultado do certame"... e sem prazo aberto
        "encerrado": prazo is None and status_indica_encerrado(datas or ""),
        "pesquisa": texto_ou_none(bruto.get("pesquisa"), 3000) or "Não encontrada",
        "escopo": escopo or "Não encontrado",
        "subvencao": texto_ou_none(bruto.get("subvencao"), 3000) or "Não encontrada",
        "vigencia_projeto": texto_ou_none(bruto.get("vigencia_projeto"), 500) or "Não encontrada",
        "tags_ia": normalizar_tags(bruto.get("tags_ia")),
        # Datas: None quando ausentes/inválidas (vira NULL no banco)
        "prazo_submissao": prazo,
        "inicio_edital": inicio,
        "fim_projeto": parse_data_iso(bruto.get("fim_projeto_iso")),
    }