"""Normalização de URLs (sem I/O)."""


def canonicalizar_url(url):
    """
    Remove o fragmento ('#...'): para o servidor é a MESMA página.
    Ex.: finep.gov.br/credito-operado-por-agentes#finep-inovacred e ...#finep-inovacred-telecom são abas
    da mesma página; sem isso cada aba virava um "edital" repetido (e uma chamada de IA repetida).
    Mantém fragmentos de ROTA de SPA ('#/rota', '#!/rota'), onde o fragmento é a página.
    """
    base, separador, fragmento = (url or "").strip().partition("#")
    if separador and fragmento.startswith(("/", "!")):
        return url.strip()
    return base