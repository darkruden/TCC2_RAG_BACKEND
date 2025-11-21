# Arquitetura do Sistema – GitRAG

Este documento descreve a arquitetura de alto nível, os principais componentes e o fluxo de dados do GitRAG.

## 1. Visão Geral

O GitRAG é uma plataforma de análise de engenharia de software baseada em **RAG (Retrieval-Augmented Generation)**.  
Diferente de APIs REST tradicionais apenas orientadas a recursos (CRUD), este backend opera como um **Sistema Baseado em Intenções**, onde um modelo de linguagem decide qual serviço interno será acionado a partir de um prompt em linguagem natural.

### 1.1. Repositórios do Projeto

- Backend (FastAPI + RAG):  
  https://github.com/darkruden/TCC2_RAG_BACKEND
- Frontend (Extensão Chrome – Side Panel):  
  https://github.com/darkruden/TCC2_RAG_FRONTEND

### 1.2. Principais Componentes

- **API Gateway (FastAPI)**  
  Ponto de entrada único da aplicação (`/api/chat` e demais endpoints).  
  Responsável por validação básica das requisições e roteamento, sem conter lógica de negócio pesada.

- **Intent Router (LLMService)**  
  “Cérebro” do sistema. Analisa o prompt do usuário e classifica a intenção (ex.: `QUERY`, `INGEST`, `REPORT`, `SCHEDULE`), disparando a combinação de serviços adequada.

- **Worker Assíncrono (RQ + Redis)**  
  Processa tarefas de longa duração (ingestão de repositórios, geração e envio de relatórios) sem bloquear as respostas síncronas da API.

- **Camada de Dados (Supabase / PostgreSQL + PGVector)**  
  Armazenamento híbrido com:
  - Dados relacionais (usuários, agendamentos, metadados).
  - Dados vetoriais (embeddings de código e textos) usando `pgvector`.

---

## 2. Fluxo de Intenção (High-Level)

```mermaid
graph TD
    User[Usuário (Frontend)] -->|Prompt + Arquivo| API[FastAPI (/api/chat)]
    API --> Router[LLM Intent Router]

    Router -->|Query Simples| Stream[Streaming Response]
    Router -->|Tarefa Pesada| Queue[Redis Queue]

    Stream -->|Chunks| User

    Queue --> Worker[Python Worker]
    Worker -->|Ingestão| Github[GitHub API]
    Worker -->|Relatório| Email[Serviço de Email]
    Worker -->|Persistência| DB[(Supabase + PGVector)]
```

### 2.1. Descrição do Fluxo

1. O **Frontend** envia um prompt (e opcionalmente arquivos) para o backend (FastAPI).
2. O endpoint `/api/chat` encaminha o pedido ao **LLM Intent Router**.
3. O router decide:
   - Se a intenção é rápida (ex.: consulta simples), responde via **Streaming** diretamente.
   - Se a intenção envolve processamento pesado (ex.: ingestão de repositórios, criação de relatórios), enfileira no **Redis** para ser processada pelo **Worker**.
4. O **Worker**:
   - Consulta a **GitHub API** (ingestão/atualização).
   - Gera relatórios (Markdown/HTML) e envia via serviço de email.
   - Salva documentos e embeddings no banco (Supabase + PGVector).

---

## 3. Serviços e Responsabilidades

### 3.1. Core Services

- **LLMService**
  - Encapsula chamadas ao modelo de IA.
  - Implementa Function Calling para:
    - Classificar intenções (`QUERY`, `INGEST`, `REPORT`, `SCHEDULE`).
    - Disparar ferramentas especializadas (RAG, ingestão, geração de relatório, etc.).

- **RAGService**
  - Orquestra a busca vetorial.
  - Gera embeddings da consulta, recupera documentos relevantes no PGVector e monta o contexto para o LLM responder de forma contextualizada.

- **SchedulerService**
  - Gerencia agendamentos de relatórios.
  - Normaliza janelas de tempo (`data_inicio`, `data_fim`) para UTC.
  - Garante que relatórios recorrentes sejam disparados na frequência correta.

### 3.2. Serviços de Infraestrutura

- **EmbeddingService**
  - Gera embeddings (por exemplo, `text-embedding-3-small`) para:
    - Indexação de commits, issues, PRs e arquivos.
    - Consultas semânticas.

- **GithubService**
  - Cliente especializado da **GitHub REST/GraphQL API**.
  - Implementa delta pull (busca apenas o que mudou desde a última ingestão) para evitar reprocessamento desnecessário.

- **ReportService**
  - Gera relatórios em **Markdown/HTML** usando templates.
  - Pode usar ferramentas para embutir estilos em HTML antes do envio por email.

---

## 4. Padrões de Design

- **Router Pattern**
  - O endpoint `/api/chat` é agnóstico da regra de negócio.
  - A responsabilidade de “decidir o que fazer” é delegada para a IA via LLMService/Intent Router.

- **Dependency Injection**
  - Serviços (RAGService, EmbeddingService, GithubService, etc.) são instanciados em `main.py` e injetados nas rotas via FastAPI.

- **Assynchronous Processing**
  - Tarefas com tempo de execução potencialmente longo são enfileiradas no Redis e processadas por workers RQ.

- **Multi-Tenancy**
  - Dados isolados por `user_id` / chave de API.
  - Facilita uso por múltiplos times/organizações com o mesmo backend.

---

## 5. Banco de Dados (Schema Lógico)

Principais tabelas/coleções:

- **documentos**
  - Armazena chunks de código, texto e seus respectivos embeddings (vetores).
  - Campos principais:
    - `id`, `user_id`, `repo`, `path`, `conteudo_chunk`, `embedding`, `created_at`.

- **agendamentos**
  - Registra configurações de relatórios recorrentes.
  - Campos principais:
    - `id`, `user_id`, `frequencia`, `data_inicio`, `data_fim`, `timezone`, `ativo`.

- **usuarios**
  - Controle de acesso e chaves de API.
  - Campos principais:
    - `id`, `email`, `nome`, `api_key_hash`, `created_at`.

---

## 6. Integração com o Frontend

O frontend (Extensão Chrome) se comunica com o backend via HTTP/HTTPS:

- Envia prompts e contexto (repositório selecionado, arquivo em foco, filtros de data).
- Configura e visualiza agendamentos de relatórios.
- Consome respostas em **streaming** para o chat.

Repositório do frontend:  
https://github.com/darkruden/TCC2_RAG_FRONTEND
