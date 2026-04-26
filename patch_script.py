import sys

mystical_engine = """
// --- MYSTICAL UI ENGINE ---
class MysticalEngine {
    constructor() {
        this.webglCanvas = document.getElementById('webgl-cloud');
        this.particleCanvas = document.getElementById('particleCanvas');
        this.textInput = document.getElementById('textInput');
        this.floatingPrompt = document.querySelector('.floating-prompt');
        this.resultsSection = document.getElementById('resultsSection');
        
        if (!this.webglCanvas || !this.particleCanvas) return;
        
        this.initWebGLCloud();
        this.initParticleEngine();
        
        // Handle window resize
        window.addEventListener('resize', () => {
            this.resizeWebGL();
            this.resizeParticleCanvas();
        });
    }
    
    initWebGLCloud() {
        if (typeof THREE === 'undefined') return;
        
        this.scene = new THREE.Scene();
        this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
        this.renderer = new THREE.WebGLRenderer({ canvas: this.webglCanvas, alpha: true, antialias: true });
        this.resizeWebGL();
        
        const fragmentShader = `
            uniform float iTime;
            uniform vec2 iResolution;
            uniform float intensity;
            
            // Noise functions
            vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
            vec2 mod289(vec2 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
            vec3 permute(vec3 x) { return mod289(((x*34.0)+1.0)*x); }
            float snoise(vec2 v) {
                const vec4 C = vec4(0.211324865405187, 0.366025403784439, -0.577350269189626, 0.024390243902439);
                vec2 i  = floor(v + dot(v, C.yy) );
                vec2 x0 = v -   i + dot(i, C.xx);
                vec2 i1; i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
                vec4 x12 = x0.xyxy + C.xxzz;
                x12.xy -= i1;
                i = mod289(i);
                vec3 p = permute( permute( i.y + vec3(0.0, i1.y, 1.0 )) + i.x + vec3(0.0, i1.x, 1.0 ));
                vec3 m = max(0.5 - vec3(dot(x0,x0), dot(x12.xy,x12.xy), dot(x12.zw,x12.zw)), 0.0);
                m = m*m ; m = m*m ;
                vec3 x = 2.0 * fract(p * C.www) - 1.0;
                vec3 h = abs(x) - 0.5;
                vec3 ox = floor(x + 0.5);
                vec3 a0 = x - ox;
                m *= 1.79284291400159 - 0.85373472095314 * ( a0*a0 + h*h );
                vec3 g;
                g.x  = a0.x  * x0.x  + h.x  * x0.y;
                g.yz = a0.yz * x12.xz + h.yz * x12.yw;
                return 130.0 * dot(m, g);
            }
            
            void mainImage( out vec4 fragColor, in vec2 fragCoord ) {
                vec2 uv = fragCoord/iResolution.xy;
                uv.x *= iResolution.x/iResolution.y;
                
                float t = iTime * 0.2;
                
                // Multilayer noise
                float n1 = snoise(uv * 1.5 + vec2(t, t * 0.5));
                float n2 = snoise(uv * 3.0 - vec2(t * 1.2, t * 0.8));
                float n3 = snoise(uv * 5.0 + vec2(t * 0.5, -t));
                
                float n = n1 * 0.5 + n2 * 0.25 + n3 * 0.125;
                n = n * 0.5 + 0.5; // map to 0-1
                
                // Colors (Deep mystical purple/blue/cyan)
                vec3 col1 = vec3(0.38, 0.4, 0.94); // Indigo
                vec3 col2 = vec3(0.66, 0.33, 0.96); // Purple
                vec3 col3 = vec3(0.1, 0.8, 0.9);   // Cyan
                
                vec3 finalCol = mix(col1, col2, smoothstep(0.2, 0.8, n));
                finalCol = mix(finalCol, col3, smoothstep(0.6, 1.0, n) * intensity);
                
                // Masking: dense at bottom, fading up
                float mask = smoothstep(0.8, 0.0, fragCoord.y/iResolution.y);
                mask = pow(mask, 1.5) * (n * 0.5 + 0.5);
                
                fragColor = vec4(finalCol, mask * 0.8);
            }
            
            void main() {
                mainImage(gl_FragColor, gl_FragCoord.xy);
            }
        `;
        
        this.uniforms = {
            iTime: { value: 0 },
            iResolution: { value: new THREE.Vector2() },
            intensity: { value: 0.2 }
        };
        
        const geometry = new THREE.PlaneGeometry(2, 2);
        const material = new THREE.ShaderMaterial({
            fragmentShader,
            uniforms: this.uniforms,
            transparent: true,
            depthWrite: false
        });
        
        const mesh = new THREE.Mesh(geometry, material);
        this.scene.add(mesh);
        
        this.clock = new THREE.Clock();
        this.animateWebGL();
    }
    
    resizeWebGL() {
        if (!this.renderer) return;
        this.renderer.setSize(window.innerWidth, window.innerHeight);
        this.uniforms.iResolution.value.set(window.innerWidth, window.innerHeight);
    }
    
    animateWebGL() {
        requestAnimationFrame(() => this.animateWebGL());
        this.uniforms.iTime.value = this.clock.getElapsedTime();
        this.renderer.render(this.scene, this.camera);
    }
    
    setCloudIntensity(high) {
        if (!this.uniforms) return;
        // Tween intensity
        const target = high ? 1.0 : 0.2;
        const current = this.uniforms.intensity.value;
        const step = (target - current) * 0.05;
        
        const tween = () => {
            this.uniforms.intensity.value += step;
            if (Math.abs(this.uniforms.intensity.value - target) > 0.01) {
                requestAnimationFrame(tween);
            } else {
                this.uniforms.intensity.value = target;
            }
        };
        tween();
    }

    // --- PARTICLE SHATTER EFFECT ---
    initParticleEngine() {
        this.ctx = this.particleCanvas.getContext('2d', { willReadFrequently: true });
        this.particles = [];
        this.resizeParticleCanvas();
    }
    
    resizeParticleCanvas() {
        this.particleCanvas.width = window.innerWidth;
        this.particleCanvas.height = window.innerHeight;
    }
    
    shatterText(textElement, onComplete) {
        if (this.floatingPrompt) {
            this.floatingPrompt.classList.add('shattering');
        }
        
        this.setCloudIntensity(true); // Intensify cloud during processing
        
        const rect = textElement.getBoundingClientRect();
        const computedStyle = window.getComputedStyle(textElement);
        
        // Draw the text onto a temporary canvas to get pixels
        const tempCanvas = document.createElement('canvas');
        tempCanvas.width = rect.width;
        tempCanvas.height = rect.height;
        const tCtx = tempCanvas.getContext('2d');
        
        tCtx.font = computedStyle.font;
        tCtx.fillStyle = '#ffffff'; // White particles
        tCtx.textBaseline = 'top';
        
        // Simple word wrapping for drawing
        const words = textElement.value.split(' ');
        let line = '';
        let y = parseInt(computedStyle.paddingTop) || 0;
        const x = parseInt(computedStyle.paddingLeft) || 0;
        const lineHeight = parseInt(computedStyle.lineHeight) || 24;
        
        for(let n = 0; n < words.length; n++) {
            let testLine = line + words[n] + ' ';
            let metrics = tCtx.measureText(testLine);
            let testWidth = metrics.width;
            if (testWidth > rect.width - x*2 && n > 0) {
                tCtx.fillText(line, x, y);
                line = words[n] + ' ';
                y += lineHeight;
            } else {
                line = testLine;
            }
        }
        tCtx.fillText(line, x, y);
        
        // Extract pixels
        const imgData = tCtx.getImageData(0, 0, tempCanvas.width, tempCanvas.height).data;
        this.particles = [];
        
        const offsetX = rect.left;
        const offsetY = rect.top;
        
        // Create particles (sampling every 2nd pixel for performance)
        for (let py = 0; py < tempCanvas.height; py += 2) {
            for (let px = 0; px < tempCanvas.width; px += 2) {
                const index = (py * tempCanvas.width + px) * 4;
                const alpha = imgData[index + 3];
                if (alpha > 128) {
                    this.particles.push({
                        x: offsetX + px,
                        y: offsetY + py,
                        vx: (Math.random() - 0.5) * 2,
                        vy: (Math.random() * -3) - 1, // Move up
                        life: 1.0,
                        decay: Math.random() * 0.015 + 0.01,
                        size: Math.random() * 1.5 + 0.5
                    });
                }
            }
        }
        
        this.animatingParticles = true;
        this.animateParticles();
        
        // Allow API call to proceed
        if (onComplete) setTimeout(onComplete, 500); 
    }
    
    animateParticles() {
        if (!this.animatingParticles) return;
        
        this.ctx.clearRect(0, 0, this.particleCanvas.width, this.particleCanvas.height);
        
        let activeParticles = 0;
        this.ctx.fillStyle = '#ffffff';
        this.ctx.beginPath();
        
        for (let i = 0; i < this.particles.length; i++) {
            let p = this.particles[i];
            if (p.life <= 0) continue;
            
            activeParticles++;
            p.x += p.vx;
            p.y += p.vy;
            p.vx += (Math.random() - 0.5) * 0.5; // Swirl
            p.vy -= 0.05; // Accelerate upwards
            p.life -= p.decay;
            
            this.ctx.globalAlpha = p.life;
            this.ctx.moveTo(p.x, p.y);
            this.ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        }
        
        this.ctx.fill();
        this.ctx.globalAlpha = 1.0;
        
        if (activeParticles > 0) {
            requestAnimationFrame(() => this.animateParticles());
        } else {
            this.animatingParticles = false;
        }
    }
    
    triggerReveal() {
        this.setCloudIntensity(false);
        if (this.resultsSection) {
            // Remove class to reset animation, force reflow, add class back
            this.resultsSection.classList.remove('revealing');
            void this.resultsSection.offsetWidth;
            this.resultsSection.classList.add('revealing');
        }
    }
    
    resetInput() {
        if (this.floatingPrompt) {
            this.floatingPrompt.classList.remove('shattering');
        }
        this.setCloudIntensity(false);
    }
}

const mysticalEngine = new MysticalEngine();
// ----------------------------
"""

