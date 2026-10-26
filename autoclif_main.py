import os
import sys
import time
import calendar
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import gspread
from oauth2client.service_account import ServiceAccountCredentials

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.keys import Keys

# Ajuste de encoding para evitar erros no terminal
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# --- CONFIGURAÇÕES GERAIS - AUTOCLIF ---
URL_SISTEMA = "https://sesce.clif.rvimola.com.br"
PLANILHA_URL = "https://docs.google.com/spreadsheets/d/11tMl509ya0kzIijINjv3KmhaWzTX5GzG6cCD5WEznwo/edit#gid=0"
USUARIO = "THIAGO.FARIAS"
SENHA = "251090#"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_PATH = os.path.join(BASE_DIR, "downloads")
CHAVE_JSON = os.path.join(BASE_DIR, "chave_google.json")

if not os.path.exists(DOWNLOAD_PATH):
    os.makedirs(DOWNLOAD_PATH)


# --- FUNÇÕES DE APOIO ---

def limpar_pasta_downloads():
    for f in os.listdir(DOWNLOAD_PATH):
        try:
            os.remove(os.path.join(DOWNLOAD_PATH, f))
        except Exception:
            pass

def obter_datas_mes_atual():
    hoje = datetime.now()
    data_ini = hoje.replace(day=1).strftime("%d/%m/%Y")
    ultimo_dia = calendar.monthrange(hoje.year, hoje.month)[1]
    data_fim = hoje.replace(day=ultimo_dia).strftime("%d/%m/%Y")
    return data_ini, data_fim

def pedir_datas_usuario():
    d_ini_def, d_fim_def = obter_datas_mes_atual()
    print(f"\n📅 Período padrão detectado (Mês Atual): {d_ini_def} até {d_fim_def}")
    opcao = input("Deseja usar este período? (S/N) [Padrão: S]: ").strip().upper()
    
    if opcao == 'N':
        d_ini = input("Informe a Data Inicial (DD/MM/AAAA): ").strip()
        d_fim = input("Informe a Data Final (DD/MM/AAAA): ").strip()
        return d_ini, d_fim
    return d_ini_def, d_fim_def

def configurar_driver():
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    prefs = {
        "download.default_directory": DOWNLOAD_PATH,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    chrome_options.add_experimental_option("prefs", prefs)
    return webdriver.Chrome(options=chrome_options)

def aguardar_download(timeout=90):
    segundos = 0
    while segundos < timeout:
        arquivos = os.listdir(DOWNLOAD_PATH)
        baixando = any(".crdownload" in f or ".tmp" in f for f in arquivos)
        finalizado = any(f.endswith((".xlsx", ".xls")) for f in arquivos)
        
        if finalizado and not baixando:
            time.sleep(2) 
            return True
        time.sleep(1)
        segundos += 1
    return False

def conectar_google_sheets(nome_aba):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CHAVE_JSON, scope)
    client = gspread.authorize(creds)
    return client.open_by_url(PLANILHA_URL).worksheet(nome_aba)

def enviar_dataframe_para_sheets(sheet, df, limpar=True, celula_inicio='A1'):
    # Tratamento numérico e infinitos
    df.replace(['inf', 'Inf', 'INF', 'infinity', 'Infinity'], np.inf, inplace=True)
    df.replace(['-inf', '-Inf', '-INF', '-infinity'], -np.inf, inplace=True)
    df.replace([np.inf, -np.inf], 0, inplace=True)

    # Formatação de Datas
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime('%d/%m/%Y %H:%M:%S')

    # Limpeza e conversão
    for col in df.columns:
        if df[col].dtype == 'object':
            df[col] = df[col].astype(str).str.replace("'", "").str.replace(",", ".").str.strip()
        
        serie_aux = pd.to_numeric(df[col], errors='coerce')
        if serie_aux.notnull().sum() > (len(df) * 0.5):
            df[col] = serie_aux.replace([np.inf, -np.inf], 0)

    df = df.fillna("")
    
    dados_finais = [df.columns.values.tolist()]
    for row in df.values.tolist():
        processed_row = []
        for item in row:
            if isinstance(item, float) and (np.isinf(item) or np.isnan(item)):
                processed_row.append(0)
            elif isinstance(item, (datetime, pd.Timestamp)):
                processed_row.append(str(item))
            else:
                processed_row.append(item)
        dados_finais.append(processed_row)

    if limpar:
        sheet.clear()
    
    sheet.update(celula_inicio, dados_finais)

