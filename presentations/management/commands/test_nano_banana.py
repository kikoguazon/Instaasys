from django.core.management.base import BaseCommand
from instaasys.nano_banana_service import generate_image_nano_banana
from datetime import datetime


class Command(BaseCommand):
    help = 'Test Nano Banana AI image generation integration'

    def add_arguments(self, parser):
        parser.add_argument(
            '--prompt',
            type=str,
            default='A teacher explaining concepts to students in a modern classroom',
            help='Image generation prompt'
        )

    def handle(self, *args, **options):
        prompt = options['prompt']
        
        self.stdout.write(self.style.SUCCESS(f'\n🔄 Testing Nano Banana image generation...'))
        self.stdout.write(f'Prompt: "{prompt}"')
        
        try:
            image_bytes = generate_image_nano_banana(prompt)
            
            if image_bytes:
                # Save test image
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"nano_banana_test_{timestamp}.jpeg"
                
                with open(filename, 'wb') as f:
                    f.write(image_bytes)
                
                self.stdout.write(self.style.SUCCESS(f'\n✅ Success!'))
                self.stdout.write(f'📊 Generated {len(image_bytes)} bytes')
                self.stdout.write(f'💾 Saved to: {filename}')
            else:
                self.stdout.write(self.style.ERROR('\n❌ Failed to generate image'))
                self.stdout.write('Check that NANO_BANANA_TOKEN is set in .env')
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\n❌ Error: {e}'))
