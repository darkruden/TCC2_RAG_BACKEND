import requests
import time
import sys

# --- CONFIGURAÇÃO ---
API_URL = "https://meu-tcc-testes-041c1dd46d1d.herokuapp.com/api/chat"
API_KEY = "d4936ab9-47f1-43ed-ae9a-51c3c3c4bc29" # Sua Key de Teste

# Repositório alvo (Use um que você já tenha acesso ou seja público/pequeno)
# Sugestão: Um repo do próprio TCC ou um lib leve como 'requests'
TARGET_REPO = "darkruden/tcc2_rag_backend" 

def trigger_single_ingest():
    print(f"--- INICIANDO TESTE DE INGESTÃO ÚNICA (MODO TURBO) ---")
    print(f"Alvo: {TARGET_REPO}")
    
    payload = {
        "messages": [
            {
                "sender": "user",
                "text": f"Atualize o repositório {TARGET_REPO}"
            }
        ]
    }

    try:
        start_time = time.time()
        response = requests.post(
            API_URL,
            headers={
                "Content-Type": "application/json", 
                "X-API-Key": API_KEY
            },
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("response_type") == "job_enqueued":
                print(f"✅ SUCESSO: Job aceito pelo servidor!")
                print(f"🆔 Job ID: {data.get('job_id')}")
                print(f"⏱️ Tempo de Resposta da API: {time.time() - start_time:.2f}s")
                print("\n>>> AGORA VERIFIQUE OS LOGS DO HEROKU PARA CONFIRMAR O MODO TURBO <<<")
            else:
                print(f"⚠️ RESPOSTA INESPERADA: {data}")
        else:
            print(f"❌ ERRO HTTP {response.status_code}: {response.text}")

    except Exception as e:
        print(f"❌ EXCEÇÃO: {e}")

if __name__ == "__main__":
    trigger_single_ingest()