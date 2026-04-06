import * as Turbo from "@hotwired/turbo"
import { Application } from "@hotwired/stimulus"

// Start Stimulus
window.Stimulus = Application.start()

// Turbo lifecycle: cleanup GSAP before page swap
document.addEventListener("turbo:before-render", () => {
  // Remove ticker callback BEFORE destroying Lenis to prevent null.raf() errors
  if (window._lenisRaf && typeof gsap !== "undefined") {
    gsap.ticker.remove(window._lenisRaf)
    window._lenisRaf = null
  }
  if (typeof ScrollTrigger !== "undefined") {
    ScrollTrigger.getAll().forEach(t => t.kill())
  }
  if (window.lenis) {
    window.lenis.destroy()
    window.lenis = null
  }
})

// Intercept same-page hash link clicks — scroll with Lenis instead of Turbo navigation
document.addEventListener("click", (e) => {
  var link = e.target.closest("a[href*='#']")
  if (!link) return

  var url = new URL(link.href, window.location.origin)
  // Only intercept if same page (or root path with hash)
  var samePage = url.pathname === window.location.pathname || (url.pathname === "/" && window.location.pathname === "/")
  if (!samePage || !url.hash) return

  var target = document.querySelector(url.hash)
  if (!target) return

  e.preventDefault()
  e.stopPropagation()
  history.pushState(null, "", url.hash)
  if (typeof ScrollTrigger !== "undefined") ScrollTrigger.refresh()
  if (window.lenis) {
    window.lenis.scrollTo(target, { offset: -80 })
  } else {
    target.scrollIntoView({ behavior: "smooth" })
  }
})

// Turbo lifecycle: reinit Lenis after page swap
document.addEventListener("turbo:load", () => {
  var prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches
  if (!prefersReducedMotion && typeof gsap !== "undefined" && typeof Lenis !== "undefined") {
    window.lenis = new Lenis({
      duration: 1.2,
      easing: t => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      smoothWheel: true,
      wheelMultiplier: 1,
      touchMultiplier: 2
    })
    window.lenis.on("scroll", ScrollTrigger.update)
    // Remove old ticker callback to prevent accumulation on Turbo navigations
    if (window._lenisRaf) gsap.ticker.remove(window._lenisRaf)
    window._lenisRaf = time => { if (window.lenis) window.lenis.raf(time * 1000) }
    gsap.ticker.add(window._lenisRaf)
    gsap.ticker.lagSmoothing(0)
    gsap.registerPlugin(ScrollTrigger)
    gsap.defaults({ ease: "power2.out", duration: 0.8 })
    // Scroll to hash target if present, otherwise reset to top
    var hash = window.location.hash
    if (hash) {
      // Delay hash scroll so page animations + ScrollTrigger pinning settle first
      setTimeout(function() {
        if (typeof ScrollTrigger !== "undefined") ScrollTrigger.refresh()
        requestAnimationFrame(function() {
          var target = document.querySelector(hash)
          if (target && window.lenis) window.lenis.scrollTo(target, { offset: -80, immediate: true })
        })
      }, 300)
    } else {
      window.lenis.scrollTo(0, { immediate: true })
    }
  } else {
    // Fallback for reduced motion or no GSAP
    var hash = window.location.hash
    if (hash) {
      var target = document.querySelector(hash)
      if (target) target.scrollIntoView({ behavior: "smooth" })
    } else {
      window.scrollTo(0, 0)
    }
  }
})
