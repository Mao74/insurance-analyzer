"""
Password strength validation utility
Implements OWASP password guidelines
"""
import re
from fastapi import HTTPException

# Common weak passwords to block
COMMON_PASSWORDS = {
    "password", "password123", "123456", "12345678", "qwerty", "abc123",
    "monkey", "1234567", "letmein", "trustno1", "dragon", "baseball",
    "iloveyou", "master", "sunshine", "ashley", "bailey", "passw0rd",
    "shadow", "123123", "654321", "superman", "qazwsx", "michael",
    "football", "changeme", "admin", "root", "user", "test"
}

def validate_password_strength(password: str) -> None:
    """
    Validate password strength according to OWASP guidelines.
    
    Raises HTTPException if password is weak.
    
    Requirements:
    - Minimum 12 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 number
    - At least 1 special character
    - Not in common passwords list
    """
    # Check minimum length
    if len(password) < 12:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 12 characters long"
        )
    
    # Check maximum length (prevent DOS)
    if len(password) > 128:
        raise HTTPException(
            status_code=400,
            detail="Password must be less than 128 characters"
        )
    
    # Check uppercase
    if not re.search(r'[A-Z]', password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least one uppercase letter"
        )
    
    # Check lowercase
    if not re.search(r'[a-z]', password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least one lowercase letter"
        )
    
    # Check number
    if not re.search(r'[0-9]', password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least one number"
        )
    
    # Check special character
    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};:,.<>?/\\|`~]', password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least one special character (!@#$%^&*...)"
        )
    
    # Check against common passwords
    if password.lower() in COMMON_PASSWORDS:
        raise HTTPException(
            status_code=400,
            detail="This password is too common. Please choose a stronger password"
        )
    
    # All checks passed
    return None


def get_password_strength_score(password: str) -> dict:
    """
    Calculate password strength score (0-100) for UI feedback.
    Returns dict with score and feedback message.
    """
    score = 0
    feedback = []
    
    # Length score (0-40 points)
    if len(password) >= 12:
        score += 20
    if len(password) >= 16:
        score += 10
    if len(password) >= 20:
        score += 10
    else:
        feedback.append(f"Use at least 12 characters (current: {len(password)})")
    
    # Complexity score (0-40 points)
    if re.search(r'[A-Z]', password):
        score += 10
    else:
        feedback.append("Add uppercase letters")
        
    if re.search(r'[a-z]', password):
        score += 10
    else:
        feedback.append("Add lowercase letters")
        
    if re.search(r'[0-9]', password):
        score += 10
    else:
        feedback.append("Add numbers")
        
    if re.search(r'[!@#$%^&*()_+\-=\[\]{};:,.<>?/\\|`~]', password):
        score += 10
    else:
        feedback.append("Add special characters")
    
    # Uniqueness score (0-20 points)
    if password.lower() not in COMMON_PASSWORDS:
        score += 20
    else:
        feedback.append("Avoid common passwords")
    
    # Determine strength level
    if score >= 80:
        strength = "Strong"
    elif score >= 60:
        strength = "Good"
    elif score >= 40:
        strength = "Fair"
    else:
        strength = "Weak"
    
    return {
        "score": score,
        "strength": strength,
        "feedback": feedback
    }
