"""
Garante UMA instância por papel ('busca', 'ia').

Importante porque: dois workers da IA processariam os mesmos editais em dobro, e dois agendadores
de relatório poderiam enviar e-mails duplicados. O lock é do sistema operacional: some sozinho se o
processo morrer (não fica "preso" como um arquivo .pid).
"""
import os
import sys

_MANTER_VIVO = []   # o handle precisa viver até o fim do processo


def garantir_instancia_unica(nome, log=print, pasta=None):
    if pasta is None:
        import config
        pasta = os.path.join(config.DIRETORIO_PAI, ".locks")
    os.makedirs(pasta, exist_ok=True)

    arquivo = open(os.path.join(pasta, f"{nome}.lock"), "a+")
    try:
        if os.name == "nt":
            import msvcrt
            arquivo.seek(0)
            msvcrt.locking(arquivo.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        arquivo.close()
        log(f"[⛔] Já existe outra instância '{nome}' em execução. Encerrando esta.")
        sys.exit(1)

    _MANTER_VIVO.append(arquivo)
    return arquivo