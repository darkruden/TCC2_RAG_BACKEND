import os

# Verifique se o diretório existe
path = './chroma_db'
if not os.path.exists(path):
    os.makedirs(path)

# Teste se o Python consegue criar um arquivo
test_file = os.path.join(path, 'test_file.txt')
with open(test_file, 'w') as f:
    f.write("Teste de criação de arquivo no diretório chroma_db")

print(f"Arquivo de teste criado em: {test_file}")
