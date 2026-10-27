import os
import time
import json
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, render_template, jsonify, request, send_from_directory

app = Flask(__name__)

CHAVE_JSON = "chave_google.json"
PLANILHA_URL = "https://docs.google.com/spreadsheets/d/11tMl509ya0kzIijINjv3KmhaWzTX5GzG6cCD5WEznwo/edit?gid=47982942#gid=47982942"

# Qual rotina o agente local deve rodar (cada botão do site envia o seu "tipo")
TIPOS_VALIDOS = ("bloqueados", "recebimento")
TEMPO_MAX_OCUPADO = 600  # segundos: depois disso uma atualização "travada" deixa de bloquear novos pedidos

STATUS_GLOBAL = {
    "status": "PARADO",
    "message": "Aguardando início...",
    "pct": 0,
    "tipo": "",
    "ts": 0
}

def conectar_planilha():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_json_env = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json_env:
        creds_dict = json.loads(creds_json_env)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        creds = ServiceAccountCredentials.from_json_keyfile_name(CHAVE_JSON, scope)
    return gspread.authorize(creds).open_by_url(PLANILHA_URL)

def ler_bloqueados_google_sheets():
    try:
        sh = conectar_planilha()
        sheet = sh.worksheet("bloqueados")
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
def index(): return render_template('index.html')

@app.route('/recebimento')
def recebimento(): return render_template('recebimento.html')

@app.route('/cedib')
@app.route('/cedib/')
def serve_cedib(): return send_from_directory('cedib', 'index.html')

@app.route('/cedib/<path:filename>')
def serve_cedib_static(filename): return send_from_directory('cedib', filename)

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
                    if termo.lower() in c.lower(): return cols[c]
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
        df[col_valor] = df[col_valor].astype(str).str.replace("R$", "", regex=False).str.replace(".", "", regex=False).str.replace(",", ".", regex=False).str.strip()
        df[col_valor] = pd.to_numeric(df[col_valor], errors='coerce').fillna(0)

        df['dt_temp'] = pd.to_datetime(df[col_data], format='%d/%m/%Y', errors='coerce')
        df = df.sort_values(by='dt_temp', ascending=False)

        tabela = [{
            'data': str(row[col_data]), 'codigo': str(row[col_codigo]), 'descricao': str(row[col_desc]),
            'projeto': str(row[col_projeto]), 'motivo': str(row[col_motivo]), 'usuario': str(row[col_usuario]),
            'detalhe': str(row[col_detalhe]) if pd.notnull(row[col_detalhe]) else '', 'valor': float(row[col_valor])
        } for _, row in df.iterrows()]

        return jsonify({"status": "success", "tabela": tabela, "ultima_atualizacao": data_atualizacao})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/kpi/recebimento', methods=['GET'])
