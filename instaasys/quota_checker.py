# instaasys/quota_checker.py

"""
API Quota Checker - Check API status before generation
"""

import logging
from django.conf import settings
from instaasys.ai_service import get_provider_status

logger = logging.getLogger(__name__)


def check_api_quotas():
    """
    Check the status of all AI and image generation APIs.
    
    Returns a dict with:
        - 'status': 'ok', 'warning', or 'critical'
        - 'ai_providers': list of AI provider statuses
        - 'image_providers': list of image provider statuses
        - 'warnings': list of warning messages
        - 'can_generate': boolean indicating if generation is possible
    """
    result = {
        'status': 'ok',
        'ai_providers': [],
        'image_providers': [],
        'warnings': [],
        'can_generate': True
    }
    
    # Check AI providers (for text generation)
    ai_status = get_provider_status()
    available_ai = 0
    
    for provider in ai_status:
        status_info = {
            'name': provider['name'].title(),
            'model': provider['model'],
            'available': provider['available'],
            'status_text': 'Available' if provider['available'] else f"Cooldown ({provider['cooldown_remaining_seconds']}s)",
            'icon': '✅' if provider['available'] else '⏳'
        }
        result['ai_providers'].append(status_info)
        
        if provider['available']:
            available_ai += 1
    
    # Check image providers
    nano_token = getattr(settings, 'NANO_BANANA_TOKEN', '')
    pexels_key = getattr(settings, 'PEXELS_API_KEY', '')
    unsplash_key = getattr(settings, 'UNSPLASH_ACCESS_KEY', '')
    
    available_image = 0
    
    # Nano Banana
    if nano_token:
        # Quick test to see if Nano Banana is working
        nano_status = _test_nano_banana_quick()
        result['image_providers'].append({
            'name': 'Nano Banana (AI)',
            'available': nano_status['available'],
            'status_text': nano_status['message'],
            'icon': '🤖' if nano_status['available'] else '❌',
            'priority': 1
        })
        if nano_status['available']:
            available_image += 1
        elif nano_status['quota_exhausted']:
            result['warnings'].append({
                'type': 'warning',
                'provider': 'Nano Banana',
                'message': 'AI image generation quota exhausted. Will use stock photos instead.'
            })
    
    # Pexels
    if pexels_key:
        result['image_providers'].append({
            'name': 'Pexels',
            'available': True,
            'status_text': 'Available',
            'icon': '📸',
            'priority': 2
        })
        available_image += 1
    
    # Unsplash
    if unsplash_key:
        result['image_providers'].append({
            'name': 'Unsplash',
            'available': True,
            'status_text': 'Available',
            'icon': '📸',
            'priority': 3
        })
        available_image += 1
    
    # Wikimedia (always available)
    result['image_providers'].append({
        'name': 'Wikimedia Commons',
        'available': True,
        'status_text': 'Available (lower quality)',
        'icon': '🌐',
        'priority': 4
    })
    available_image += 1
    
    # Determine overall status
    if available_ai == 0:
        result['status'] = 'critical'
        result['can_generate'] = False
        result['warnings'].append({
            'type': 'error',
            'provider': 'AI Text Generation',
            'message': 'All AI providers are unavailable. Cannot generate lessons. Please wait or check API keys.'
        })
    elif available_ai == 1:
        result['status'] = 'warning'
        result['warnings'].append({
            'type': 'warning',
            'provider': 'AI Text Generation',
            'message': f'Only 1 AI provider available. Generation may be slower if it fails.'
        })
    
    if available_image == 1:  # Only Wikimedia
        if not result['warnings']:
            result['status'] = 'warning'
        result['warnings'].append({
            'type': 'info',
            'provider': 'Image Generation',
            'message': 'Only Wikimedia available for images. Image quality may be lower.'
        })
    
    return result


def _test_nano_banana_quick():
    """Quick test of Nano Banana API without actually generating an image."""
    nano_token = getattr(settings, 'NANO_BANANA_TOKEN', '')
    
    if not nano_token:
        return {'available': False, 'message': 'Not configured', 'quota_exhausted': False}
    
    try:
        import requests
        # Just test the endpoint with a minimal request
        url = "https://api.laozhang.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {nano_token}",
            "Content-Type": "application/json"
        }
        
        # Minimal test payload
        payload = {
            "model": "gemini-3.1-flash-image-preview",
            "stream": False,
            "messages": [{"role": "user", "content": "test"}]
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        
        if response.status_code == 200:
            return {'available': True, 'message': 'Available', 'quota_exhausted': False}
        elif response.status_code == 403:
            # Check if it's a quota issue
            try:
                error_data = response.json()
                if 'insufficient_user_quota' in str(error_data):
                    return {
                        'available': False,
                        'message': 'Quota exhausted',
                        'quota_exhausted': True
                    }
            except:
                pass
            return {'available': False, 'message': 'Access denied', 'quota_exhausted': False}
        else:
            return {'available': False, 'message': f'Error ({response.status_code})', 'quota_exhausted': False}
            
    except requests.exceptions.Timeout:
        return {'available': False, 'message': 'Timeout', 'quota_exhausted': False}
    except Exception as e:
        logger.debug(f"Nano Banana quick test failed: {e}")
        return {'available': False, 'message': 'Connection failed', 'quota_exhausted': False}


def get_quota_summary_html():
    """
    Generate HTML summary of API quotas for display in templates.
    Returns HTML string.
    """
    status = check_api_quotas()
    
    if status['status'] == 'ok':
        badge_class = 'success'
        badge_text = 'All Systems Operational'
        icon = '✅'
    elif status['status'] == 'warning':
        badge_class = 'warning'
        badge_text = 'Limited Availability'
        icon = '⚠️'
    else:
        badge_class = 'danger'
        badge_text = 'Service Unavailable'
        icon = '❌'
    
    html = f'<span class="badge bg-{badge_class}">{icon} {badge_text}</span>'
    return html
