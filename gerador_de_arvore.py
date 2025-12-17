import os

ignore = {'.git', '__pycache__', 'venv', 'chroma_db', '.idea', '.vscode', 'docs', 'node_modules'}

def list_files(startpath):
    with open("Estrutura-Arvore.md", "w", encoding="utf-8") as f:
        f.write("```text\n")
        for root, dirs, files in os.walk(startpath):
            dirs[:] = [d for d in dirs if d not in ignore]
            
            level = root.replace(startpath, '').count(os.sep)
            indent = ' ' * 4 * (level)
            f.write(f'{indent}{os.path.basename(root)}/\n')
            subindent = ' ' * 4 * (level + 1)
            for file in files:
                f.write(f'{subindent}{file}\n')
        f.write("```\n")

if __name__ == "__main__":
    list_files('.')
    print("Arquivo 'Estrutura-Arvore.md' gerado com sucesso!")