def get_kpi_recebimento():
    try:
        hoje = datetime.now()
        primeiro_dia = hoje.replace(day=1).strftime('%Y-%m-%d')
        hoje_str = hoje.strftime('%Y-%m-%d')
        
        data_ini_iso = request.args.get('data_ini_iso', primeiro_dia)
        data_fim_iso = request.args.get('data_fim_iso', hoje_str)
        
        dt_i_obj = datetime.strptime(data_ini_iso, '%Y-%m-%d')
        dt_f_obj = datetime.strptime(data_fim_iso, '%Y-%m-%d')
        data_ini_br = dt_i_obj.strftime('%d/%m/%Y')
        data_fim_br = dt_f_obj.strftime('%d/%m/%Y')

        sh = conectar_planilha()
        sheet_kpi = sh.worksheet("KPI_RECEBIMENTO")
        
        try:
            sheet_kpi.update_acell('P2', data_ini_br)
            sheet_kpi.update_acell('Q2', data_fim_br)
            sheet_kpi.update_acell('T2', data_ini_br)
            sheet_kpi.update_acell('U2', data_fim_br)
            time.sleep(1)
        except Exception as e:
            print(f"Aviso ao atualizar datas no Sheets: {e}")

        total_notas_pendentes, total_volumes_pendentes = 0, 0
        conf_notas, end_notas, conf_vol, end_vol = 0, 0, 0, 0
        ultima_atl = ""
        
        try:
            ultima_atl = str(sheet_kpi.acell('G1').value or "")
            kpi_vals = sheet_kpi.get('A3:F3')
            if kpi_vals and len(kpi_vals) > 0:
                row = kpi_vals[0]
                def to_int(val):
                    try: return int(float(str(val).replace('.', '').replace(',', '.')))
                    except: return 0
                
                total_notas_pendentes = to_int(row[0]) if len(row) > 0 else 0
                total_volumes_pendentes = to_int(row[1]) if len(row) > 1 else 0
                conf_notas = to_int(row[2]) if len(row) > 2 else 0
                end_notas = to_int(row[3]) if len(row) > 3 else 0
                conf_vol = to_int(row[4]) if len(row) > 4 else 0
                end_vol = to_int(row[5]) if len(row) > 5 else 0
        except Exception as e:
            print(f"Erro ao ler totais do KPI: {e}")

        # LEITURA EXATA DAS MACROS (VOLUMES E NOTAS NAS COLUNAS M E N)
        macro_volumes = []
        macro_notas = []
        try:
            raw_data = sheet_kpi.get('M1:N15')
            # Volumes: M3:N7
            for r in raw_data[2:7]:
                if len(r) >= 2 and r[0]:
                    macro_volumes.append({
                        "macro": str(r[0]),
                        "valor": int(float(str(r[1]).replace('.', '').replace(',', '.'))) if str(r[1]).replace('.', '').isdigit() else 0
                    })
            # Notas: M10:N14
            for r in raw_data[9:14]:
                if len(r) >= 2 and r[0]:
                    macro_notas.append({
                        "macro": str(r[0]),
                        "valor": int(float(str(r[1]).replace('.', '').replace(',', '.'))) if str(r[1]).replace('.', '').isdigit() else 0
                    })
        except Exception as e:
            print(f"Erro ao ler Macros M e N: {e}")

        produtividade_enderecador = []
        try:
            raw_end = sheet_kpi.get('P2:R15')
            for r in raw_end:
                if len(r) >= 3 and r[0] and r[0].upper() not in ['ENDEREÇADOR', 'DATA INICIAL']:
                    produtividade_enderecador.append({
                        "nome": str(r[0]),
                        "notas": int(float(str(r[1]).replace('.', '').replace(',', '.'))) if str(r[1]).replace('.', '').isdigit() else 0,
                        "volumes": int(float(str(r[2]).replace('.', '').replace(',', '.'))) if len(r) > 2 and str(r[2]).replace('.', '').isdigit() else 0
                    })
        except Exception as e:
            print(f"Erro ao ler Endereçadores: {e}")

        produtividade_conferente = []
        try:
            raw_conf = sheet_kpi.get('T2:V15')
            for r in raw_conf:
                if len(r) >= 3 and r[0] and r[0].upper() not in ['CONFERENTE', 'DATA INICIAL']:
                    produtividade_conferente.append({
                        "nome": str(r[0]),
                        "notas": int(float(str(r[1]).replace('.', '').replace(',', '.'))) if str(r[1]).replace('.', '').isdigit() else 0,
                        "volumes": int(float(str(r[2]).replace('.', '').replace(',', '.'))) if len(r) > 2 and str(r[2]).replace('.', '').isdigit() else 0
                    })
        except Exception as e:
            print(f"Erro ao ler Conferentes: {e}")

        return jsonify({
            "status": "success",
            "total_notas_pendentes": total_notas_pendentes,
            "total_volumes_pendentes": total_volumes_pendentes,
            "conferencia_notas": conf_notas,
            "enderecamento_notas": end_notas,
            "conferencia_volumes": conf_vol,
            "enderecamento_volumes": end_vol,
            "macro_volumes": macro_volumes,
            "macro_notas": macro_notas,
            "produtividade_enderecador": produtividade_enderecador,
            "produtividade_conferente": produtividade_conferente,
            "ultima_atualizacao": ultima_atl
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/solicitar/atualizacao', methods=['POST', 'GET'])
def solicitar_atualizacao():
    global STATUS_GLOBAL
    tipo = (request.args.get('tipo') or 'recebimento').strip().lower()
    if tipo not in TIPOS_VALIDOS:
        return jsonify({"status": "error", "message": "Tipo de atualização inválido."}), 400

    # Só existe UM agente local: não deixa um botão atropelar a atualização do outro
    ocupado = (
        STATUS_GLOBAL.get("status") in ("PENDENTE", "EM_ANDAMENTO")
        and (time.time() - STATUS_GLOBAL.get("ts", 0)) < TEMPO_MAX_OCUPADO
    )
    if ocupado:
        return jsonify({
            "status": "busy",
            "message": f"Já existe uma atualização de '{STATUS_GLOBAL.get('tipo', '')}' em andamento. Aguarde terminar."
        })

    STATUS_GLOBAL = {
        "status": "PENDENTE",
        "message": "📡 Aguardando Agente Local iniciar...",
        "pct": 5,
        "tipo": tipo,
        "ts": time.time()
    }
    return jsonify({"status": "success", "tipo": tipo})

@app.route('/api/atualizar/status-local', methods=['POST'])
def atualizar_status_local():
    global STATUS_GLOBAL
    data = request.json
    if data:
        STATUS_GLOBAL = {
            "status": data.get("status", "EM_ANDAMENTO"),
            "message": data.get("message", ""),
            "pct": int(data.get("pct", 0)),
            "tipo": STATUS_GLOBAL.get("tipo", ""),   # mantém o tipo que foi solicitado
            "ts": time.time()
        }
    return jsonify({"status": "recebido"})

@app.route('/api/status/atualizacao', methods=['GET'])
def checar_status_atualizacao():
    return jsonify(STATUS_GLOBAL)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)