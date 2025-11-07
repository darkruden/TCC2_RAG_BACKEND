import os
from dotenv import load_dotenv
from openai import OpenAI

# carrega o .env
load_dotenv()

# lê a chave da openai
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("❌ Nenhuma OPENAI_API_KEY encontrada no .env")
    exit()

# inicializa o cliente
client = OpenAI(api_key=api_key)

try:
    # faz uma requisição simples ao modelo gpt-4o-mini (barato e rápido)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Olá! só quero testar se a API está funcionando."}],
    )

    print("✅ Conexão bem-sucedida!")
    print("Resposta do modelo:", response.choices[0].message.content)

except Exception as e:
    print("❌ Erro ao conectar com a API da OpenAI:")
    print(e)
