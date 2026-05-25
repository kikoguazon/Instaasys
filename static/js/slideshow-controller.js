/**
 * Slideshow Controller
 * Manages slide navigation, animations, and UI interactions
 */

class SlideshowController {
  constructor(options = {}) {
    this.currentSlideIndex = 0;
    this.slides = options.slides || [];
    this.animationEngine = new AnimationEngine({
      animationsEnabled: true,
      animationSpeed: 1,
    });
    
    this.animationsEnabled = true;
    this.isFullscreen = false;
    this.autoPlayEnabled = false;
    this.autoPlayDelay = 5000;

    this.setupElements();
    this.bindEvents();
    this.initializeSlideshow();
  }

  /**
   * Setup DOM element references
   */
  setupElements() {
    this.container = document.getElementById('slideshowContainer');
    this.viewport = document.getElementById('slideViewport');
    this.allSlides = document.querySelectorAll('.slide');
    this.prevBtn = document.getElementById('prevBtn');
    this.nextBtn = document.getElementById('nextBtn');
    this.fullscreenBtn = document.getElementById('fullscreenBtn');
    this.exitBtn = document.getElementById('exitBtn');
    this.animationToggle = document.getElementById('animationToggle');
    this.animationLevel = document.getElementById('animationLevel');
    this.currentSlideDisplay = document.getElementById('currentSlide');
    this.totalSlidesDisplay = document.getElementById('totalSlides');
    this.progressFill = document.getElementById('progressFill');
  }

  /**
   * Bind event listeners
   */
  bindEvents() {
    this.prevBtn.addEventListener('click', () => this.previousSlide());
    this.nextBtn.addEventListener('click', () => this.nextSlide());
    this.fullscreenBtn.addEventListener('click', () => this.toggleFullscreen());
    this.exitBtn.addEventListener('click', () => this.exitSlideshow());
    this.animationToggle.addEventListener('click', () => this.toggleAnimations());

    // Keyboard controls
    document.addEventListener('keydown', (e) => this.handleKeyboard(e));

    // Mouse controls
    this.viewport.addEventListener('click', (e) => {
      if (e.clientX > window.innerWidth / 2) {
        this.nextSlide();
      } else {
        this.previousSlide();
      }
    });

    // Window resize
    window.addEventListener('resize', () => this.updateLayout());
  }

  /**
   * Initialize slideshow
   */
  initializeSlideshow() {
    this.totalSlidesDisplay.textContent = this.allSlides.length;
    this.showSlide(0);
  }

  /**
   * Show a specific slide
   */
  async showSlide(index) {
    if (index < 0 || index >= this.allSlides.length) {
      return;
    }

    // Hide all slides
    this.allSlides.forEach((slide) => {
      slide.classList.add('hidden');
    });

    // Show target slide
    const targetSlide = this.allSlides[index];
    targetSlide.classList.remove('hidden');
    this.currentSlideIndex = index;

    // Update UI
    this.updateUI();

    // Get animation level
    const animationLevel = targetSlide.dataset.animationLevel || 'basic';

    // Play animations
    if (this.animationsEnabled) {
      await this.animationEngine.playSlideAnimations(targetSlide, animationLevel);
    } else {
      this.animationEngine.showAllElements(targetSlide);
    }

    // Scroll into view (in case of small screens)
    targetSlide.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  /**
   * Navigation
   */
  async nextSlide() {
    if (this.currentSlideIndex < this.allSlides.length - 1) {
      await this.showSlide(this.currentSlideIndex + 1);
      this.resetAutoPlay();
    }
  }

  async previousSlide() {
    if (this.currentSlideIndex > 0) {
      await this.showSlide(this.currentSlideIndex - 1);
      this.resetAutoPlay();
    }
  }

  async jumpToSlide(index) {
    await this.showSlide(index);
    this.resetAutoPlay();
  }

  /**
   * Update UI elements
   */
  updateUI() {
    // Update counter
    this.currentSlideDisplay.textContent = this.currentSlideIndex + 1;

    // Update progress bar
    const progress = ((this.currentSlideIndex + 1) / this.allSlides.length) * 100;
    this.progressFill.style.width = `${progress}%`;

    // Update button states
    this.prevBtn.disabled = this.currentSlideIndex === 0;
    this.nextBtn.disabled = this.currentSlideIndex === this.allSlides.length - 1;

    // Update animation level display
    const currentSlide = this.allSlides[this.currentSlideIndex];
    const animLevel = currentSlide.dataset.animationLevel || 'basic';
    this.animationLevel.textContent = animLevel.charAt(0).toUpperCase() + animLevel.slice(1);
  }

  /**
   * Toggle fullscreen
   */
  toggleFullscreen() {
    if (!this.isFullscreen) {
      if (this.container.requestFullscreen) {
        this.container.requestFullscreen();
      } else if (this.container.mozRequestFullScreen) {
        this.container.mozRequestFullScreen();
      } else if (this.container.webkitRequestFullscreen) {
        this.container.webkitRequestFullscreen();
      }
      this.isFullscreen = true;
      this.fullscreenBtn.textContent = '⛶ Exit Fullscreen';
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen();
      } else if (document.mozCancelFullScreen) {
        document.mozCancelFullScreen();
      } else if (document.webkitExitFullscreen) {
        document.webkitExitFullscreen();
      }
      this.isFullscreen = false;
      this.fullscreenBtn.textContent = '⛶ Fullscreen';
    }
  }

