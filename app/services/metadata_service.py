# CÓDIGO COMPLETO PARA: app/services/metadata_service.py
import os
from sqlalchemy import create_engine, Column, String, Text, Integer, MetaData, Table, DateTime
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from typing import List, Dict, Any

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("Variável de ambiente DATABASE_URL não definida.")

# --- INÍCIO DA CORREÇÃO (NameError) ---

# 1. Define a variável 'db_url' a partir da string de conexão
db_url = make_url(DATABASE_URL)

# 2. Modifica a 'db_url' para adicionar o sslmode=require (necessário para o Supabase Pooler)
# Esta é a linha que estava falhando antes porque a Linha 1 estava faltando.
db_url = db_url.set(query={"sslmode": "require"})

# 3. Cria o engine com a URL final e corrigida
engine = create_engine(db_url)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

# Nosso modelo de tabela de documentos
class Document(Base):
    __tablename__ = "documents"
    
    id = Column(String, primary_key=True, index=True) # O ID do chunk (ex: "issue_123_chunk_0")
    repo_name = Column(String, index=True, nullable=False)
    doc_type = Column(String, index=True) # "issue", "commit", "pull_request"
    doc_id = Column(String) # ID original (ex: "123" ou o SHA)
    title = Column(Text)
    text_content = Column(Text) # O texto completo do chunk
    author = Column(String)
    url = Column(String)
    created_at = Column(DateTime, index=True) # A coluna crucial para ordenação

def init_db():
    """Cria a tabela no banco de dados se ela não existir."""
    Base.metadata.create_all(bind=engine)

class MetadataService:
    """
    Serviço para interagir com o banco de dados SQL de metadados.
    """
    def __init__(self):
        self.db = SessionLocal()

    def add_documents(self, documents: List[Dict[str, Any]]):
        """
        Adiciona ou atualiza metadados de documentos no banco SQL.
        """
        print(f"[MetadataService] Adicionando {len(documents)} metadados ao SQL DB...")
        try:
            for doc in documents:
                meta = doc.get("metadata", {})
                
                # Cria o objeto Document com base nos metadados do chunk
                db_doc = Document(
                    id=doc.get("id"),
                    repo_name=meta.get("repo_name"),
                    doc_type=meta.get("type"),
                    doc_id=str(meta.get("id") or meta.get("sha")),
                    title=meta.get("title"),
                    text_content=doc.get("text"), # Salvamos o texto aqui também
                    author=meta.get("author"),
                    url=meta.get("url"),
                    created_at=meta.get("created_at") or meta.get("date") # Usa 'date' para commits
                )
                
                # Faz um 'merge' (upsert)
                self.db.merge(db_doc)
            
            self.db.commit()
            print("[MetadataService] Metadados salvos no SQL DB com sucesso.")
        except Exception as e:
            self.db.rollback()
            print(f"[MetadataService] Erro ao salvar no SQL DB: {e}")
            raise
        finally:
            self.db.close()

    def find_document_by_date(self, repo_name: str, doc_type: str, order: str = "desc") -> List[Dict[str, Any]]:
        """
        Busca um documento por data (para consultas cronológicas).
        """
        print(f"[MetadataService] Buscando SQL por: {doc_type}, ordem: {order}")
        try:
            query = self.db.query(Document).filter(
                Document.repo_name == repo_name,
                Document.doc_type == doc_type
            )
            
            if order == "desc":
                query = query.order_by(Document.created_at.desc())
            else:
                query = query.order_by(Document.created_at.asc())
            
            # Pega o documento mais recente/antigo
            result = query.first()
            
            if not result:
                return []
                
            # Formata o resultado de volta para o formato que a LLM espera
            return [{
                "text": result.text_content,
                "metadata": {
                    "type": result.doc_type,
                    "id": result.doc_id,
                    "title": result.title,
                    "author": result.author,
                    "url": result.url,
                    "date": result.created_at.isoformat() if result.created_at else None,
                    "created_at": result.created_at.isoformat() if result.created_at else None
                }
            }]
        except Exception as e:
            print(f"[MetadataService] Erro ao buscar no SQL DB: {e}")
            return []
        finally:
            self.db.close()

# Chama init_db() quando o módulo é importado pela primeira vez
init_db()