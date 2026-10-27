import time
import requests
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from autoclif_main import (
    configurar_driver, 
    realizar_login, 
    rotina_bloqueados, 
    rotina_pendentes,
    rotina_concluidas,
    processar_kpi_recebimento,
    obter_datas_mes_atual,
    PLANILHA_URL, 
    CHAVE_JSON, 
    limpar_pasta_downloads
)
from selenium.webdriver.support.ui import WebDriverWait

# URL DO SEU SITE ONLINE NO RENDER (Sem a barra no final)
URL_SERVIDOR_WEB = "http://localhost:5000"

def conectar_sheets(nome_aba="bloqueados"):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CHAVE_JSON, scope)
    client = gspread.authorize(creds)
    return client.open_by_url(PLANILHA_URL).worksheet(nome_aba)

def enviar_status_nuvem(pct, msg, status="EM_ANDAMENTO"):
    print(f"[{pct}%] {msg}")
    try:
        requests.post(f"{URL_SERVIDOR_WEB}/api/atualizar/status-local", json={
            "status": status,
            "message": msg,
            "pct": pct
        }, timeout=5)
    except Exception as e:
        print(f"⚠️ Erro ao notificar servidor web: {e}")

def verificar_solicitacao_web():
    try:
        res = requests.get(f"{URL_SERVIDOR_WEB}/api/status/atualizacao", timeout=5)
        if res.status_code == 200:
            data = res.json()
            return data.get("status") == "PENDENTE"
    except Exception:
        pass
    return False

def executar_automacao_clif():
    print("\n🚀 [AGENTE LOCAL] Sinal de atualização detectado via Web! Iniciando automação de Entradas...")
    enviar_status_nuvem(10, "⚙️ Inicializando automação e Selenium local...")
    
    limpar_pasta_downloads()
    
    try:
        driver = configurar_driver()
        wait = WebDriverWait(driver, 45)
        
        enviar_status_nuvem(25, "🔐 Acessando o CLIF para efetuar Login...")
        realizar_login(driver, wait)
        
        enviar_status_nuvem(45, "📥 Baixando relatório de Entradas Pendentes...")
        rotina_pendentes(driver, wait)

        enviar_status_nuvem(65, "✅ Baixando relatório de Entradas Concluídas...")
        d_ini, d_fim = obter_datas_mes_atual()
        rotina_concluidas(driver, wait, d_ini, d_fim)

        driver.quit()

        enviar_status_nuvem(85, "🧠 Processando inteligência de Recebimento no Sheets...")
        processar_kpi_recebimento()

        agora_str = f"Atualizado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        try:
            sheet_kpi = conectar_sheets("KPI_RECEBIMENTO")
            sheet_kpi.update_acell('G1', agora_str)
        except Exception:
            pass
        
        enviar_status_nuvem(100, "✅ Concluído! Recebimento 100% atualizado.", status="CONCLUIDO")
        print("✅ [AGENTE LOCAL] Entradas e Recebimento atualizados com sucesso!")

    except Exception as e:
        erro_msg = f"❌ Erro: {str(e)}"
        print(erro_msg)
        enviar_status_nuvem(-1, erro_msg, status="ERRO")

def escutar_pedidos():
    print("-------------------------------------------------------")
    print("🤖 AGENTE LOCAL AUTOCLIF (RECEBIMENTO) CONECTADO...")
    print(f"Monitorando o servidor: {URL_SERVIDOR_WEB}")
    print("-------------------------------------------------------")
    
    while True:
        try:
            if verificar_solicitacao_web():
                executar_automacao_clif()
            
            time.sleep(3)
        except Exception as e:
            print(f"⚠️ Erro no ciclo de escuta: {e}")
            time.sleep(10)

if __name__ == '__main__':
    escutar_pedidos()