"""Sessão HTTP compartilhada com retry/backoff para lidar com instabilidade dos portais."""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def criar_sessao():
    sessao = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.5,                       # espera 1.5s, 3s, 6s...
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
        respect_retry_after_header=True,
    )
    adaptador = HTTPAdapter(max_retries=retry, pool_maxsize=10)
    sessao.mount("http://", adaptador)
    sessao.mount("https://", adaptador)
    sessao.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "pt-BR,pt;q=0.9",
    })
    return sessao


SESSAO = criar_sessao()