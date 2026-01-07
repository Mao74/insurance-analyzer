from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status, Request
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import json
import os
import re

from ..database import get_db
from ..models import User, ProspectAnalysis, UserAnalysisQuota
from ..services.openapi_client import openapi_client
from ..llm_client import LLMClient # Reusing for PDF generation utility if needed, or just plain string replace

router = APIRouter(prefix="/api/prospect", tags=["prospect"])

# --- SCHEMAS ---
class ProspectSearchRequest(BaseModel):
    piva: str
    mode: str = "advanced" # advanced | full

class BuyQuotaRequest(BaseModel):
    package_type: str # 'prospect_pack'

class UpdateProspectContentRequest(BaseModel):
    html_content: str

class ProspectAnalysisResponse(BaseModel):
    id: int
    piva: str
    company_name: str
    service_type: str
    created_at: datetime
    report_html: str # The full HTML to render
    is_archived: bool

class QuotaResponse(BaseModel):
    year_month: str
    advanced_used: int
    advanced_limit: int
    full_used: int
    full_limit: int

# --- HELPERS ---
def get_current_quota(db: Session, user_id: int) -> UserAnalysisQuota:
    current_month = datetime.utcnow().strftime("%Y-%m")
    quota = db.query(UserAnalysisQuota).filter(
        UserAnalysisQuota.user_id == user_id,
        UserAnalysisQuota.year_month == current_month
    ).first()
    
    if not quota:
        # Initialize quota for this month
        quota = UserAnalysisQuota(
            user_id=user_id,
            year_month=current_month,
            advanced_limit_base=10, # Default from requirements
            full_limit_base=5
        )
        db.add(quota)
        db.commit()
        db.refresh(quota)
    return quota

def check_and_consume_quota(db: Session, user_data: dict, mode: str):
    is_admin = user_data.get("is_admin", False)
    user_id = user_data["id"]
    if is_admin:
        return True # Unlimited for admin

    quota = get_current_quota(db, user_id)
    
    if mode == "advanced":
        limit = quota.advanced_limit_base + quota.advanced_purchased
        if quota.advanced_used >= limit:
            raise HTTPException(status_code=402, detail="Quota Advanced esaurita per questo mese.")
        quota.advanced_used += 1
    elif mode == "full":
        limit = quota.full_limit_base + quota.full_purchased
        if quota.full_used >= limit:
            raise HTTPException(status_code=402, detail="Quota Full esaurita per questo mese.")
        quota.full_used += 1
        
    db.commit()

# --- ROUTES ---

@router.get("/quota", response_model=QuotaResponse)
def get_quota(request: Request, db: Session = Depends(get_db)):
    user_data = request.session.get("user")
    if not user_data: raise HTTPException(status_code=401, detail="Not authenticated")
    quota = get_current_quota(db, user_data["id"])
    return {
        "year_month": quota.year_month,
        "advanced_used": quota.advanced_used,
        "advanced_limit": quota.advanced_limit_base + quota.advanced_purchased,
        "full_used": quota.full_used,
        "full_limit": quota.full_limit_base + quota.full_purchased
    }

@router.post("/buy-quota")
def buy_quota(req: BuyQuotaRequest, request: Request, db: Session = Depends(get_db)):
    user_data = request.session.get("user")
    if not user_data: raise HTTPException(status_code=401, detail="Not authenticated")
    # MOCK implementation - in real app would verify Stripe payment
    if req.package_type == "prospect_pack":
        quota = get_current_quota(db, user_data["id"])
        quota.advanced_purchased += 10
        quota.full_purchased += 5
        db.commit()
        return {"status": "success", "message": "Pacchetto acquistato: +10 Advanced, +5 Full"}
    raise HTTPException(status_code=400, detail="Pacchetto non valido")