with open('script.js', 'r') as f:
    content = f.read()

# Replace the ambient gradient logic with mystical engine hooks
content = content.replace(
    """        // Ambient gradient interaction & auto-resize textarea
        const updateGradient = () => {
            if (this.ambientGradient) {
                if (this.textInput.value.trim().length > 0 || document.activeElement === this.textInput) {
                    this.ambientGradient.classList.add('active');
                } else {
                    this.ambientGradient.classList.remove('active');
                }
            }
        };
        this.textInput.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = (Math.min(this.scrollHeight, 200)) + 'px';
            updateGradient();
        });
        this.textInput.addEventListener('focus', updateGradient);
        this.textInput.addEventListener('blur', updateGradient);""",
    """        // Auto-resize textarea
        this.textInput.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = (Math.min(this.scrollHeight, 200)) + 'px';
        });"""
)

# Intercept handleFactCheck to trigger shatter first
handle_check_orig = """    async handleFactCheck() {
        const text = this.textInput.value.trim();
        const hasImage = Boolean(this.imageDataUrl);

        if (!text && !hasImage) {
            alert('Please enter text/URL or upload an image.');
            return;
        }

        this.showLoading();"""

handle_check_new = """    async handleFactCheck() {
        const text = this.textInput.value.trim();
        const hasImage = Boolean(this.imageDataUrl);

        if (!text && !hasImage) {
            alert('Please enter text/URL or upload an image.');
            return;
        }

        // Trigger the magical text shatter animation first
        if (text && typeof mysticalEngine !== 'undefined') {
            mysticalEngine.shatterText(this.textInput, () => this.executeFactCheck(text, hasImage));
        } else {
            this.executeFactCheck(text, hasImage);
        }
    }
    
    async executeFactCheck(text, hasImage) {
        this.showLoading();"""