  /**
   * Toggle animations
   */
  toggleAnimations() {
    this.animationsEnabled = !this.animationsEnabled;
    this.animationEngine.toggleAnimations(this.animationsEnabled);
    this.animationToggle.textContent = this.animationsEnabled ? 'On' : 'Off';
    this.animationToggle.classList.toggle('active', this.animationsEnabled);

    // Re-animate current slide if it exists
    const currentSlide = this.allSlides[this.currentSlideIndex];
    if (currentSlide && !currentSlide.classList.contains('hidden')) {
      this.animateCurrentSlide();
    }
  }

  /**
   * Animate current slide
   */
  async animateCurrentSlide() {
    const currentSlide = this.allSlides[this.currentSlideIndex];
    const animationLevel = currentSlide.dataset.animationLevel || 'basic';
    
    if (this.animationsEnabled) {
      await this.animationEngine.playSlideAnimations(currentSlide, animationLevel);
    } else {
      this.animationEngine.showAllElements(currentSlide);
    }
  }

  /**
   * Exit slideshow
   */
  exitSlideshow() {
    if (this.isFullscreen) {
      this.toggleFullscreen();
    }
    // Return to presentation detail page
    history.back();
  }

  /**
   * Handle keyboard controls
   */
  handleKeyboard(e) {
    switch (e.key) {
      case 'ArrowRight':
      case ' ':
        e.preventDefault();
        this.nextSlide();
        break;
      case 'ArrowLeft':
        e.preventDefault();
        this.previousSlide();
        break;
      case 'f':
      case 'F':
        e.preventDefault();
        this.toggleFullscreen();
        break;
      case 'Escape':
        this.exitSlideshow();
        break;
      case 'a':
      case 'A':
        e.preventDefault();
        this.toggleAnimations();
        break;
    }
  }

  /**
   * Auto-play functionality
   */
  startAutoPlay() {
    this.autoPlayEnabled = true;
    this.autoPlayTimer = setInterval(() => {
      if (this.currentSlideIndex < this.allSlides.length - 1) {
        this.nextSlide();
      } else {
        this.stopAutoPlay();
      }
    }, this.autoPlayDelay);
  }

  stopAutoPlay() {
    this.autoPlayEnabled = false;
    if (this.autoPlayTimer) {
      clearInterval(this.autoPlayTimer);
    }
  }

  resetAutoPlay() {
    if (this.autoPlayEnabled) {
      this.stopAutoPlay();
      this.startAutoPlay();
    }
  }

  /**
   * Update layout for responsiveness
   */
  updateLayout() {
    // Adjust font sizes based on viewport
    const slide = this.allSlides[this.currentSlideIndex];
    if (slide) {
      const vw = window.innerWidth;
      if (vw < 768) {
        slide.style.transform = 'scale(0.8)';
      } else if (vw < 1024) {
        slide.style.transform = 'scale(0.9)';
      } else {
        slide.style.transform = 'scale(1)';
      }
    }
  }

  /**
   * Speaker view mode (if needed)
   */
  toggleSpeakerView() {
    this.container.classList.toggle('speaker-view');
  }

  /**
   * Export as image
   */
  exportCurrentSlideAsImage() {
    const currentSlide = this.allSlides[this.currentSlideIndex];
    const canvas = document.createElement('canvas');
    // Implementation would use html2canvas or similar
  }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
  const controller = new SlideshowController({
    slides: slideshowData.slides,
  });

  // Make global for debugging
  window.slideshowController = controller;
});