def enviar_para_google(caminho_excel, nome_aba):
    try:
        print(f"📌 Processando e enviando para a aba '{nome_aba}'...")
        sheet = conectar_google_sheets(nome_aba)
        df = pd.read_excel(caminho_excel)

        enviar_dataframe_para_sheets(sheet, df, limpar=True, celula_inicio='A1')

        horario_atual = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        sheet.update_acell('Z1', f"Atualizado em: {horario_atual}")
        
        print(f"✅ SUCESSO: Aba '{nome_aba}' atualizada!")
        return df
    except Exception as e:
        print(f"❌ ERRO CRÍTICO no Google Sheets ({nome_aba}): {str(e)}")
        return None


# --- INTELIGÊNCIA & PROCESSAMENTO DE KPIS ---

def processar_kpi_bloqueados(caminho_excel):
    """
    Lê o relatório bruto de produtos bloqueados, gera os resumos consolidados,
    encontra a data do último bloqueio e cria a lista detalhada tratada.
    """
    try:
        print("🧠 Processando inteligência, lista detalhada e KPIs de Bloqueados...")
        df = pd.read_excel(caminho_excel)
        
        cols = df.columns.tolist()
        col_codigo = cols[1] if len(cols) > 1 else 'Produto'
        col_desc = cols[2] if len(cols) > 2 else 'Grupo'
        col_projeto = cols[8] if len(cols) > 8 else 'Projeto'
        col_valor = cols[18] if len(cols) > 18 else 'Valor Total'
        col_motivo = cols[19] if len(cols) > 19 else 'Motivo'
        col_data = cols[20] if len(cols) > 20 else 'Data'
        col_usuario = cols[21] if len(cols) > 21 else 'Usuário'
        col_detalhe = cols[23] if len(cols) > 23 else 'Descrição'

        df[col_valor] = pd.to_numeric(df[col_valor], errors='coerce').fillna(0)

        # 1. Resumo por Motivo
        res_motivo = df.groupby(col_motivo).agg(
            QTD_ITENS=(col_codigo, 'count'),
            VALOR_TOTAL=(col_valor, 'sum')
        ).reset_index().sort_values(by='VALOR_TOTAL', ascending=False)

        # 2. Resumo por Usuário
        res_usuario = df.groupby(col_usuario).agg(
            QTD_BLOQUEIOS=(col_codigo, 'count'),
            VALOR_TOTAL=(col_valor, 'sum')
        ).reset_index().sort_values(by='VALOR_TOTAL', ascending=False)

        # 3. Resumo por Projeto
        res_projeto = df.groupby(col_projeto).agg(
            QTD_ITENS=(col_codigo, 'count'),
            VALOR_TOTAL=(col_valor, 'sum')
        ).reset_index().sort_values(by='VALOR_TOTAL', ascending=False)

        # 4. Data do Último Bloqueio registrado
        df_datas = pd.to_datetime(df[col_data], errors='coerce', dayfirst=True)
        data_ultimo_bloqueio = df_datas.max().strftime('%d/%m/%Y %H:%M:%S') if pd.notnull(df_datas.max()) else "N/I"

        # 5. Lista Detalhada Limpa (Filtrando e ordenando)
        df_detalhado = df[[col_data, col_codigo, col_desc, col_projeto, col_motivo, col_usuario, col_detalhe, col_valor]].copy()
        df_detalhado.columns = ['DATA_BLOQUEIO', 'CODIGO', 'DESCRICAO_ITEM', 'PROJETO', 'MOTIVO_BLOQUEIO', 'USUARIO', 'DETALHE_MOTIVO', 'VALOR_TOTAL']
        
        # Converte data temporariamente para ordenar do mais recente para o mais antigo
        df_detalhado['DATA_TMP'] = pd.to_datetime(df_detalhado['DATA_BLOQUEIO'], errors='coerce', dayfirst=True)
        df_detalhado = df_detalhado.sort_values(by='DATA_TMP', ascending=False).drop(columns=['DATA_TMP'])

        # Envia tudo para a aba KPI_BLOQUEADOS
        sheet_kpi = conectar_google_sheets("KPI_BLOQUEADOS")
        sheet_kpi.clear()

        # Blocos Superiores (Resumos)
        sheet_kpi.update_acell('A1', "--- RESUMO POR MOTIVO DE BLOQUEIO ---")
        enviar_dataframe_para_sheets(sheet_kpi, res_motivo, limpar=False, celula_inicio='A2')

        sheet_kpi.update_acell('E1', "--- RESUMO POR USUÁRIO ---")
        enviar_dataframe_para_sheets(sheet_kpi, res_usuario, limpar=False, celula_inicio='E2')

        sheet_kpi.update_acell('I1', "--- RESUMO POR PROJETO ---")
        enviar_dataframe_para_sheets(sheet_kpi, res_projeto, limpar=False, celula_inicio='I2')

        # Indicadores de Cabeçalho
        horario_atual = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        sheet_kpi.update_acell('M1', f"Atualizado em: {horario_atual}")
        sheet_kpi.update_acell('M2', f"Último Bloqueio registrado em: {data_ultimo_bloqueio}")

        # Bloco da Lista Detalhada (Inicia a partir da linha 25 para dar espaço aos resumos)
        sheet_kpi.update_acell('A25', "--- LISTA DETALHADA DOS ITENS BLOQUEADOS ---")
        enviar_dataframe_para_sheets(sheet_kpi, df_detalhado, limpar=False, celula_inicio='A26')

        print(f"✅ SUCESSO: Lista detalhada e Último Bloqueio ({data_ultimo_bloqueio}) enviados para 'KPI_BLOQUEADOS'!")

    except Exception as e:
        print(f"❌ ERRO ao processar KPI de Bloqueados: {str(e)}")


