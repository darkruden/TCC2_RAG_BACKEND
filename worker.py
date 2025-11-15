# --- Instância Singleton para o Worker ---
try:
    _report_service_instance = ReportService()
    processar_e_salvar_relatorio = _report_service_instance.processar_e_salvar_relatorio
    print("[ReportService] Instância de serviço criada e função exportada.")
except Exception as e:
    #...
    processar_e_salvar_relatorio = None