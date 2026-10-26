from core.workers import criar_logger
from portais.bndes import varrer

log = criar_logger("TESTE_BNDES")

# Abre o seu arquivo .txt com o HTML salvo
with open("bnds.txt", "r", encoding="utf-8") as f:
    html_bruto = f.read()

# Executa a varredura passando o HTML estático como parâmetro
varrer(log, html_conteudo=html_bruto)
