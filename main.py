"""
main.py foi dividido em dois processos independentes (a IA não espera mais a varredura dos portais):

    python main_busca.py     # percorre os portais e grava editais novos
    python main_ia.py        # analisa os editais com a IA + relatório semanal

Rode os dois (dois terminais, ou duas tarefas do Agendador de Tarefas do Windows).
"""
import sys

print(__doc__)
sys.exit(1)