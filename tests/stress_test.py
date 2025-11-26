import requests
import concurrent.futures
import time
import json

# --- CONFIGURAÇÃO ---
API_URL = "https://meu-tcc-testes-041c1dd46d1d.herokuapp.com/api/chat"
# SUBSTITUA PELA SUA API KEY REAL (Pode pegar no Inspecionar Elemento da extensão -> Application -> Local Storage)
API_KEY = "d4936ab9-47f1-43ed-ae9a-51c3c3c4bc29" 

# O comando que simula o aluno clicando em "Ingerir"
PAYLOAD = {
    "messages": [
        {
            "sender": "user",
            "text": "Atualize o repositório darkruden/TCC2_RAG_BACKEND" 
        }
    ]
}

# Número de "alunos" simultâneos
NUM_REQUESTS = 30

def simulate_student(student_id):
    print(f"[Aluno {student_id}] Clicou em Ingerir...")
    start_time = time.time()
    
    try:
        response = requests.post(
            API_URL,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": API_KEY
            },
            json=PAYLOAD,
            timeout=30 # Timeout de conexão apenas
        )
        
        duration = time.time() - start_time
        
        if response.status_code == 200:
            data = response.json()
            # Verifica se entrou na fila
            if data.get("response_type") == "job_enqueued":
                return f"✅ [Aluno {student_id}] Sucesso! Job ID: {data.get('job_id')} ({duration:.2f}s)"
            else:
                return f"⚠️ [Aluno {student_id}] Resposta inesperada: {data.get('message')}"
        else:
            return f"❌ [Aluno {student_id}] Erro {response.status_code}: {response.text}"
            
    except Exception as e:
        return f"❌ [Aluno {student_id}] Falha de Conexão: {str(e)}"

def run_stress_test():
    print(f"--- INICIANDO TESTE DE ESTRESSE: {NUM_REQUESTS} REQUISIÇÕES SIMULTÂNEAS ---")
    print(f"Alvo: {API_URL}\n")
    
    start_global = time.time()
    
    # ThreadPoolExecutor dispara as requisições em paralelo (como se fossem navegadores diferentes)
    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_REQUESTS) as executor:
        # Agenda as execuções
        futures = [executor.submit(simulate_student, i+1) for i in range(NUM_REQUESTS)]
        
        # Coleta resultados conforme chegam
        for future in concurrent.futures.as_completed(futures):
            print(future.result())
            
    end_global = time.time()
    print(f"\n--- TESTE FINALIZADO EM {end_global - start_global:.2f} SEGUNDOS ---")

if __name__ == "__main__":
    run_stress_test()