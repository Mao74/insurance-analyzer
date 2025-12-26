"""
Stripe service for subscription management
"""
import stripe
from datetime import datetime, timedelta
from .config import settings


def init_stripe():
    """Initialize Stripe with API key"""
    stripe.api_key = settings.STRIPE_SECRET_KEY


def create_checkout_session(
    user_id: int,
    user_email: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    stripe_customer_id: str = None
) -> dict:
    """
    Create a Stripe Checkout session for subscription
    Returns the checkout session URL
    """
    init_stripe()
    
    try:
        session_params = {
            "payment_method_types": ["card"],
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": {"user_id": str(user_id)},
            "subscription_data": {
                "metadata": {"user_id": str(user_id)}
            }
        }
        
        # If user already has a Stripe customer ID, use it
        if stripe_customer_id:
            session_params["customer"] = stripe_customer_id
        else:
            session_params["customer_email"] = user_email
        
        session = stripe.checkout.Session.create(**session_params)
        
        return {
            "success": True,
            "checkout_url": session.url,
            "session_id": session.id
        }
        
    except stripe.error.StripeError as e:
        print(f"[STRIPE] Error creating checkout session: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def create_customer_portal_session(stripe_customer_id: str, return_url: str) -> dict:
    """
    Create a Stripe Customer Portal session for subscription management
    """
    init_stripe()
    
    try:
        session = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=return_url
        )
        
        return {
            "success": True,
            "portal_url": session.url
        }
        
    except stripe.error.StripeError as e:
        print(f"[STRIPE] Error creating customer portal session: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def verify_webhook_signature(payload: bytes, signature: str) -> dict:
    """
    Verify Stripe webhook signature and return the event
    """
    init_stripe()
    
    try:
        event = stripe.Webhook.construct_event(
            payload,
            signature,
            settings.STRIPE_WEBHOOK_SECRET
        )
        return {"success": True, "event": event}
        
    except stripe.error.SignatureVerificationError as e:
        print(f"[STRIPE] Webhook signature verification failed: {e}")
        return {"success": False, "error": str(e)}


def get_subscription_details(subscription_id: str) -> dict:
    """
    Get details of a subscription
    """
    init_stripe()
    
    try:
        subscription = stripe.Subscription.retrieve(subscription_id)
        return {
            "success": True,
            "subscription": subscription,
            "status": subscription.status,
            "current_period_end": datetime.fromtimestamp(subscription.current_period_end)
        }
    except stripe.error.StripeError as e:
        print(f"[STRIPE] Error getting subscription: {e}")
        return {"success": False, "error": str(e)}


def cancel_subscription(subscription_id: str, at_period_end: bool = True) -> dict:
    """
    Cancel a subscription (optionally at end of billing period)
    """
    init_stripe()
    
    try:
        if at_period_end:
            subscription = stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=True
            )
        else:
            subscription = stripe.Subscription.delete(subscription_id)
        
        return {"success": True, "subscription": subscription}
        
    except stripe.error.StripeError as e:
        print(f"[STRIPE] Error canceling subscription: {e}")
        return {"success": False, "error": str(e)}
