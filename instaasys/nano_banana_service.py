# instaasys/nano_banana_service.py

import os
import logging
import requests
import base64
import re
from django.conf import settings

logger = logging.getLogger(__name__)


def generate_image_nano_banana(prompt: str) -> bytes | None:
    """
    Generate an AI image using the Nano Banana API (Gemini-based image generation).
    
    Args:
        prompt: Text description of the image to generate
        
    Returns:
        Image bytes (JPEG) on success, None on failure
    """
    if not prompt or not prompt.strip():
        logger.debug("Empty prompt provided to Nano Banana")
        return None
    
    try:
        api_key = getattr(settings, 'NANO_BANANA_TOKEN', '')
        if not api_key:
            logger.debug("NANO_BANANA_TOKEN not configured")
            return None
        
        url = "https://api.laozhang.ai/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "gemini-3.1-flash-image-preview",
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }
        
        logger.info(f"Generating image with Nano Banana: '{prompt[:50]}...'")
        
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        
        if response.status_code == 200:
            data = response.json()
            
            # Extract message content
            if 'choices' in data and len(data['choices']) > 0:
                choice = data['choices'][0]
                if 'message' in choice and 'content' in choice['message']:
                    content = choice['message']['content']
                    
                    # Extract base64 image data
                    base64_pattern = r'data:image/([^;]+);base64,([A-Za-z0-9+/=]+)'
                    match = re.search(base64_pattern, content)
                    
                    if match:
                        image_format = match.group(1)
                        b64_data = match.group(2)
                        
                        # Decode base64 to bytes
                        image_data = base64.b64decode(b64_data)
                        
                        logger.info(f"Nano Banana generated {len(image_data)} bytes ({image_format})")
                        return image_data
                    else:
                        logger.warning("No base64 image data found in Nano Banana response")
        else:
            logger.warning(f"Nano Banana API error {response.status_code}: {response.text[:200]}")
            
    except requests.exceptions.Timeout:
        logger.warning("Nano Banana API request timed out")
    except Exception as e:
        logger.exception(f"Nano Banana image generation failed: {e}")
    
    return None
