from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Show configured image generation sources and their status'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('\n📊 Image Generation Configuration\n'))
        self.stdout.write('=' * 60)
        
        # Check Nano Banana
        nano_token = getattr(settings, 'NANO_BANANA_TOKEN', '')
        if nano_token:
            self.stdout.write(self.style.SUCCESS('\n✅ Nano Banana (AI Generation)'))
            self.stdout.write(f'   Status: Configured')
            self.stdout.write(f'   Priority: 1 (Primary)')
            self.stdout.write(f'   Model: gemini-3.1-flash-image-preview')
            self.stdout.write(f'   Cost: ~$0.055 per image')
        else:
            self.stdout.write(self.style.WARNING('\n⚠️  Nano Banana (AI Generation)'))
            self.stdout.write(f'   Status: Not configured')
            self.stdout.write(f'   Add NANO_BANANA_TOKEN to .env to enable')
        
        # Check Pexels
        pexels_key = getattr(settings, 'PEXELS_API_KEY', '')
        if pexels_key:
            self.stdout.write(self.style.SUCCESS('\n✅ Pexels (Stock Photos)'))
            self.stdout.write(f'   Status: Configured')
            self.stdout.write(f'   Priority: 2 (Fallback)')
            self.stdout.write(f'   Cost: Free')
        else:
            self.stdout.write(self.style.WARNING('\n⚠️  Pexels (Stock Photos)'))
            self.stdout.write(f'   Status: Not configured')
        
        # Check Unsplash
        unsplash_key = getattr(settings, 'UNSPLASH_ACCESS_KEY', '')
        if unsplash_key:
            self.stdout.write(self.style.SUCCESS('\n✅ Unsplash (Stock Photos)'))
            self.stdout.write(f'   Status: Configured')
            self.stdout.write(f'   Priority: 3 (Fallback)')
            self.stdout.write(f'   Cost: Free')
        else:
            self.stdout.write(self.style.WARNING('\n⚠️  Unsplash (Stock Photos)'))
            self.stdout.write(f'   Status: Not configured')
        
        # Wikimedia (always available)
        self.stdout.write(self.style.SUCCESS('\n✅ Wikimedia Commons'))
        self.stdout.write(f'   Status: Always available')
        self.stdout.write(f'   Priority: 4 (Last resort)')
        self.stdout.write(f'   Cost: Free')
        self.stdout.write(f'   Quality: Lower')
        
        self.stdout.write('\n' + '=' * 60)
        
        # Summary
        sources = []
        if nano_token:
            sources.append('Nano Banana (AI)')
        if pexels_key:
            sources.append('Pexels')
        if unsplash_key:
            sources.append('Unsplash')
        sources.append('Wikimedia')
        
        self.stdout.write(self.style.SUCCESS(f'\n📌 Active Sources: {", ".join(sources)}'))
        
        if nano_token:
            self.stdout.write(self.style.SUCCESS('🎨 AI image generation is ENABLED'))
        else:
            self.stdout.write(self.style.WARNING('💡 Tip: Add NANO_BANANA_TOKEN to enable AI image generation'))
        
        self.stdout.write('\n')
