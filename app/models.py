from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Enum, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from .database import Base

class AnalysisStatus(enum.Enum):
    UPLOADED = "uploaded"
    CONVERTED = "converted"
    MASKED = "masked"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    ERROR = "error"

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    documents = relationship("Document", back_populates="user")

class Document(Base):
    __tablename__ = 'documents'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False)  # UUID-based
    ramo = Column(String(50), nullable=False)
    ocr_method = Column(String(20))  # nativo, ocr_doctr, ocr_tesseract
    extracted_text_path = Column(String(255))  # Path al file TXT estratto
    token_count = Column(Integer, default=0)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User", back_populates="documents")
    analyses = relationship("Analysis", back_populates="document")

class Analysis(Base):
    __tablename__ = 'analyses'
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey('documents.id'), nullable=True) # Nullable for multi-doc
    source_document_ids = Column(Text) # JSON list of IDs e.g. "[1, 2]"
    status = Column(Enum(AnalysisStatus), default=AnalysisStatus.UPLOADED)
    policy_type = Column(String(50), default="rc_generale") # rc_generale, incendio, trasporti
    prompt_level = Column(String(20))  # base, avanzato
    llm_model = Column(String(50))
    total_tokens = Column(Integer, default=0)
    masked_text_path = Column(String(255))  # Path al testo mascherato
    masking_skipped = Column(Boolean, default=False)  # True se utente ha saltato
    reverse_mapping_json = Column(Text)  # JSON {placeholder: valore_originale}
    report_html_masked = Column(Text)    # Report con placeholder (storage sicuro)
    report_html_display = Column(Text)   # Report con dati reali (visualizzazione)
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    document = relationship("Document", back_populates="analyses")
