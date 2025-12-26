"""
Stripe API routes for subscription management
"""
from fastapi import APIRouter, Request, HTTPException, status, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from ..database import get_db
from .. import models
from ..config import settings
from .. import stripe_service

router = APIRouter()


# Request/Response Models

class CreateCheckoutRequest(BaseModel):
    price_type: str  # "monthly" or "annual"

class CheckoutResponse(BaseModel):
    success: bool
    checkout_url: Optional[str] = None
    error: Optional[str] = None

class PortalResponse(BaseModel):
    success: bool
    portal_url: Optional[str] = None
    error: Optional[str] = None

class SubscriptionStatusResponse(BaseModel):
    has_subscription: bool
    status: Optional[str] = None
    plan: Optional[str] = None
    expires_at: Optional[datetime] = None


# Helper function to get current user
def get_current_user(request: Request, db: Session):
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    user = db.query(models.User).filter(models.User.id == user_data["id"]).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    return user


# Routes

@router.post("/create-checkout", response_model=CheckoutResponse)
async def create_checkout(
    request: Request,
    payload: CreateCheckoutRequest,
    db: Session = Depends(get_db)
):
    """Create a Stripe Checkout session for subscription"""
    user = get_current_user(request, db)
    
    # Determine price ID based on type
    if payload.price_type == "monthly":
        price_id = settings.STRIPE_PRICE_MONTHLY
    elif payload.price_type == "annual":
        price_id = settings.STRIPE_PRICE_ANNUAL
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid price type. Use 'monthly' or 'annual'"
        )
    
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stripe price not configured"
        )
    
    result = stripe_service.create_checkout_session(
        user_id=user.id,
        user_email=user.email,
        price_id=price_id,
        success_url=f"{settings.APP_URL}/settings?payment=success",
        cancel_url=f"{settings.APP_URL}/settings?payment=canceled",
        stripe_customer_id=user.stripe_customer_id
    )
    
    if result["success"]:
        return CheckoutResponse(success=True, checkout_url=result["checkout_url"])
    else:
        return CheckoutResponse(success=False, error=result.get("error", "Unknown error"))


@router.post("/customer-portal", response_model=PortalResponse)
async def customer_portal(
    request: Request,
    db: Session = Depends(get_db)
):
    """Get Stripe Customer Portal URL for subscription management"""
    user = get_current_user(request, db)
    
    if not user.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No subscription found"
        )
    
    result = stripe_service.create_customer_portal_session(
        stripe_customer_id=user.stripe_customer_id,
        return_url=f"{settings.APP_URL}/settings"
    )
    
    if result["success"]:
        return PortalResponse(success=True, portal_url=result["portal_url"])
    else:
        return PortalResponse(success=False, error=result.get("error", "Unknown error"))


@router.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def subscription_status(
    request: Request,
    db: Session = Depends(get_db)
):
    """Get current user's subscription status"""
    user = get_current_user(request, db)
    
    # If no subscription, return empty
    if not user.stripe_subscription_id or not user.subscription_status:
        return SubscriptionStatusResponse(
            has_subscription=False,
            status=None,
            plan=None,
            expires_at=user.access_expires_at
        )
    
    # Return subscription info from database
    # (Stripe webhook keeps this updated)
    return SubscriptionStatusResponse(
        has_subscription=True,
        status=user.subscription_status,
        plan="active",  # Plan details can be fetched separately if needed
        expires_at=user.access_expires_at
    )


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Stripe webhook events"""
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    
    # Verify webhook signature
    result = stripe_service.verify_webhook_signature(payload, signature)
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature"
        )
    
    event = result["event"]
    event_type = event["type"]
    data = event["data"]["object"]
    
    print(f"[STRIPE WEBHOOK] Received event: {event_type}")
    
    # Handle different event types
    if event_type == "checkout.session.completed":
        # Payment successful, activate subscription
        user_id = data.get("metadata", {}).get("user_id")
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")
        
        if user_id and subscription_id:
            user = db.query(models.User).filter(models.User.id == int(user_id)).first()
            if user:
                user.stripe_customer_id = customer_id
                user.stripe_subscription_id = subscription_id
                user.subscription_status = "active"
                
                # Get subscription details to set real expiry date
                import stripe
                stripe.api_key = settings.STRIPE_SECRET_KEY
                try:
                    subscription = stripe.Subscription.retrieve(subscription_id)
                    user.access_expires_at = datetime.fromtimestamp(subscription.current_period_end)
                except Exception as e:
                    print(f"[STRIPE] Error getting subscription details: {e}")
                    # Fallback to 1 month from now
                    from datetime import timedelta
                    user.access_expires_at = datetime.utcnow() + timedelta(days=30)
                
                db.commit()
                print(f"[STRIPE] Activated subscription for user {user.email} until {user.access_expires_at}")
    
    elif event_type == "invoice.paid":
        # Recurring payment successful
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")
        
        user = db.query(models.User).filter(models.User.stripe_customer_id == customer_id).first()
        if user:
            user.subscription_status = "active"
            
            # Get subscription details to set real expiry date
            if subscription_id:
                import stripe
                stripe.api_key = settings.STRIPE_SECRET_KEY
                try:
                    subscription = stripe.Subscription.retrieve(subscription_id)
                    user.access_expires_at = datetime.fromtimestamp(subscription.current_period_end)
                except Exception as e:
                    print(f"[STRIPE] Error getting subscription details: {e}")
            
            db.commit()
            print(f"[STRIPE] Invoice paid for user {user.email} until {user.access_expires_at}")
    
    elif event_type == "customer.subscription.updated":
        # Subscription status changed
        customer_id = data.get("customer")
        subscription_status = data.get("status")
        
        user = db.query(models.User).filter(models.User.stripe_customer_id == customer_id).first()
        if user:
            user.subscription_status = subscription_status
            if subscription_status in ["canceled", "unpaid", "past_due"]:
                # Set expiry to end of current period
                current_period_end = data.get("current_period_end")
                if current_period_end:
                    user.access_expires_at = datetime.fromtimestamp(current_period_end)
            db.commit()
            print(f"[STRIPE] Subscription updated for user {user.email}: {subscription_status}")
    
    elif event_type == "customer.subscription.deleted":
        # Subscription canceled/ended
        customer_id = data.get("customer")
        user = db.query(models.User).filter(models.User.stripe_customer_id == customer_id).first()
        if user:
            user.subscription_status = "canceled"
            user.stripe_subscription_id = None
            # Keep access until current period end (already set by update event)
            db.commit()
            print(f"[STRIPE] Subscription deleted for user {user.email}")
    
    return {"received": True}


@router.get("/prices")
async def get_prices():
    """Get available subscription prices (public endpoint)"""
    return {
        "monthly": {
            "price_id": settings.STRIPE_PRICE_MONTHLY,
            "amount": 4900,  # in cents
            "currency": "eur",
            "interval": "month",
            "display": "€49/mese"
        },
        "annual": {
            "price_id": settings.STRIPE_PRICE_ANNUAL,
            "amount": 47000,  # in cents
            "currency": "eur",
            "interval": "year",
            "display": "€470/anno",
            "savings": "Risparmia ~€118/anno"
        }
    }