# --- AUTENTICAÇÃO CLIF ---

def realizar_login(driver, wait):
    print("\n🔐 Acessando o CLIF para efetuar Login...")
    driver.get(URL_SISTEMA)
    
    try:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Entrar')] | //button[contains(., 'Entrar')]")))
        driver.execute_script("arguments[0].click();", btn)
    except Exception:
        pass

    wait.until(EC.element_to_be_clickable((By.NAME, "data[Usuario][login]"))).send_keys(USUARIO)
    driver.find_element(By.NAME, "data[Usuario][senha]").send_keys(SENHA)
    driver.find_element(By.NAME, "data[Usuario][senha]").send_keys(Keys.ENTER)
    
    time.sleep(5)
    driver.get("https://sesce.clif.rvimola.com.br/Homes/index/all")
    print("🔓 Login realizado com sucesso!")


# --- ROTINAS DE EXTRAÇÃO ---

def rotina_bloqueados(driver, wait):
    print("\n📦 Executando Rotina: [Produtos Bloqueados]")
    driver.get("https://sesce.clif.rvimola.com.br/Relprodutosbloqueados/listarprodutos")
    Select(wait.until(EC.element_to_be_clickable((By.ID, "filtro_unidade")))).select_by_value("1")
    time.sleep(2)
    driver.execute_script("document.getElementById('RelprodutosbloqueadoTipofiltro').value='1'; EscolhaTipoRelatorio();")
    wait.until(EC.element_to_be_clickable((By.ID, "XLSX"))).click()
    if aguardar_download():
        arquivo = max([os.path.join(DOWNLOAD_PATH, f) for f in os.listdir(DOWNLOAD_PATH)], key=os.path.getctime)
        # 1. Atualiza base bruta
        enviar_para_google(arquivo, "bloqueados")
        # 2. Atualiza aba de inteligência / KPI
        processar_kpi_bloqueados(arquivo)
        os.remove(arquivo)

