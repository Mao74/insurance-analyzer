# Quick reference for adding list analyses endpoint

# Add after line 90 in analysis_routes.py:

@router.get("/", response_model=List[AnalysisResponse])
async def list_analyses(
    request: Request,
    db: Session = Depends(get_db),
    limit: int = 20
):
    """Get list of all analyses for current user (dashboard)"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user_id = user_data.get("id")
    
    # Get all analyses for user, ordered by most recent
    analyses = db.query(models.Analysis).filter(
        models.Analysis.user_id == user_id
    ).order_by(
        models.Analysis.created_at.desc()
    ).limit(limit).all()
    
    return [
        AnalysisResponse(
            analysis_id=a.id,
            status=a.status.value,
            policy_type=a.policy_type,
            analysis_level=a.analysis_level or "base",
            created_at=a.created_at,
            completed_at=a.completed_at,
            report_html=None  # Don't send full HTML in list
        ) for a in analyses
    ]
