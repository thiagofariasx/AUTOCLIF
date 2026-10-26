import os
import time
import json
from datetime import datetime
import pandas as pd
import numpy as np
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, render_template, jsonify, Response

app = Flask(__name__)

# Tenta pegar as credenciais da Variável de Ambiente (Nuvem) ou do arquivo local
CHAVE_JSON = "chave_google.json"
PLANILHA_URL = "SUA_URL_DO_GOOGLE_SHEETS_AQUI"  # <-- Coloque sua URL do Google Sheets aqui

def conectar_google_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # Se estiver no Render (env var)
    creds_json_env = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json_env:
        creds_dict = json.loads(creds_json_env)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        # Execução local
        creds = ServiceAccountCredentials.from_json_keyfile_name(CHAVE_JSON, scope)
        
    client = gspread.authorize(creds)
    return client.open_by_url(PLANILHA_URL).worksheet("bloqueados")

def ler_bloqueados_google_sheets():
    try:
        sheet = conectar_google_sheets()
        
        data_atualizacao = ""
        try:
            val_z1 = sheet.acell('Z1').value
            if val_z1 and 'Unnamed' not in str(val_z1):
                data_atualizacao = str(val_z1).strip()
            else:
                val_m1 = sheet.acell('M1').value
                if val_m1 and 'Unnamed' not in str(val_m1):
                    data_atualizacao = str(val_m1).strip()
        except Exception:
            pass

        data = sheet.get_all_values()
        if not data or len(data) <= 1:
            return pd.DataFrame(), data_atualizacao
        
        header_idx = 0
        for idx, row in enumerate(data[:5]):
            if any('Cliente' in str(cell) or 'Produto' in str(cell) for cell in row):
                header_idx = idx
                break

        df = pd.DataFrame(data[header_idx + 1:], columns=data[header_idx])
        return df, data_atualizacao
    except Exception as e:
        print(f"Erro ao ler sheets: {e}")
        return pd.DataFrame(), ""

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/kpi/bloqueados', methods=['GET'])
def get_kpi_bloqueados():
    try:
        df, data_atualizacao = ler_bloqueados_google_sheets()
        if df.empty:
            return jsonify({"status": "empty", "message": "A aba 'bloqueados' está vazia.", "ultima_atualizacao": data_atualizacao})

        cols = {col.strip(): col for col in df.columns}

        def buscar_coluna(termos_busca, indice_fallback):
            for termo in termos_busca:
                for c in cols.keys():
                    if termo.lower() in c.lower():
                        return cols[c]
            return list(cols.values())[min(indice_fallback, len(cols) - 1)]

        col_codigo = buscar_coluna(['produto', 'código', 'item'], 1)
        col_desc = buscar_coluna(['grupo', 'descrição', 'desc'], 2)
        col_projeto = buscar_coluna(['projeto'], 8)
        col_valor = buscar_coluna(['valor total', 'valor', 'total'], 18)
        col_motivo = buscar_coluna(['motivo'], 19)
        col_data = buscar_coluna(['data', 'fabricação'], 20)
        col_usuario = buscar_coluna(['usuário', 'usuario'], 21)
        col_detalhe = buscar_coluna(['marca', 'detalhe', 'descrição', 'motivo detalhado'], 23)

        df = df[df[col_codigo].astype(str).str.lower() != 'produto'].copy()

        df[col_valor] = df[col_valor].astype(str).str.replace("R$", "", regex=False)
        df[col_valor] = df[col_valor].str.replace(".", "", regex=False).str.replace(",", ".", regex=False).str.strip()
        df[col_valor] = pd.to_numeric(df[col_valor], errors='coerce').fillna(0)

        df['dt_temp'] = pd.to_datetime(df[col_data], format='%d/%m/%Y', errors='coerce')
        df = df.sort_values(by='dt_temp', ascending=False)

        tabela = []
        for _, row in df.iterrows():
            tabela.append({
                'data': str(row[col_data]),
                'codigo': str(row[col_codigo]),
                'descricao': str(row[col_desc]),
                'projeto': str(row[col_projeto]),
                'motivo': str(row[col_motivo]),
                'usuario': str(row[col_usuario]),
                'detalhe': str(row[col_detalhe]) if pd.notnull(row[col_detalhe]) else '',
                'valor': float(row[col_valor])
            })

        return jsonify({
            "status": "success",
            "tabela": tabela,
            "ultima_atualizacao": data_atualizacao
        })
    except Exception as e:
        print(f"❌ ERRO API KPI: {str(e)}")
        return jsonify({"status": "error", "message": str(e)})

# ROTA DA NUVEM: Grava 'PENDENTE' na Z2 do Google Sheets para o Agente Local executar
@app.route('/stream/atualizar/bloqueados')
def stream_bloqueados():
    def generate():
        def send_log(msg, pct):
            return f"data: {json.dumps({'message': msg, 'pct': pct})}\n\n"

        yield send_log("📡 Solicitando atualização ao Agente Local no Brasil...", 20)
        try:
            sheet = conectar_google_sheets()
            sheet.update_acell('Z2', 'PENDENTE')
            
            # Fica monitorando a célula Z2 até o Agente Local terminar
            tentativas = 0
            while tentativas < 60: # Aguarda até 3 minutos
                time.sleep(3)
                tentativas += 1
                status = sheet.acell('Z2').value
                
                if status == 'EM_ANDAMENTO':
                    yield send_log("🔐 Agente local conectado no CLIF... processando", 50)
                elif status == 'CONCLUIDO':
                    yield send_log("✅ Concluído! Base 100% atualizada.", 100)
                    return
                elif status and 'ERRO' in status:
                    yield send_log(f"❌ {status}", -1)
                    return

            yield send_log("⚠️ Agente local não respondeu a tempo.", -1)
        except Exception as e:
            yield send_log(f"❌ Erro: {str(e)}", -1)

    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)