def rotina_pendentes(driver, wait):
    print("\n📥 Executando Rotina: [Entradas Pendentes]")
    driver.get("https://sesce.clif.rvimola.com.br/Relentradaspendentes/filtroentradas")
    Select(wait.until(EC.element_to_be_clickable((By.ID, "filtro_unidade")))).select_by_value("1")
    time.sleep(2)
    driver.execute_script("document.getElementById('RelentradaspendenteTipofiltro').value = '1'; EscolhaTipoRelatorio();")
    wait.until(EC.element_to_be_clickable((By.ID, "XLSX"))).click()
    if aguardar_download():
        arquivo = max([os.path.join(DOWNLOAD_PATH, f) for f in os.listdir(DOWNLOAD_PATH)], key=os.path.getctime)
        enviar_para_google(arquivo, "ENTRADAS PENDENTES")
        os.remove(arquivo)

def rotina_concluidas(driver, wait, d_ini, d_fim):
    print(f"\n✅ Executando Rotina: [Entradas Concluídas] ({d_ini} a {d_fim})")
    driver.get("https://sesce.clif.rvimola.com.br/Relentradasconcluidasdetalhados/filtroentradas")
    Select(wait.until(EC.element_to_be_clickable((By.ID, "filtro_unidade")))).select_by_value("1")
    time.sleep(2)
    driver.execute_script(f"document.getElementById('data_inicio').value='{d_ini}'; document.getElementById('data_final').value='{d_fim}'; document.getElementById('RelentradasconcluidasdetalhadoTipofiltro').value='1'; EscolhaTipoRelatorio();")
    wait.until(EC.element_to_be_clickable((By.ID, "XLSX"))).click()
    if aguardar_download():
        arquivo = max([os.path.join(DOWNLOAD_PATH, f) for f in os.listdir(DOWNLOAD_PATH)], key=os.path.getctime)
        enviar_para_google(arquivo, "ENTRADAS CONCLUÍDAS")
        os.remove(arquivo)

def rotina_pedidos_aberto(driver, wait):
    print("\n📋 Executando Rotina: [Pedidos em Aberto]")
    driver.get("https://sesce.clif.rvimola.com.br/Relsaidasgerals/filtrosaidas")
    Select(wait.until(EC.element_to_be_clickable((By.ID, "filtro_unidade")))).select_by_value("1")
    time.sleep(4)
    driver.execute_script("document.getElementById('cod_wms').value='1'; document.getElementById('filtro_nstatus_ped').value='0'; document.getElementById('RelsaidasgeralTipofiltro').value='1'; EscolhaTipoRelatorio();")
    wait.until(EC.element_to_be_clickable((By.ID, "XLSX"))).click()
    if aguardar_download(90):
        arquivo = max([os.path.join(DOWNLOAD_PATH, f) for f in os.listdir(DOWNLOAD_PATH)], key=os.path.getctime)
        enviar_para_google(arquivo, "PEDIDOS EM ABERTO")
        os.remove(arquivo)

def rotina_saidas_concluidas(driver, wait, d_ini, d_fim):
    print(f"\n🚚 Executando Rotina: [Saídas Concluídas] ({d_ini} a {d_fim})")
    driver.get("https://sesce.clif.rvimola.com.br/Relsaidasconcluidas/listarprodutos")
    Select(wait.until(EC.element_to_be_clickable((By.ID, "filtro_unidade")))).select_by_value("1")
    time.sleep(4)
    driver.execute_script(f"document.getElementById('data_inicio').value = '{d_ini}'; document.getElementById('data_final').value = '{d_fim}'; document.getElementById('RelsaidasconcluidaTipofiltro').value = '1'; EscolhaTipoRelatorio();")
    wait.until(EC.element_to_be_clickable((By.ID, "XLSX"))).click()
    if aguardar_download():
        arquivo = max([os.path.join(DOWNLOAD_PATH, f) for f in os.listdir(DOWNLOAD_PATH)], key=os.path.getctime)
        enviar_para_google(arquivo, "SAÍDAS CONCLUÍDAS")
        os.remove(arquivo)

