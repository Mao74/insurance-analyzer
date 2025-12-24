from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Text, ForeignKey, Enum, Boolean
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
    email = Column(String(255), unique=True, nullable=False, index=True)  # Email as username
    username = Column(String(50), unique=True, nullable=True, index=True)  # Legacy, keep for compatibility
    password_hash = Column(String(255), nullable=False)
    
    # User management fields
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    email_verified = Column(Boolean, default=False)  # For email verification
    access_expires_at = Column(DateTime, nullable=True)  # NULL = never expires
    last_login = Column(DateTime, nullable=True)
    
    # Token tracking
    total_tokens_used = Column(BigInteger, default=0)
    
    # Rate limiting for login
    login_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)  # NULL = not locked
    
    created_at = Column(DateTime, default=datetime.utcnow)
    documents = relationship("Document", back_populates="user")

class PasswordResetToken(Base):
    """Token for password reset requests"""
    __tablename__ = 'password_reset_tokens'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    token = Column(String(255), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User")

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
    
    # Saved Reports / Archive features
    title = Column(String(255), nullable=True) # Custom title for saved reports
    is_saved = Column(Boolean, default=False)  # If True, shows in "Archivio"
    last_updated = Column(DateTime, default=datetime.utcnow) # Track edits
    document = relationship("Document", back_populates="analyses")

