"""
Script de Teste Unitário para o portal Mover.
Valida se apenas os elementos de 'CHAMADAS ABERTAS' estão sendo capturados.
"""
import os
import sys
from bs4 import BeautifulSoup
import urllib.parse

# Garante o path do projeto para carregar módulos internos se necessário
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Simulação simplificada da lógica de extração do mover.py usando uma string estática HTML
def extrair_html_teste(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    url_base = "https://mover.fundep.ufmg.br/chamadas-publicas/"
    
    header_abertas = None
    for h2 in soup.find_all("h2"):
        if "CHAMADAS ABERTAS" in h2.get_text().upper():
            header_abertas = h2.find_parent("div", class_="porto-u-heading") or h2
            break
            
    if not header_abertas:
        return []

    editais_encontrados = []
    atual = header_abertas.find_next_sibling()
    
    while atual:
        # Se bater em outro bloco de cabeçalho (ex: CHAMADAS EM AVALIAÇÃO), para a execução
        if atual.name == "div" and "porto-u-heading" in atual.get("class", []):
            if "CHAMADAS" in atual.get_text().upper():
                break
                
        # Captura os botões dentro do bloco atual
        containers = atual.find_all(class_="vc_btn3-container") if atual.name != "div" else [atual]
        if "vc_btn3-container" in atual.get("class", []):
            containers = [atual]
            
        for c in containers:
            if "vc_btn3-container" in c.get("class", []) or c.find("a"):
                link_tag = c.find("a") if c.name != "a" else c
                if link_tag and link_tag.get("href"):
                    url_completa = urllib.parse.urljoin(url_base, link_tag.get("href"))
                    texto_btn = link_tag.get_text(strip=True)
                    editais_encontrados.append((texto_btn, url_completa))
                    
        atual = atual.find_next_sibling()
        
    return editais_encontrados


if __name__ == "__main__":
    # Conteúdo HTML resumido fornecido pelo usuário (contendo Abertas e Encerradas)
    html_mock = """
    <div class="porto-u-heading"><h2>CHAMADAS ABERTAS</h2></div>
    <div class="vc_btn3-container"><a href="https://ufmg.br">LINHA VI - CHAMADA DE PD&I 01.2026</a></div>
    <div class="vc_btn3-container"><a href="https://ufmg.br">LINHA IV - PROJETO DE NITRETAÇÃO POR PLASMA</a></div>
    <div class="vc_btn3-container"><a href="https://conectamais.ind.br">LINHA IV - CONECTA MAIS</a></div>
    
    <div class="porto-u-heading"><h2>CHAMADAS EM AVALIAÇÃO</h2></div>
    <div class="porto-u-heading"><h2>CHAMADAS ENCERRADAS</h2></div>
    <div class="vc_btn3-container"><a href="https://ufmg.br">LINHA V - CHAMADA PÚBLICA DE PD&I 01.2026</a></div>
    """

    print("=== INICIANDO TESTE DO PORTAL MOVER ===")
    resultados = extrair_html_teste(html_mock)
    
    print(f"Total de editais abertos encontrados: {len(resultados)}")
    for idx, (titulo, url) in enumerate(resultados, 1):
        print(f" {idx}. [{titulo}] -> {url}")
        
    # Validações de segurança do teste
    titulos_encontrados = [r[0] for r in resultados]
    
    assert len(resultados) == 3, f"Erro: Esperava 3 editais, mas achou {len(resultados)}"
    assert "LINHA V - CHAMADA PÚBLICA DE PD&I 01.2026" not in titulos_encontrados, "Erro: Capturou edital da seção ENCERRADAS!"
    
    print("\n[✓] SUCESSO: O filtro funcionou perfeitamente e ignorou as chamadas fechadas/encerradas!")