@router.post("/analyze", response_model=ProspectAnalysisResponse)
def analyze_prospect(
    req: ProspectSearchRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    user_data = request.session.get("user")
    if not user_data: raise HTTPException(status_code=401, detail="Not authenticated")
    # 1. Validation
    piva = req.piva.strip()
    if not re.match(r"^\d{11}$", piva) and not len(piva) == 16: # Simple check for P.IVA or CF
         raise HTTPException(status_code=400, detail="Formato P.IVA o CF non valido")

    # 2. Check Quota
    check_and_consume_quota(db, user_data, req.mode)

    # 3. Call OpenAPI
    data = openapi_client.get_company_data(piva, req.mode)
    
    if "error" in data:
        # Revert quota consumption if error (optional logic, but friendly)
        # For now we assume quota is consumed only on success or we accept the "cost" of the API call if it returned 404
        # Requirement says: "Non trovata" -> show message. 
        # Ideally we shouldn't burn a quota token for a 404, so let's revert it.
        if not user_data.get("is_admin", False):
            quota = get_current_quota(db, user_data["id"])
            if req.mode == "advanced": quota.advanced_used -= 1
            else: quota.full_used -= 1
            db.commit()
            
        raise HTTPException(status_code=404 if data["error"] == "Company not found" else 500, detail=data["error"])

    # 4. Process Data & Populate Template
    # Load template
    template_path = os.path.join("prompts", "analisi_prospect", "template_prospect.html")
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    # --- POPULATION LOGIC (Simplified for MVP) ---
    # --- POPULATION LOGIC (Updated for New API Schema) ---
    company = data # Data is now the direct company object
    
    # Common replacements
    html = html.replace("[RAGIONE_SOCIALE]", company.get("companyName", "N/D"))
    html = html.replace("[PIVA]", company.get("vatCode", piva))
    html = html.replace("[CODICE_FISCALE]", company.get("taxCode", "N/D"))
    html = html.replace("[CCIAA_REA]", f"{company.get('cciaa', '')} - {company.get('reaCode', '')}")
    
    legal_form = company.get("detailedLegalForm", {})
    html = html.replace("[FORMA_GIURIDICA]", legal_form.get("description", "N/D") if isinstance(legal_form, dict) else "N/D")
    
    html = html.replace("[DATA_COSTITUZIONE]", company.get("registrationDate", "N/D"))
    html = html.replace("[DATA_ANALISI]", datetime.now().strftime("%d/%m/%Y"))
    html = html.replace("[TIPO_SERVIZIO]", req.mode.capitalize())
    
    # Address
    addr_obj = company.get("address", {}).get("registeredOffice", {})
    street = addr_obj.get("streetName", "")
    zip_code = addr_obj.get("zipCode", "")
    town = addr_obj.get("town", "")
    province = addr_obj.get("province", "")
    
    addr_str = f"{street}, {zip_code} {town} ({province})"
    html = html.replace("[INDIRIZZO_SEDE]", addr_str)
    html = html.replace("[INDIRIZZO_ENCODED]", addr_str.replace(" ", "+"))
    
    # Activity
    ateco_obj = company.get("atecoClassification", {}).get("ateco", {})
    html = html.replace("[CODICE_ATECO]", ateco_obj.get("code", "N/D"))
    html = html.replace("[DESCRIZIONE_ATTIVITA]", ateco_obj.get("description", "N/D"))
    
    # Employees (try to find in balance sheets if not at top level)
    # The new schema puts employees inside balance sheets
    balance_sheets = company.get("balanceSheets", {})
    last_balance = balance_sheets.get("last", {})
    employees = last_balance.get("employees", "N/D")
    
    # Sometimes it is at top level or inside 'companySize'? Check schema. 
    # Based on debug: "employees": 11623 inside "last".
    html = html.replace("[NUMERO_DIPENDENTI]", str(employees))
    
    # Contacts
    html = html.replace("[PEC]", company.get("pec", "N/D"))
    html = html.replace("[CODICE_SDI]", company.get("sdiCode", "N/D"))
    
    # Status
    stato = company.get("activityStatus", "ATTIVA")
    html = html.replace("[STATO_ATTIVITA]", stato)
    html = html.replace("[BADGE_CLASS]", "badge-active" if stato == "ATTIVA" else "badge-inactive")

    # Financials (Bilancio Sintetico from 'balanceSheets.all')
    fin_rows = ""
    financials_list = balance_sheets.get("all", []) or []
    # Sort by year desc
    financials_list.sort(key=lambda x: x.get("anno", 0) if x.get("anno") else x.get("year", 0), reverse=True)
    
    last_turnover = "N/D"
    
    for f in financials_list[:5]: # Last 5 years
        year = f.get("year")
        turnover = f.get("turnover", 0) or 0
        emps = f.get("employees", "-") or "-"
        share_cap = f.get("shareCapital", 0) or 0
        profit = f.get("profit", 0) # API might not return 'profit' in this summary list? Debug showed 'netWorth', 'turnover'.
        # Debug JSON showed: turnover, netWorth, shareCapital, totalStaffCost, totalAssets. NO net profit (utile).
        # We might need to map 'netWorth' or find profit elsewhere. Use netWorth (Patrimonio Netto) as proxy for now or 0.
        # Actually standard report asks for Utile. If missing, put 0 or N/D.
        
        row = f"<tr><td>{year}</td><td class='col-curr'>€ {turnover:,}</td><td class='col-center'>{emps}</td><td class='col-curr'>€ {share_cap:,}</td><td class='col-curr'>-</td></tr>"
        fin_rows += row
        if last_turnover == "N/D" and turnover: last_turnover = f"€ {turnover:,}"

    html = html.replace("[ROWS_BILANCIO]", fin_rows)
    html = html.replace("[ULTIMO_FATTURATO]", last_turnover)

    # Governance - Soci (shareHolders)
    soci_rows = ""
    soci = company.get("shareHolders", []) or []
    for s in soci:
        # Schema for shareholders might vary. Assuming logic.
        curr = s.get("currency", "EUR") # Placeholder
        name = s.get("name", "N/D")
        cf = s.get("taxCode", "")
        quote = f"{s.get('sharePercentage', 0)}%"
        soci_rows += f"<tr><td>{name}</td><td>{cf}</td><td>{quote}</td></tr>"
    html = html.replace("[ROWS_SOCI]", soci_rows)
    
    # CLEANUP / FULL MODE LOGIC
    if req.mode == "advanced":
        # Remove Logic Blocks
        html = html.replace("[FULL_CONTACTS_START]", "<!--").replace("[FULL_CONTACTS_END]", "-->")
        html = html.replace("[FULL_BILANCIO_START]", "<!--").replace("[FULL_BILANCIO_END]", "-->")
        html = html.replace("[FULL_GOVERNANCE_START]", "<!--").replace("[FULL_GOVERNANCE_END]", "-->")
    else:
        # FULL Mode - Populate extra fields
        html = html.replace("[FULL_CONTACTS_START]", "").replace("[FULL_CONTACTS_END]", "")
        html = html.replace("[FULL_BILANCIO_START]", "").replace("[FULL_BILANCIO_END]", "")
        html = html.replace("[FULL_GOVERNANCE_START]", "").replace("[FULL_GOVERNANCE_END]", "")
        
        # Phone? Debug didn't show phone. 
        html = html.replace("[TELEFONO]", "N/D") 
        html = html.replace("[SITO_WEB]", "N/D")
        
        # Governance - Amministratori (officers?)
        # Not seen in debug JSON. Assuming empty for now.
        amm_rows = ""
        html = html.replace("[ROWS_AMMINISTRATORI]", amm_rows)
        
        # Detailed Bilancio
        if len(financials_list) >= 2:
            y1 = financials_list[0]
            y2 = financials_list[1]
            
            html = html.replace("[ANNO_N]", str(y1.get('year')))
            html = html.replace("[ANNO_N_1]", str(y2.get('year')))
            
            def fmt(val): return f"€ {val:,}" if val is not None else "-"
            def calc_var(v1, v2):
                if not v2 or v2 == 0 or not v1: return "-"
                diff = ((v1 - v2) / v2) * 100
                return f"{diff:+.1f}%"

            # Turnover
            t1 = y1.get('turnover')
            t2 = y2.get('turnover')
            html = html.replace("[RICAVI_N]", fmt(t1)).replace("[RICAVI_N_1]", fmt(t2))
            html = html.replace("[VAR_RICAVI]", calc_var(t1, t2))
            
            # Others missing in simplified JSON
            html = html.replace("[UTILE_N]", "-").replace("[UTILE_N_1]", "-").replace("[VAR_UTILE]", "-")
            html = html.replace("[EBITDA_N]", "-").replace("[EBITDA_N_1]", "-").replace("[VAR_EBITDA]", "-")
            html = html.replace("[EBIT_N]", "-").replace("[EBIT_N_1]", "-").replace("[VAR_EBIT]", "-")
            
            html = html.replace("[ROE]", "-").replace("[ROI]", "-").replace("[ROS]", "-").replace("[LEVERAGE]", "-")

    # 5. Save to DB
    analysis = ProspectAnalysis(
        user_id=user_data["id"],
        piva=piva,
        company_name=company.get("companyName", "N/D"),
        service_type=req.mode,
        data_json=json.dumps(data),
        report_html=html
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    
    return {
        "id": analysis.id,
        "piva": analysis.piva,
        "company_name": analysis.company_name,
        "service_type": analysis.service_type,
        "created_at": analysis.created_at,
        "report_html": analysis.report_html,
        "is_archived": analysis.is_archived
    }

@router.get("/archive", response_model=List[ProspectAnalysisResponse])
def get_archive(request: Request, db: Session = Depends(get_db)):
    user_data = request.session.get("user")
    if not user_data: raise HTTPException(status_code=401, detail="Not authenticated")
    return db.query(ProspectAnalysis).filter(
        ProspectAnalysis.user_id == user_data["id"],
        ProspectAnalysis.is_archived == True
    ).order_by(ProspectAnalysis.created_at.desc()).all()

@router.put("/archive/{id}")
def archive_analysis(
    id: int, 
    request: Request, 
    title: Optional[str] = None, # Allow renaming on archive
    db: Session = Depends(get_db)
):
    user_data = request.session.get("user")
    if not user_data: raise HTTPException(status_code=401, detail="Not authenticated")
    
    analysis = db.query(ProspectAnalysis).filter(
        ProspectAnalysis.id == id,
        ProspectAnalysis.user_id == user_data["id"]
    ).first()
    if not analysis: raise HTTPException(status_code=404, detail="Analysis not found")
    
    analysis.is_archived = True
    if title:
        analysis.company_name = title # Overwrite company name with user provided title if any
        
    db.commit()
    return {"status": "success", "message": "Archiviata"}

@router.put("/{id}/content")
def update_prospect_content(
    id: int, 
    req: UpdateProspectContentRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    user_data = request.session.get("user")
    if not user_data: raise HTTPException(status_code=401, detail="Not authenticated")
    
    analysis = db.query(ProspectAnalysis).filter(
        ProspectAnalysis.id == id,
        ProspectAnalysis.user_id == user_data["id"]
    ).first()
    
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
        
    analysis.report_html = req.html_content
    db.commit()
    return {"status": "success", "message": "Report aggiornato"}
