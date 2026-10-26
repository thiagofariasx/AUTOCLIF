import time
import requests
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from autoclif_main import (
    configurar_driver, 
    realizar_login, 
    rotina_bloqueados, 
    PLANILHA_URL, 
    CHAVE_JSON, 
    limpar_pasta_downloads
)
from selenium.webdriver.support.ui import WebDriverWait

# URL DO SEU SITE ONLINE NO RENDER (Sem a barra no final)
URL_SERVIDOR_WEB = "https://autoclif.onrender.com"

def conectar_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CHAVE_JSON, scope)
    client = gspread.authorize(creds)
    return client.open_by_url(PLANILHA_URL).worksheet("bloqueados")

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
    print("\n🚀 [AGENTE LOCAL] Sinal de atualização detectado via Web! Iniciando automação...")
    enviar_status_nuvem(10, "⚙️ Inicializando automação e Selenium local...")
    
    limpar_pasta_downloads()
    sheet = conectar_sheets()
    
    try:
        driver = configurar_driver()
        wait = WebDriverWait(driver, 45)
        
        enviar_status_nuvem(30, "🔐 Acessando o CLIF para efetuar Login...")
        realizar_login(driver, wait)
        
        enviar_status_nuvem(65, "📦 Baixando relatório de Bloqueados...")
        rotina_bloqueados(driver, wait)
        driver.quit()

        enviar_status_nuvem(90, "📊 Atualizando inteligência no Google Sheets...")
        
        agora_str = f"Atualizado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        sheet.update_acell('Z1', agora_str)
        sheet.update_acell('M1', agora_str)
        
        enviar_status_nuvem(100, "✅ Concluído! Base 100% atualizada.", status="CONCLUIDO")
        print("✅ [AGENTE LOCAL] Base atualizada com sucesso e servidor notificado!")

    except Exception as e:
        erro_msg = f"❌ Erro: {str(e)}"
        print(erro_msg)
        enviar_status_nuvem(-1, erro_msg, status="ERRO")

def escutar_pedidos():
    print("-------------------------------------------------------")
    print("🤖 AGENTE LOCAL AUTOCLIF V2 CONECTADO À NUVEM...")
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