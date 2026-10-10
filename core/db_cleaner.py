from datetime import date
import config

TAMANHO_LOTE = 200


def limpar_editais_expirados_no_banco(log_func):
    """
    Marca como 'expirado' os editais cujo prazo de submissão já passou.
    Editais sem prazo (prazo_iso NULL) nunca expiram por aqui: lt() ignora NULL.
    Também apaga o texto bruto (texto_extracao) para economizar espaço.
    """
    try:
        hoje_str = date.today().isoformat()
        vencidos = (config.supabase.table("editais").select("url")
                    .neq("status_ia", "expirado")
                    .lt("prazo_iso", hoje_str)
                    .execute().data)

        if not vencidos:
            return

        dados_expurgados = {
            "datas": "Expirado", "pesquisa": None, "subvencao": None,
            "escopo": "Dados limpos por expiração.", "tags_ia": None,
            "texto_extracao": None, "status_ia": "expirado",
        }

        urls = [item["url"] for item in vencidos]
        # Atualização em lote (antes era 1 requisição por edital)
        for i in range(0, len(urls), TAMANHO_LOTE):
            lote = urls[i:i + TAMANHO_LOTE]
            config.supabase.table("editais").update(dados_expurgados).in_("url", lote).execute()

        log_func(f"    [🧹 Limpeza] {len(urls)} editais marcados como expirados.")
    except Exception as e:
        log_func(f"Erro na limpeza: {e}")