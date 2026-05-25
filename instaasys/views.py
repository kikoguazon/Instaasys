import json
from django.http import JsonResponse
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from instaasys import ai_service
from instaasys.theme_config import THEME_CONFIG, get_theme_for_user, get_semantic_tokens, get_theme_metadata_for_ai


@staff_member_required
def ai_status(request):
    """
    Admin-only endpoint that returns a live snapshot of AI provider health.

    GET /api/ai-status/
    Response:
    {
        "providers": [
            {
                "name": "groq",
                "model": "llama-3.3-70b-versatile",
                "available": true,
                "cooldown_remaining_seconds": 0,
                "total_calls": 42,
                "total_errors": 1
            },
            ...
        ]
    }
    """
    return JsonResponse({"providers": ai_service.get_provider_status()})


@staff_member_required
def quota_status(request):
    """
    Admin-only endpoint that returns comprehensive API quota status.
    
    GET /api/quota-status/
    Response:
    {
        "status": "ok|warning|critical",
        "can_generate": true|false,
        "ai_providers": [...],
        "image_providers": [...],
        "warnings": [...]
    }
    """
    from instaasys.quota_checker import check_api_quotas
    
    try:
        quota_status = check_api_quotas()
        return JsonResponse(quota_status)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'error': str(e),
            'can_generate': True  # Allow generation even if check fails
        }, status=500)


@login_required
def theme_config_api(request):
    """
    Get current user's theme configuration and semantic token definitions.
    
    Used by:
    - Frontend for theme context
    - AI systems for design system understanding
    - Mobile apps for consistent theming
    
    GET /api/theme-config/
    Response:
    {
        "current_theme": "light" | "dark" | "system",
        "effective_theme": "light" | "dark",
        "semantic_tokens": { ... },
        "wcag_compliance": { ... },
        "ai_context": { ... }
    }
    """
    theme_pref = getattr(request.user, 'theme_preference', 'system')
    effective_theme = theme_pref if theme_pref in ['light', 'dark'] else 'light'
    
    return JsonResponse({
        'status': 'success',
        'current_theme_preference': theme_pref,
        'effective_theme': effective_theme,
        'semantic_tokens': get_semantic_tokens(effective_theme),
        'available_themes': list(THEME_CONFIG['themes'].keys()),
        'ai_context': get_theme_metadata_for_ai(),
    })


@require_http_methods(["POST"])
@login_required
def user_theme_preference(request):
    """
    Save user's theme preference to database.
    
    POST /api/user/theme-preference/
    Content-Type: application/json
    Body: { "theme_preference": "light" | "dark" | "system" }
    
    Response:
    {
        "status": "success",
        "message": "Theme preference updated",
        "theme_preference": "dark"
    }
    """
    try:
        data = json.loads(request.body)
        theme_pref = data.get('theme_preference', '').lower()
        
        # Validate theme choice
        valid_themes = ['light', 'dark', 'system']
        if theme_pref not in valid_themes:
            return JsonResponse({
                'status': 'error',
                'message': f'Invalid theme. Must be one of: {", ".join(valid_themes)}'
            }, status=400)
        
        # Update user preference
        request.user.theme_preference = theme_pref
        request.user.save(update_fields=['theme_preference'])
        
        return JsonResponse({
            'status': 'success',
            'message': 'Theme preference saved',
            'theme_preference': theme_pref,
        })
    
    except json.JSONDecodeError:
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid JSON in request body'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Error saving theme preference: {str(e)}'
        }, status=500)