def rotina_coletor(driver, wait, d_ini, d_fim):
    print(f"\n📱 Executando Rotina: [Pickings por Coletor] ({d_ini} a {d_fim})")
    driver.get("https://sesce.clif.rvimola.com.br/Relpickingporcoletors/index")
    Select(wait.until(EC.element_to_be_clickable((By.ID, "filtro_unidade")))).select_by_value("1")
    time.sleep(2)
    driver.execute_script(f"""
        document.getElementById('data_inicio').value = '{d_ini}';
        document.getElementById('data_final').value = '{d_fim}';
        document.getElementById('RelpickingporcoletorTipofiltro').value = '1';
        EscolhaTipoRelatorio();
    """)
    wait.until(EC.element_to_be_clickable((By.ID, "XLSX"))).click()
    if aguardar_download():
        arquivo = max([os.path.join(DOWNLOAD_PATH, f) for f in os.listdir(DOWNLOAD_PATH)], key=os.path.getctime)
        enviar_para_google(arquivo, "COLETOR")
        os.remove(arquivo)


# --- INTERFACE / MENU PRINCIPAL ---

def exibir_menu():
    print("\n" + "=" * 45)
    print("          🤖 AutoCLIF - SYSTEM MENU          ")
    print("=" * 45)
    print("  [1] Atualizar Produtos Bloqueados")
    print("  [2] Atualizar Entradas Pendentes")
    print("  [3] Atualizar Entradas Concluídas")
    print("  [4] Atualizar Pedidos em Aberto")
    print("  [5] Atualizar Saídas Concluídas")
    print("  [6] Atualizar Pickings por Coletor")
    print("  [7] 🔄 ATUALIZAR TODOS OS RELATÓRIOS")
    print("  [0] Sair")
    print("=" * 45)

def executar_operacao(opcao):
    datas_filtro = None
    if opcao in ["3", "5", "6", "7"]:
        datas_filtro = pedir_datas_usuario()

    limpar_pasta_downloads()
    driver = configurar_driver()
    wait = WebDriverWait(driver, 45)
    
    try:
        realizar_login(driver, wait)
        
        if opcao == "1":
            rotina_bloqueados(driver, wait)
        elif opcao == "2":
            rotina_pendentes(driver, wait)
        elif opcao == "3":
            rotina_concluidas(driver, wait, datas_filtro[0], datas_filtro[1])
        elif opcao == "4":
            rotina_pedidos_aberto(driver, wait)
        elif opcao == "5":
            rotina_saidas_concluidas(driver, wait, datas_filtro[0], datas_filtro[1])
        elif opcao == "6":
            rotina_coletor(driver, wait, datas_filtro[0], datas_filtro[1])
        elif opcao == "7":
            print("\n🚀 INICIANDO ATUALIZAÇÃO COMPLETA DE TODAS AS BASES...")
            rotina_bloqueados(driver, wait)
            rotina_pendentes(driver, wait)
            rotina_concluidas(driver, wait, datas_filtro[0], datas_filtro[1])
            rotina_pedidos_aberto(driver, wait)
            rotina_saidas_concluidas(driver, wait, datas_filtro[0], datas_filtro[1])
            rotina_coletor(driver, wait, datas_filtro[0], datas_filtro[1])
            print("\n🎉 TODAS AS BASES FORAM ATUALIZADAS COM SUCESSO!")

    except Exception as e:
        print(f"\n❌ ERRO durante a execução: {e}")
    finally:
        driver.quit()
        print("🏁 Sessão do navegador encerrada.")

def main():
    while True:
        exibir_menu()
        opcao = input("Escolha uma opção: ").strip()
        
        if opcao in ["1", "2", "3", "4", "5", "6", "7"]:
            executar_operacao(opcao)
            input("\nPressione [ENTER] para voltar ao menu...")
        elif opcao == "0":
            print("\nEncerrando AutoCLIF. Até logo!")
            break
        else:
            print("\n⚠️ Opção inválida. Tente novamente.\n")

if __name__ == "__main__":
    main()