import sys

with open('style.css', 'r') as f:
    content = f.read()

# Replace ambient-gradient with webgl-cloud and particle-canvas
ambient_css = """/* Ambient Gradient Background */
.ambient-gradient {
  position: absolute;
  bottom: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 100vw;
  height: 60vh;
  background: radial-gradient(circle at 50% 100%, var(--grad-1) 0%, var(--grad-2) 35%, var(--grad-3) 70%, transparent 100%);
  filter: blur(80px);
  opacity: 0.5;
  pointer-events: none;
  z-index: 0;
  transition: all 0.8s cubic-bezier(0.16, 1, 0.3, 1);
  animation: breathe 8s ease-in-out infinite alternate;
}

.ambient-gradient.active {
  height: 75vh;
  opacity: 0.85;
  filter: blur(60px);
  animation: typing-pulse 3s ease-in-out infinite alternate;
}

@keyframes breathe {
  0% { transform: translateX(-50%) scale(1); opacity: 0.4; }
  100% { transform: translateX(-50%) scale(1.05); opacity: 0.6; }
}

@keyframes typing-pulse {
  0% { transform: translateX(-50%) scale(1.05); opacity: 0.7; }
  100% { transform: translateX(-50%) scale(1.1); opacity: 0.9; }
}"""

mystical_css = """/* Mystical Cloud WebGL & Particle Canvases */
.webgl-cloud {
  position: absolute;
  bottom: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  pointer-events: none;
  z-index: 0;
  opacity: 0.6;
  transition: opacity 2s ease;
  mix-blend-mode: screen;
}

[data-theme="light"] .webgl-cloud {
  mix-blend-mode: multiply;
  opacity: 0.3;
}

.particle-canvas {
  position: absolute;
  bottom: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  pointer-events: none;
  z-index: 10;
}

/* Cinematic Reveal Animation */
.results-section.revealing {
  animation: ethereal-reveal 2.5s cubic-bezier(0.2, 0.8, 0.2, 1) forwards;
}

@keyframes ethereal-reveal {
  0% { opacity: 0; filter: blur(20px); transform: translateY(40px) scale(0.95); }
  40% { opacity: 0.5; filter: blur(10px); transform: translateY(10px) scale(0.98); }
  100% { opacity: 1; filter: blur(0); transform: translateY(0) scale(1); }
}"""

content = content.replace(ambient_css, mystical_css)

# Replace glass-panel with floating-prompt
glass_css = """.glass-panel {
  max-width: 768px;
  margin: 0 auto;
  background: var(--glass-bg);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow);
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
}"""

floating_css = """.glass-panel {
  max-width: 768px;
  margin: 0 auto;
  background: var(--glass-bg);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow);
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
}

.floating-prompt {
  max-width: 768px;
  margin: 0 auto;
  background: transparent;
  border: none;
  border-radius: var(--radius-lg);
  transition: all 0.3s ease;
}

.floating-prompt .prompt-input {
  font-size: 1.15rem;
  letter-spacing: 0.01em;
  text-shadow: 0 0 10px rgba(255,255,255,0.2);
  caret-color: var(--primary);
}

.floating-prompt.shattering .prompt-input {
  color: transparent !important;
  text-shadow: none !important;
  caret-color: transparent;
}"""

content = content.replace(glass_css, floating_css)

with open('style.css', 'w') as f:
    f.write(content)