content = content.replace(handle_check_orig, handle_check_new)

# Hook reveal animation
display_res_orig = """        this.resultsSection.classList.remove('hidden');
        this.resultsSection.scrollIntoView({ behavior: 'smooth' });
    }"""

display_res_new = """        this.resultsSection.classList.remove('hidden');
        
        // Trigger cinematic reveal
        if (typeof mysticalEngine !== 'undefined') {
            mysticalEngine.triggerReveal();
        }
        
        this.resultsSection.scrollIntoView({ behavior: 'smooth' });
    }"""

content = content.replace(display_res_orig, display_res_new)

# Hook reset
clear_orig = """    handleClear() {
        this.textInput.value = '';
        this.textInput.style.height = 'auto';
        this.hideResults();
        if (this.welcomeSection) this.welcomeSection.classList.remove('hidden');
        if (this.ambientGradient) this.ambientGradient.classList.remove('active');
        this.textInput.focus();
    }"""

clear_new = """    handleClear() {
        this.textInput.value = '';
        this.textInput.style.height = 'auto';
        this.hideResults();
        if (this.welcomeSection) this.welcomeSection.classList.remove('hidden');
        
        if (typeof mysticalEngine !== 'undefined') {
            mysticalEngine.resetInput();
        }
        this.textInput.focus();
    }"""

content = content.replace(clear_orig, clear_new)

# Append mystical engine code
content = content.replace("// Initialize the app when page loads", mystical_engine + "\n// Initialize the app when page loads")

with open('script.js', 'w') as f:
    f.write(content)
