/**
 * Animation Engine for Slideshow
 * Handles animation playback for slide elements
 */

class AnimationEngine {
  constructor(options = {}) {
    this.animationsEnabled = options.animationsEnabled !== false;
    this.animationSpeed = options.animationSpeed || 1;
    this.currentAnimatingElements = [];
    this.animationQueue = [];
    this.isAnimating = false;
  }

  /**
   * Play animations for a slide based on animation level
   */
  playSlideAnimations(slideElement, animationLevel = 'basic') {
    if (!this.animationsEnabled) {
      this.showAllElements(slideElement);
      return Promise.resolve();
    }

    return new Promise((resolve) => {
      this.clearAnimations(slideElement);
      
      const animationRules = this.getAnimationRules(animationLevel);
      const elements = this.getAnimatableElements(slideElement, animationRules);
      
      this.animateSequence(elements, animationRules).then(resolve);
    });
  }

  /**
   * Get animation rules based on animation level
   */
  getAnimationRules(level) {
    const rules = {
      none: {},
      basic: {
        title: {
          animation: 'fade-in',
          duration: 600,
          delay: 0,
        },
        bullets: {
          animation: 'slide-in',
          duration: 500,
          delay: 200, // Between each bullet
        },
        image: {
          animation: 'appear',
          duration: 800,
          delay: 0,
        },
      },
      enhanced: {
        title: {
          animation: 'fade-in',
          duration: 600,
          delay: 0,
        },
        bullets: {
          animation: 'slide-in',
          duration: 400,
          delay: 300, // Longer stagger
          stagger: true,
        },
        image: {
          animation: 'appear',
          duration: 600,
          delay: 300,
        },
      },
    };

    return rules[level] || rules.basic;
  }

  /**
   * Get animatable elements from slide
   */
  getAnimatableElements(slideElement, animationRules) {
    const elements = {};

    // Title
    const titleEl = slideElement.querySelector('.slide-title');
    if (titleEl && animationRules.title) {
      elements.title = [titleEl];
    }

    // Bullets
    const bulletEls = slideElement.querySelectorAll('.slide-bullets li');
    if (bulletEls.length > 0 && animationRules.bullets) {
      elements.bullets = Array.from(bulletEls);
    }

    // Image
    const imageEl = slideElement.querySelector('.slide-image img');
    if (imageEl && animationRules.image) {
      elements.image = [imageEl];
    }

    return elements;
  }

  /**
   * Animate elements in sequence
   */
  animateSequence(elements, animationRules, delay = 0) {
    return new Promise((resolve) => {
      this.isAnimating = true;
      let totalDelay = delay;

      // Animate title first
      if (elements.title && animationRules.title) {
        this.animateElement(
          elements.title[0],
          animationRules.title,
          totalDelay
        );
        totalDelay += animationRules.title.duration + animationRules.title.delay;
      }

      // Then bullets (with stagger if enhanced)
      if (elements.bullets && animationRules.bullets) {
        const bulletDelay = animationRules.bullets.delay;
        elements.bullets.forEach((el, index) => {
          const elementDelay = totalDelay + (index * bulletDelay);
          this.animateElement(el, animationRules.bullets, elementDelay);
        });
        const lastBulletDelay = totalDelay + (elements.bullets.length - 1) * bulletDelay;
        totalDelay = lastBulletDelay + animationRules.bullets.duration;
      }

      // Finally image
      if (elements.image && animationRules.image) {
        this.animateElement(
          elements.image[0],
          animationRules.image,
          Math.max(totalDelay, animationRules.image.delay)
        );
        totalDelay = Math.max(
          totalDelay,
          animationRules.image.delay + animationRules.image.duration
        );
      }

      // Wait for all animations to complete
      setTimeout(() => {
        this.isAnimating = false;
        resolve();
      }, totalDelay + 100);
    });
  }

  /**
   * Animate a single element
   */
  animateElement(element, rule, delay) {
    const duration = rule.duration / this.animationSpeed;
    
    // Reset any previous animation
    element.style.animation = 'none';
    element.offsetHeight; // Trigger reflow

    // Apply animation
    element.style.animationName = this.getCSSAnimationName(rule.animation);
    element.style.animationDuration = `${duration}ms`;
    element.style.animationDelay = `${delay}ms`;
    element.style.animationFillMode = 'both';
    element.style.animationTimingFunction = 'cubic-bezier(0.34, 1.56, 0.64, 1)';
  }

  /**
   * Map animation names to CSS keyframes
   */
  getCSSAnimationName(animation) {
    const mapping = {
      'fade-in': 'fadeIn',
      'slide-in': 'slideInLeft',
      'appear': 'appear',
    };
    return mapping[animation] || animation;
  }

  /**
   * Show all elements without animation
   */
  showAllElements(slideElement) {
    const elements = slideElement.querySelectorAll('[class*="slide-"]');
    elements.forEach((el) => {
      el.style.animation = 'none';
      el.style.opacity = '1';
    });
  }

  /**
   * Clear animations from slide
   */
  clearAnimations(slideElement) {
    const elements = slideElement.querySelectorAll('*');
    elements.forEach((el) => {
      el.style.animation = 'none';
      el.style.animationDelay = '0ms';
    });
  }

  /**
   * Toggle animations on/off
   */
  toggleAnimations(enabled) {
    this.animationsEnabled = enabled;
  }

  /**
   * Skip to end of animation (for accessibility)
   */
  skipAnimation(slideElement) {
    this.clearAnimations(slideElement);
    this.showAllElements(slideElement);
  }
}

// Export for use in slideshow controller
if (typeof module !== 'undefined' && module.exports) {
  module.exports = AnimationEngine;
}
