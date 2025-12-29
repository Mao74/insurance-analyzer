import json

def mask_document(text: str, sensitive_data: dict) -> tuple[str, list[dict], dict]:
    """
    Sostituzione letterale, nessuna ricerca di varianti.
    L'utente inserisce i dati ESATTAMENTE come appaiono nel documento.
    
    sensitive_data = {
        'numero_polizza': '123456789',
        'contraente': 'Mario Rossi S.r.l.',
        'partita_iva': '12345678901',
        'codice_fiscale': 'RSSMRA80A01H501Z',
        'assicurato': 'Mario Rossi',
        'altri': ['Via Roma 15', 'info@azienda.it']
    }
    
    Ritorna:
    - testo_mascherato: testo con placeholder
    - lista_sostituzioni: per mostrare all'utente cosa è stato sostituito
    - reverse_mapping: dizionario {placeholder: valore_originale} per ripopolamento
    """
    import re
    
    replacements = []
    reverse_mapping = {}  # mask -> originale
    masked = text
    
    field_masks = {
        'numero_polizza': '[POLIZZA_XXX]',
        'contraente': '[CONTRAENTE_XXX]',
        'partita_iva': '[PIVA_XXX]',
        'codice_fiscale': '[CF_XXX]',
        'assicurato': '[ASSICURATO_XXX]',
        'indirizzo': '[INDIRIZZO_XXX]',
        'citta': '[CITTA_XXX]',
        'cap': '[CAP_XXX]'
    }
    
    for field, mask in field_masks.items():
        value = sensitive_data.get(field, '').strip()
        if value:
            # Escape regex characters in value
            pattern = re.escape(value)
            # Find all occurrences (case insensitive)
            flag = re.IGNORECASE
            
            # Count occurrences before replacement
            count = len(re.findall(pattern, masked, flags=flag))
            
            if count > 0:
                # Perform replacement
                masked = re.sub(pattern, mask, masked, flags=flag)
                reverse_mapping[mask] = value
                replacements.append({
                    'campo': field,
                    'originale': value,
                    'mascherato': mask,
                    'occorrenze': count
                })
    
    # Altri dati custom
    altri = sensitive_data.get('altri', [])
    if isinstance(altri, str): # Handle if passed as string
         altri = [altri]
         
    for i, dato in enumerate(altri, 1):
        dato = dato.strip()
        if dato:
            mask = f'[DATO_OSCURATO_{i}]'
            pattern = re.escape(dato)
            count = len(re.findall(pattern, masked, flags=re.IGNORECASE))
            
            if count > 0:
                masked = re.sub(pattern, mask, masked, flags=re.IGNORECASE)
                reverse_mapping[mask] = dato
                replacements.append({
                    'campo': f'altro_{i}',
                    'originale': dato,
                    'mascherato': mask,
                    'occorrenze': count
                })
    
    return masked, replacements, reverse_mapping


def repopulate_report(report_html: str, reverse_mapping: dict) -> str:
    """
    Sostituisce i placeholder mascherati con i dati originali nel report finale.
    Da chiamare DOPO aver ricevuto la risposta dall'LLM, PRIMA di mostrare all'utente.
    
    Args:
        report_html: HTML del report con placeholder [CONTRAENTE_XXX], ecc.
        reverse_mapping: dizionario {placeholder: valore_originale}
    
    Returns:
        HTML del report con i dati reali ripristinati
    """
    repopulated = report_html
    
    if not reverse_mapping:
         return report_html

    for mask, original in reverse_mapping.items():
        repopulated = repopulated.replace(mask, original)
    
    return repopulated


def serialize_mapping(reverse_mapping: dict) -> str:
    """Serializza il mapping per storage in DB"""
    return json.dumps(reverse_mapping, ensure_ascii=False)


def deserialize_mapping(mapping_json: str) -> dict:
    """Deserializza il mapping dal DB"""
    if not mapping_json:
        return {}
    if isinstance(mapping_json, dict):
        return mapping_json
    return json.loads(mapping_json)
