import matplotlib.pyplot as plt
import re
import numpy as np

# Dados extraídos manualmente do seu log 'stress_test_chat_result.log'
# para garantir precisão, já que não posso executar leitura de arquivos locais aqui.
# Fonte: Log fornecido no contexto.
data_points = [
    # Sucessos (Tempo em segundos)
    2.44, 4.24, 5.43, 6.96, 8.63, 10.24, 11.97, 13.56, 14.82, 16.28,
    18.22, 20.08, 21.62, 22.92, 24.52, 25.88, 27.07, 28.40, 29.58,
    # Falha (Timeout/503) - Vamos representar como o tempo máximo registrado no log
    30.44 
]

statuses = [
    "Sucesso", "Sucesso", "Sucesso", "Sucesso", "Sucesso", "Sucesso", "Sucesso", "Sucesso", "Sucesso", "Sucesso",
    "Sucesso", "Sucesso", "Sucesso", "Sucesso", "Sucesso", "Sucesso", "Sucesso", "Sucesso", "Sucesso",
    "Falha (Timeout)"
]

# Configuração do Gráfico para Artigo SBC (P&B ou cores sóbrias)
plt.figure(figsize=(10, 6))

# Criar índices para o eixo X (Requisições)
x_pos = np.arange(len(data_points))

# Definir cores: Azul para sucesso, Vermelho para falha
colors = ['#4E79A7' if s == "Sucesso" else '#E15759' for s in statuses]

# Plotar barras
bars = plt.bar(x_pos, data_points, color=colors, edgecolor='black', alpha=0.7)

# Adicionar linha de tendência ou média
avg_time = np.mean([d for i, d in enumerate(data_points) if statuses[i] == "Sucesso"])
plt.axhline(y=avg_time, color='green', linestyle='--', label=f'Tempo Médio (Sucesso): {avg_time:.2f}s')

# Etiquetas e Títulos (Em Português para o Artigo)
plt.ylabel('Tempo de Resposta (s)', fontsize=12)
plt.xlabel('Requisições Concorrentes (ID do Usuário Simulado)', fontsize=12)
plt.title('Desempenho do GitRAG sob Carga (60 Req. Simultâneas)', fontsize=14)

# Legenda personalizada
from matplotlib.patches import Patch
legend_elements = [
    Patch(facecolor='#4E79A7', edgecolor='black', label='Sucesso (200 OK)'),
    Patch(facecolor='#E15759', edgecolor='black', label='Erro (503/Timeout)'),
    plt.Line2D([0], [0], color='green', linestyle='--', label='Média (Sucessos)')
]
plt.legend(handles=legend_elements, loc='upper left')

# Grid para facilitar leitura
plt.grid(axis='y', linestyle='--', alpha=0.5)

# Salvar em alta resolução
plt.tight_layout()
plt.savefig('fig2.png', dpi=300)
print("Gráfico gerado como 'fig2.png'. Faça upload para a pasta images/ do Overleaf.")
plt.show()