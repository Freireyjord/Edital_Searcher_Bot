from datetime import datetime
import config

def limpar_editais_expirados_no_banco(log_func):
    try:
        hoje_str = datetime.now().date().isoformat()
        editais_vencidos = config.supabase.table("editais").select("url, prazo_iso").not_.eq("status_ia", "expirado").not_.eq("prazo_iso", "9999-12-31 23:59").lt("prazo_iso", hoje_str).execute().data
        
        if not editais_vencidos: return
            
        dados_expurgados = {"datas": "Expirado", "pesquisa": None, "subvencao": None, "escopo": "Dados limpos por expiração.", "tags_ia": None, "status_ia": "expirado"}
        for item in editais_vencidos:
            config.supabase.table("editais").update(dados_expurgados).eq("url", item["url"]).execute()
    except Exception as e: log_func(f"Erro na limpeza: {e}")
