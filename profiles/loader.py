from profiles.tax.tax_profile import TAX_PROFILE
from profiles.legal.legal_profile import LEGAL_PROFILE

PROFILE_REGISTRY = {
    "tax": TAX_PROFILE,
    "legal": LEGAL_PROFILE,
}


def load_profile(profile_name: str):

    profile = profile_name.lower().strip()
    
    if profile not in PROFILE_REGISTRY:
        raise ValueError(f"Profile '{profile_name}' not found.")
    
    return PROFILE_REGISTRY[profile]