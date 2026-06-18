/**
 * hud.js — CCDashboard Arc-Reactor HUD
 *
 * Injected into index.html by the builder at the HUD script slot.
 * Runs BEFORE app.js, AFTER the data script.
 * Zero global leakage (IIFE). No frameworks, no imports, pure Canvas 2D.
 */
(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // Constants
  // ---------------------------------------------------------------------------
  const C = {
    // Palette — cyan / teal holographic
    CYAN:        '#00e5ff',
    TEAL:        '#19f0d4',
    CORE_INNER:  'rgba(0, 229, 255, 0.95)',
    CORE_MID:    'rgba(25, 240, 212, 0.45)',
    CORE_OUTER:  'rgba(0, 229, 255, 0.0)',
    GLOW:        'rgba(0, 229, 255, 0.18)',
    DIM:         'rgba(0, 229, 255, 0.08)',
    RADAR:       'rgba(0, 229, 255, 0.35)',
    PARTICLE:    'rgba(0, 229, 255, 0.55)',
    LABEL:       'rgba(0, 229, 255, 0.90)',

    // Animation / rendering
    MAX_PARTICLES:   80,
    PARTICLE_SPEED:  0.15,   // px/ms at 1 dpr
    NEAR_DIST_SQ:    2500,   // link particles within sqrt(2500)=50px
    RESIZE_DEBOUNCE: 200,    // ms

    // Ring definitions: [radiusFraction, speedRad/ms, direction, dashPattern, width, alpha]
    // radiusFraction is a fraction of the "reactor radius" (half the shortest side * 0.42)
    RINGS: [
      { r: 0.38, speed: 0.00045, dir:  1, dash: [4, 8],   w: 1.0, a: 0.55 },  // inner fast
      { r: 0.55, speed: 0.00028, dir: -1, dash: [8, 6],   w: 1.5, a: 0.65 },  // mid CW
      { r: 0.72, speed: 0.00018, dir:  1, dash: [12, 8],  w: 1.0, a: 0.50 },  // outer CCW
      { r: 0.88, speed: 0.00010, dir: -1, dash: [3, 14],  w: 0.8, a: 0.40 },  // outermost slow
    ],

    // Segmented arcs: [radiusFraction, speedRad/ms, dir, segments, gapFraction, width, alpha]
    SEGS: [
      { r: 0.48, speed: 0.00060, dir:  1, segs: 6, gap: 0.22, w: 2.5, a: 0.80 },
      { r: 0.65, speed: 0.00035, dir: -1, segs: 4, gap: 0.30, w: 2.0, a: 0.70 },
    ],

    // Tick marks on two rings: [radiusFraction, count, tickLen, width, alpha]
    TICKS: [
      { r: 0.55, count: 36, len: 0.040, w: 1.0, a: 0.50 },
      { r: 0.88, count: 60, len: 0.025, w: 0.8, a: 0.35 },
    ],

    // Boot lines
    BOOT_LINES: [
      'INITIALIZING…',
      'MOUNTING ~/.claude …',
      'INDEXING SKILLS / AGENTS / RULES …',
      'RENDERING HUD …',
      'ONLINE.',
    ],
    BOOT_CHAR_DELAY:  14,   // ms per character
    BOOT_LINE_PAUSE:  70,   // ms between lines
    BOOT_HOLD:       200,   // ms after last line before fade
    BOOT_DONE_DELAY: 1200,  // ms total target for reduced-motion fast-path
  };

  // ---------------------------------------------------------------------------
  // Reduced-motion check (honour OS / browser preference)
  // ---------------------------------------------------------------------------
  const REDUCED = (function () {
    try {
      return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    } catch (_) {
      return false;
    }
  }());

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  let canvas = null;
  let ctx    = null;
  let W = 0, H = 0;        // logical (CSS) dimensions
  let dpr = 1;
  let cx = 0, cy = 0;      // centre of canvas in physical px
  let reactorR = 0;         // reactor radius in physical px

  let particles = [];
  let animId = null;
  let lastTs  = null;
  let resizeTimer = null;

  // Accumulated rotation angles per ring / seg (in radians)
  let ringAngles = C.RINGS.map(() => 0);
  let segAngles  = C.SEGS.map(() => 0);
  let radarAngle = 0;

  // Pulse state
  let pulseT = 0; // ms accumulator for sine pulse

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------
  function lerp(a, b, t) { return a + (b - a) * t; }

  /** Clamp x to [min, max] */
  function clamp(x, mn, mx) { return x < mn ? mn : x > mx ? mx : x; }

  // ---------------------------------------------------------------------------
  // Canvas setup
  // ---------------------------------------------------------------------------
  function setupCanvas() {
    canvas = document.getElementById('reactor');
    if (!canvas) return false;

    ctx = canvas.getContext('2d');
    if (!ctx) return false;

    sizeCanvas();
    return true;
  }

  function sizeCanvas() {
    if (!canvas) return;

    dpr = window.devicePixelRatio || 1;

    // Read container size (CSS layout already positioned the canvas)
    const container = canvas.parentElement || canvas;
    W = container.clientWidth  || canvas.clientWidth  || 400;
    H = container.clientHeight || canvas.clientHeight || 400;

    // Physical backing-store size
    canvas.width  = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);

    // CSS display size
    canvas.style.width  = W + 'px';
    canvas.style.height = H + 'px';

    // Centre and reactor radius
    cx = Math.round(W * dpr / 2);
    cy = Math.round(H * dpr / 2);
    reactorR = Math.round(Math.min(W, H) * dpr * 0.42);
  }

  // ---------------------------------------------------------------------------
  // Particle system
  // ---------------------------------------------------------------------------
  function initParticles() {
    particles = [];
    for (let i = 0; i < C.MAX_PARTICLES; i++) {
      particles.push(makeParticle(true));
    }
  }

  function makeParticle(randomPos) {
    const angle = Math.random() * Math.PI * 2;
    const speed = C.PARTICLE_SPEED * dpr * (0.3 + Math.random() * 0.7);
    return {
      x: randomPos ? Math.random() * W * dpr : cx + Math.cos(angle) * reactorR * 1.05,
      y: randomPos ? Math.random() * H * dpr : cy + Math.sin(angle) * reactorR * 1.05,
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed,
      a: 0.15 + Math.random() * 0.45,
      size: (0.5 + Math.random() * 1.5) * dpr,
    };
  }

  function updateParticles(dt) {
    const pw = W * dpr;
    const ph = H * dpr;
    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      // Wrap edges
      if (p.x < -5)    p.x = pw + 5;
      if (p.x > pw + 5) p.x = -5;
      if (p.y < -5)    p.y = ph + 5;
      if (p.y > ph + 5) p.y = -5;
    }
  }

  function drawParticles() {
    if (!ctx) return;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';

    // Draw dots
    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];
      ctx.globalAlpha = p.a * 0.6;
      ctx.fillStyle = C.PARTICLE;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
      ctx.fill();
    }

    // Draw connecting lines between nearby particles (sparse)
    ctx.strokeStyle = C.PARTICLE;
    ctx.lineWidth = 0.5 * dpr;
    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const dx = particles[i].x - particles[j].x;
        const dy = particles[i].y - particles[j].y;
        const dSq = dx * dx + dy * dy;
        if (dSq < C.NEAR_DIST_SQ * dpr * dpr) {
          const t = 1 - (dSq / (C.NEAR_DIST_SQ * dpr * dpr));
          ctx.globalAlpha = t * 0.12;
          ctx.beginPath();
          ctx.moveTo(particles[i].x, particles[i].y);
          ctx.lineTo(particles[j].x, particles[j].y);
          ctx.stroke();
        }
      }
    }

    ctx.restore();
  }

  // ---------------------------------------------------------------------------
  // Reactor drawing
  // ---------------------------------------------------------------------------

  /** Radial gradient glowing core, size modulated by pulse */
  function drawCore(pulse) {
    if (!ctx) return;
    const coreR = reactorR * (0.26 + pulse * 0.035);
    const grd = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR);
    grd.addColorStop(0.00, C.CORE_INNER);
    grd.addColorStop(0.30, C.CORE_MID);
    grd.addColorStop(0.70, 'rgba(0, 229, 255, 0.12)');
    grd.addColorStop(1.00, C.CORE_OUTER);

    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.shadowBlur  = Math.round(reactorR * 0.25);
    ctx.shadowColor = C.CYAN;

    ctx.fillStyle = grd;
    ctx.beginPath();
    ctx.arc(cx, cy, coreR, 0, Math.PI * 2);
    ctx.fill();

    // Second pass for intense inner bloom
    const bloom = reactorR * (0.10 + pulse * 0.015);
    const grd2 = ctx.createRadialGradient(cx, cy, 0, cx, cy, bloom);
    grd2.addColorStop(0, 'rgba(200, 255, 255, 0.95)');
    grd2.addColorStop(1, 'rgba(0, 229, 255, 0.0)');
    ctx.fillStyle = grd2;
    ctx.shadowBlur = Math.round(reactorR * 0.12);
    ctx.beginPath();
    ctx.arc(cx, cy, bloom, 0, Math.PI * 2);
    ctx.fill();

    ctx.restore();
  }

  /** Dashed / patterned concentric rings with individual rotation */
  function drawRings(pulse) {
    if (!ctx) return;
    for (let i = 0; i < C.RINGS.length; i++) {
      const cfg = C.RINGS[i];
      const r = reactorR * cfg.r;

      ctx.save();
      ctx.globalCompositeOperation = 'lighter';
      ctx.globalAlpha  = cfg.a * (0.85 + pulse * 0.15);
      ctx.strokeStyle  = C.CYAN;
      ctx.lineWidth    = cfg.w * dpr;
      ctx.shadowBlur   = Math.round(6 * dpr);
      ctx.shadowColor  = C.CYAN;

      // Scale dash pattern to dpr
      const dash = cfg.dash.map(function (d) { return d * dpr; });
      ctx.setLineDash(dash);
      ctx.lineDashOffset = -ringAngles[i] * r; // offset rotates the dash

      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }
  }

  /** Segmented arcs that physically rotate */
  function drawSegmentedArcs(pulse) {
    if (!ctx) return;
    for (let i = 0; i < C.SEGS.length; i++) {
      const cfg = C.SEGS[i];
      const r   = reactorR * cfg.r;
      const base = segAngles[i];
      const segSpan   = (Math.PI * 2 / cfg.segs);
      const arcSpan   = segSpan * (1 - cfg.gap);

      ctx.save();
      ctx.globalCompositeOperation = 'lighter';
      ctx.globalAlpha = cfg.a * (0.8 + pulse * 0.2);
      ctx.strokeStyle = C.TEAL;
      ctx.lineWidth   = cfg.w * dpr;
      ctx.shadowBlur  = Math.round(8 * dpr);
      ctx.shadowColor = C.TEAL;
      ctx.setLineDash([]);

      for (let s = 0; s < cfg.segs; s++) {
        const start = base + s * segSpan;
        const end   = start + arcSpan;
        ctx.beginPath();
        ctx.arc(cx, cy, r, start, end);
        ctx.stroke();
      }
      ctx.restore();
    }
  }

  /** Evenly-spaced tick marks radiating inward/outward from a ring */
  function drawTickMarks(pulse) {
    if (!ctx) return;
    for (let ti = 0; ti < C.TICKS.length; ti++) {
      const cfg = C.TICKS[ti];
      const r   = reactorR * cfg.r;
      const tickLen = reactorR * cfg.len;

      ctx.save();
      ctx.globalCompositeOperation = 'lighter';
      ctx.globalAlpha = cfg.a * (0.8 + pulse * 0.2);
      ctx.strokeStyle = C.CYAN;
      ctx.lineWidth   = cfg.w * dpr;
      ctx.shadowBlur  = Math.round(4 * dpr);
      ctx.shadowColor = C.CYAN;
      ctx.setLineDash([]);

      for (let t = 0; t < cfg.count; t++) {
        const angle = (t / cfg.count) * Math.PI * 2;
        const cos = Math.cos(angle);
        const sin = Math.sin(angle);
        // Major ticks every 6th are longer
        const len = (t % 6 === 0) ? tickLen * 1.8 : tickLen;
        ctx.beginPath();
        ctx.moveTo(cx + cos * (r - len / 2), cy + sin * (r - len / 2));
        ctx.lineTo(cx + cos * (r + len / 2), cy + sin * (r + len / 2));
        ctx.stroke();
      }
      ctx.restore();
    }
  }

  /** Slow-rotating radar sweep line with fading gradient */
  function drawRadarSweep() {
    if (!ctx) return;
    const sweepR = reactorR * 0.96;

    ctx.save();
    ctx.globalCompositeOperation = 'lighter';

    // Build sweep gradient: bright at origin → transparent at tip
    const grd = ctx.createLinearGradient(
      cx, cy,
      cx + Math.cos(radarAngle) * sweepR,
      cy + Math.sin(radarAngle) * sweepR
    );
    grd.addColorStop(0,    'rgba(0, 229, 255, 0.0)');
    grd.addColorStop(0.35, C.RADAR);
    grd.addColorStop(0.85, 'rgba(0, 229, 255, 0.55)');
    grd.addColorStop(1,    'rgba(0, 229, 255, 0.25)');

    ctx.strokeStyle = grd;
    ctx.lineWidth   = 1.5 * dpr;
    ctx.shadowBlur  = Math.round(10 * dpr);
    ctx.shadowColor = C.CYAN;
    ctx.setLineDash([]);

    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(
      cx + Math.cos(radarAngle) * sweepR,
      cy + Math.sin(radarAngle) * sweepR
    );
    ctx.stroke();

    // Trailing fade arc behind the sweep (comet tail)
    const tailSpan = Math.PI / 4;
    const tailGrd = ctx.createConicalGradient
      ? null // not standard — skip
      : null;

    // Fallback tail: a short arc drawn with decreasing alpha
    const steps = 12;
    for (let s = 0; s < steps; s++) {
      const t = s / steps;
      const a = radarAngle - tailSpan * (1 - t);
      ctx.globalAlpha = (1 - t) * 0.18;
      ctx.strokeStyle = C.CYAN;
      ctx.lineWidth   = (1.5 - t * 0.8) * dpr;
      ctx.beginPath();
      ctx.arc(cx, cy, sweepR * (0.5 + t * 0.46), a, a + (tailSpan / steps) + 0.001);
      ctx.stroke();
    }

    ctx.restore();
  }

  /** Outer ambient glow ring */
  function drawAmbientGlow(pulse) {
    if (!ctx) return;
    const r = reactorR * 0.95;
    const grd = ctx.createRadialGradient(cx, cy, r * 0.85, cx, cy, r * 1.15);
    grd.addColorStop(0, 'rgba(0, 229, 255, 0.0)');
    grd.addColorStop(0.5, `rgba(0, 229, 255, ${0.04 + pulse * 0.03})`);
    grd.addColorStop(1, 'rgba(0, 229, 255, 0.0)');

    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.fillStyle = grd;
    ctx.beginPath();
    ctx.arc(cx, cy, r * 1.15, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  /** Label: CCDASH_DATA.summary.total or "JARVIS" rendered near core */
  function drawLabel() {
    if (!ctx) return;

    let label = 'JARVIS';
    try {
      const total = window.CCDASH_DATA &&
                    window.CCDASH_DATA.summary &&
                    window.CCDASH_DATA.summary.total;
      if (total !== undefined && total !== null) {
        label = String(total);
      }
    } catch (_) {}

    const fontSize = Math.round(reactorR * 0.13);
    ctx.save();
    ctx.globalCompositeOperation = 'source-over';
    ctx.font = `bold ${fontSize}px 'Courier New', Courier, monospace`;
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'middle';

    // Shadow glow behind text
    ctx.shadowBlur  = Math.round(reactorR * 0.10);
    ctx.shadowColor = C.CYAN;
    ctx.fillStyle   = C.LABEL;
    ctx.fillText(label, cx, cy);

    // Thin sub-label
    const subSize = Math.round(reactorR * 0.058);
    ctx.font        = `${subSize}px 'Courier New', Courier, monospace`;
    ctx.globalAlpha = 0.65;
    ctx.shadowBlur  = Math.round(reactorR * 0.05);
    ctx.fillText('SYSTEM ONLINE', cx, cy + fontSize * 1.05);
    ctx.restore();
  }

  // ---------------------------------------------------------------------------
  // Full frame render
  // ---------------------------------------------------------------------------
  function renderFrame(dt, pulse) {
    if (!ctx) return;

    // Clear
    ctx.clearRect(0, 0, W * dpr, H * dpr);

    // Layer 1: background particle field
    drawParticles();

    // Layer 2: ambient outer glow
    drawAmbientGlow(pulse);

    // Layer 3: tick marks (behind rings)
    drawTickMarks(pulse);

    // Layer 4: concentric dashed rings
    drawRings(pulse);

    // Layer 5: segmented rotating arcs
    drawSegmentedArcs(pulse);

    // Layer 6: radar sweep
    drawRadarSweep();

    // Layer 7: bright pulsing core
    drawCore(pulse);

    // Layer 8: centre label
    drawLabel();
  }

  // ---------------------------------------------------------------------------
  // Static frame (reduced-motion path)
  // ---------------------------------------------------------------------------
  function renderStatic() {
    pulseT = 500; // mid-pulse
    const pulse = (Math.sin(pulseT / 800) + 1) / 2;

    // Particles at fixed positions (already initialised by initParticles)
    renderFrame(0, pulse);
  }

  // ---------------------------------------------------------------------------
  // Animation loop
  // ---------------------------------------------------------------------------
  function tick(ts) {
    if (lastTs === null) lastTs = ts;
    const dt = clamp(ts - lastTs, 0, 50); // cap to 50ms to avoid spiral
    lastTs = ts;

    pulseT += dt;
    const pulse = (Math.sin(pulseT / 900) + 1) / 2; // 0→1 smooth oscillation

    // Update ring/seg rotation angles
    for (let i = 0; i < C.RINGS.length; i++) {
      ringAngles[i] += C.RINGS[i].speed * C.RINGS[i].dir * dt;
    }
    for (let i = 0; i < C.SEGS.length; i++) {
      segAngles[i] += C.SEGS[i].speed * C.SEGS[i].dir * dt;
    }

    // Radar sweep: one full rotation ~8 seconds
    radarAngle = (radarAngle + 0.00078 * dt) % (Math.PI * 2);

    // Update particle positions
    updateParticles(dt);

    // Render
    renderFrame(dt, pulse);

    // Schedule next frame if tab visible
    if (!document.hidden) {
      animId = requestAnimationFrame(tick);
    } else {
      animId = null;
    }
  }

  function startLoop() {
    if (animId !== null) return;
    lastTs = null;
    animId = requestAnimationFrame(tick);
  }

  function stopLoop() {
    if (animId !== null) {
      cancelAnimationFrame(animId);
      animId = null;
    }
  }

  // Pause/resume on visibility change
  function onVisibilityChange() {
    if (document.hidden) {
      stopLoop();
    } else if (!REDUCED) {
      startLoop();
    }
  }

  // ---------------------------------------------------------------------------
  // Resize handler (debounced)
  // ---------------------------------------------------------------------------
  function onResize() {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      sizeCanvas();
      initParticles();
      if (REDUCED) {
        renderStatic();
      }
      // If animated loop is running it will pick up new dimensions automatically
    }, C.RESIZE_DEBOUNCE);
  }

  // ---------------------------------------------------------------------------
  // Boot sequence
  // ---------------------------------------------------------------------------
  function runBootSequence() {
    let bootEl     = null;
    let bootTextEl = null;

    try {
      bootEl     = document.getElementById('boot');
      bootTextEl = document.getElementById('boot-text');
    } catch (_) {}

    // Nothing to animate
    if (!bootEl || !bootTextEl) return;

    // Click anywhere on the overlay to skip the boot animation immediately.
    bootEl.style.cursor = 'pointer';
    bootEl.addEventListener('click', function () { hideBoot(bootEl); });

    if (REDUCED) {
      // Show final line immediately, then hide
      try {
        bootTextEl.textContent = C.BOOT_LINES[C.BOOT_LINES.length - 1];
        setTimeout(function () {
          hideBoot(bootEl);
        }, 300);
      } catch (_) {}
      return;
    }

    // Typewriter boot
    let lineIdx  = 0;
    let charIdx  = 0;
    let currentLine = '';

    function typeNextChar() {
      try {
        if (lineIdx >= C.BOOT_LINES.length) {
          // All lines typed — wait, then fade out
          setTimeout(function () { hideBoot(bootEl); }, C.BOOT_HOLD);
          return;
        }

        const line = C.BOOT_LINES[lineIdx];

        if (charIdx === 0 && lineIdx > 0) {
          currentLine += '\n';
        }

        if (charIdx < line.length) {
          currentLine += line[charIdx];
          charIdx++;
          try { bootTextEl.textContent = currentLine; } catch (_) {}
          setTimeout(typeNextChar, C.BOOT_CHAR_DELAY);
        } else {
          // Line complete — pause before next
          lineIdx++;
          charIdx = 0;
          setTimeout(typeNextChar, C.BOOT_LINE_PAUSE);
        }
      } catch (_) {}
    }

    typeNextChar();
  }

  function hideBoot(bootEl) {
    try {
      if (!bootEl) return;
      bootEl.classList.add('done');
      // Fallback if CSS transition not defined
      setTimeout(function () {
        try {
          if (bootEl) bootEl.hidden = true;
        } catch (_) {}
      }, 800);
    } catch (_) {}
  }

  // ---------------------------------------------------------------------------
  // Initialise
  // ---------------------------------------------------------------------------
  function init() {
    try {
      if (!setupCanvas()) {
        // Canvas not found — nothing to do
        return;
      }

      initParticles();

      if (REDUCED) {
        // Static render only — one frame
        renderStatic();
      } else {
        // Kick off animation loop
        startLoop();
        // Hook tab visibility
        try {
          document.addEventListener('visibilitychange', onVisibilityChange);
        } catch (_) {}
      }

      // Resize
      try {
        window.addEventListener('resize', onResize);
      } catch (_) {}

      // Boot sequence (runs independently of canvas)
      runBootSequence();
    } catch (err) {
      // Silently absorb — HUD should never crash the app
      try { console.warn('[hud.js] init error:', err); } catch (_) {}
    }
  }

  // ---------------------------------------------------------------------------
  // Entry point — safe to call before or after DOMContentLoaded
  // ---------------------------------------------------------------------------
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

}());
