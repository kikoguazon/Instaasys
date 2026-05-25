from .models import Course

def active_courses_processor(request):
    try:
        if request.user.is_authenticated and hasattr(request.user, 'is_instructor') and request.user.is_instructor:
            return {'active_courses': Course.objects.filter(instructor=request.user)}
    except Exception:
        # Silently handle any exceptions to prevent template rendering errors
        pass
    return {}


def theme_processor(request):
    """
    Context processor that detects and provides the appropriate theme to templates.
    
    Logic:
    1. If user is authenticated and has a theme preference set:
       - If 'light' or 'dark': use that preference
       - If 'system': check for system preference detection flag
    2. If user is not authenticated:
       - Default to 'light' (will be overridden by client-side localStorage)
    
    Also provides metadata for AI systems to understand the current theme context.
    """
    context = {
        'theme': 'light',  # Default
        'system_prefers_dark': False,
    }
    
    if request.user.is_authenticated:
        theme_pref = getattr(request.user, 'theme_preference', 'system')
        
        if theme_pref == 'system':
            # Server cannot detect system preference, client-side JS will handle this
            # Pass a flag to indicate system preference should be detected
            context['theme'] = 'light'  # Default while system detection happens
            context['system_prefers_dark'] = False
            context['theme_preference_system'] = True
        else:
            # User has explicit light or dark preference
            context['theme'] = theme_pref
            context['theme_preference_system'] = False
    
    return context
