class FactCheckerApp {
    constructor() {
        this.apiUrl = '/api';   // Use API routes for Vercel serverless functions
        this.initializeElements();
        this.bindEvents();
        this.initializeTheme();
    }

    initializeElements() {
        this.textInput = document.getElementById('textInput');
        this.factCheckBtn = document.getElementById('factCheckBtn');
        this.clearBtn = document.getElementById('clearBtn');
        this.loadingSection = document.getElementById('loadingSection');
        this.resultsSection = document.getElementById('resultsSection');
        this.resultsContainer = document.getElementById('resultsContainer');
        this.themeToggle = document.getElementById('themeToggle');
        this.imageDrop = document.getElementById('imageDrop');
        this.imageInput = document.getElementById('imageInput');
        this.imagePreview = document.getElementById('imagePreview');
        this.analyzeImageBtn = null;
    }

    bindEvents() {
        this.factCheckBtn.addEventListener('click', () => this.handleFactCheck());
        this.clearBtn.addEventListener('click', () => this.handleClear());
        if (this.themeToggle) {
            this.themeToggle.addEventListener('click', () => this.toggleTheme());
        }
        if (this.imageDrop) {
            this.imageDrop.addEventListener('click', () => this.imageInput.click());
            this.imageDrop.addEventListener('dragover', (e) => { e.preventDefault(); });
            this.imageDrop.addEventListener('drop', (e) => {
                e.preventDefault();
                const files = Array.from(e.dataTransfer.files || []).filter(f => f.type.startsWith('image/'));
                if (files.length) this.loadImages(files);
            });
        }
        if (this.imageInput) {
            this.imageInput.addEventListener('change', (e) => {
                const files = Array.from(e.target.files || []).filter(f => f.type.startsWith('image/'));
                if (files.length) this.loadImages(files);
            });
        }
        // single button handles both
        
        // Allow Enter+Ctrl to trigger fact check
        this.textInput.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.key === 'Enter') {
                this.handleFactCheck();
            }
        });
    }

    async loadImages(files) {
        // Single image for now
        const file = files[0];
        
        // Check file size (limit to 5MB)
        if (file.size > 5 * 1024 * 1024) {
            alert('Image file is too large. Please use an image smaller than 5MB.');
            return;
        }
        
        const reader = new FileReader();
        reader.onload = () => {
            this.imageDataUrl = reader.result;
            console.log('Image loaded, size:', this.imageDataUrl.length, 'characters');
            this.renderImagePreview(this.imageDataUrl);
        };
        reader.readAsDataURL(file);
    }

    renderImagePreview(dataUrl) {
        if (!this.imagePreview) return;
        this.imagePreview.classList.remove('hidden');
        this.imagePreview.innerHTML = `
            <div class="thumb">
                <img src="${this.escapeAttribute(dataUrl)}" alt="Uploaded image preview" />
                <button class="remove" aria-label="Remove image">Remove</button>
            </div>
        `;
        this.imagePreview.querySelector('.remove').addEventListener('click', () => {
            this.imageDataUrl = null;
            this.imagePreview.classList.add('hidden');
            this.imagePreview.innerHTML = '';
            this.updateFactCheckButtonState();
        });
        this.updateFactCheckButtonState();
    }

    async handleAnalyzeImage() { /* deprecated - unified into handleFactCheck */ }

    initializeTheme() {
        const html = document.documentElement;
        const stored = localStorage.getItem('ai-fc-theme');
        const current = html.getAttribute('data-theme') || stored || 'light';
        this.applyTheme(current);
        // Reveal icon after initial theme applied (avoid FOUC)
        const icon = document.querySelector('.icon-btn i');
        if (icon) icon.style.visibility = 'visible';

        // If no stored preference, follow system changes
        if (!stored && window.matchMedia) {
            const mm = window.matchMedia('(prefers-color-scheme: dark)');
            if (mm.addEventListener) {
                mm.addEventListener('change', (e) => {
                    if (!localStorage.getItem('ai-fc-theme')) {
                        this.applyTheme(e.matches ? 'dark' : 'light');
                    }
                });
            } else if (mm.addListener) {
                // Safari
                mm.addListener((e) => {
                    if (!localStorage.getItem('ai-fc-theme')) {
                        this.applyTheme(e.matches ? 'dark' : 'light');
                    }
                });
            }
        }
    }

    applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        this.updateThemeIcon(theme);
    }

    toggleTheme() {
        const current = document.documentElement.getAttribute('data-theme') || 'light';
        const next = current === 'dark' ? 'light' : 'dark';
        this.applyTheme(next);
        try { localStorage.setItem('ai-fc-theme', next); } catch (_) {}
    }

    updateThemeIcon(theme) {
        if (!this.themeToggle) return;
        const icon = this.themeToggle.querySelector('i');
        if (!icon) return;
        icon.className = `fas ${theme === 'dark' ? 'fa-sun' : 'fa-moon'}`;
        this.themeToggle.setAttribute('aria-label', `Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`);
        this.themeToggle.title = `Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`;
    }

     updateFactCheckButtonState() {
        if (!this.factCheckBtn) return;
        const hasImage = Boolean(this.imageDataUrl);
        const icon = this.factCheckBtn.querySelector('i');
        const label = this.factCheckBtn.querySelector('.btn-label');
        if (icon) icon.className = `fas ${hasImage ? 'fa-photo-film' : 'fa-magnifying-glass'}`;
        if (label) label.textContent = hasImage ? 'Analyze Image' : 'Fact Check Now';
    }

    async handleFactCheck() {
        const text = this.textInput.value.trim();
        const hasImage = Boolean(this.imageDataUrl);

        if (!text && !hasImage) {
            alert('Please enter text/URL or upload an image.');
            return;
        }

        this.showLoading();
        try {
            let response;
            if (hasImage) {
                console.log('Sending image for analysis...');
                const payload = { image_data_url: this.imageDataUrl };
                console.log('Payload size:', JSON.stringify(payload).length, 'characters');
                
                response = await fetch(`${this.apiUrl}/api/fact-check-image`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                
                console.log('Response status:', response.status);
                console.log('Response headers:', Object.fromEntries(response.headers.entries()));
            } else {
                const payload = this.buildPayload(text);
                response = await fetch(`${this.apiUrl}/fact-check`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
            }

            if (!response.ok) {
                const errorText = await response.text();
                console.error('HTTP Error:', response.status, errorText);
                throw new Error(`HTTP ${response.status}: ${errorText}`);
            }
            
            const data = await response.json();
            console.log('Response data:', data);

            this.displayResults(data);
        } catch (error) {
            console.error('Fact-check error:', error);
            this.showError(`Failed to fact-check: ${error.message}`);
        } finally {
            this.hideLoading();
        }
    }

    buildPayload(input) {
        const isLikelyUrl = /^(https?:\/\/)[\w.-]+(?:\.[\w\.-]+)+(?:[\w\-\._~:\/?#\[\]@!$&'()*+,;=.]+)?$/i.test(input);
        if (isLikelyUrl) {
            return { url: input };
        }
        return { text: input };
    }

    handleClear() {
        this.textInput.value = '';
        this.hideResults();
        this.textInput.focus();
    }

    showLoading() {
        this.loadingSection.classList.remove('hidden');
        this.resultsSection.classList.add('hidden');
        this.factCheckBtn.disabled = true;
    }

    hideLoading() {
        this.loadingSection.classList.add('hidden');
        this.factCheckBtn.disabled = false;
        this.updateFactCheckButtonState();
    }

    hideResults() {
        this.resultsSection.classList.add('hidden');
    }

    displayResults(data) {

        this.resultsContainer.innerHTML = '';
        
        if (data.source_url) {
            const src = document.createElement('div');
            src.className = 'source-banner';
            src.innerHTML = `
                <i class="fas fa-link"></i>
                <span>Source:</span>
                <a href="${data.source_url}" target="_blank" rel="noopener">${data.source_url}</a>
            `;
            this.resultsContainer.appendChild(src);
            if (data.source_title) {
                const title = document.createElement('div');
                title.style.margin = '6px 0 10px';
                title.style.color = 'var(--muted)';
                title.style.fontSize = '0.95rem';
                title.innerHTML = `<i class="fas fa-file-lines"></i> <strong>Title:</strong> ${data.source_title}`;
                this.resultsContainer.appendChild(title);
            }
        }

        if (!data.fact_check_results || data.fact_check_results.length === 0) {

            this.resultsContainer.innerHTML = '<p>No factual claims found to verify.</p>';
        } else {
            data.fact_check_results.forEach((result, index) => {
                const claimElement = this.createClaimElement(result, index + 1);
                this.resultsContainer.appendChild(claimElement);
            });
        }
        
        this.resultsSection.classList.remove('hidden');
        this.resultsSection.scrollIntoView({ behavior: 'smooth' });
    }

    createClaimElement(result, index) {
        const div = document.createElement('div');
        
        // Safety check for result structure
        if (!result || !result.result) {
            div.innerHTML = `
                <div class="claim-result partial">
                    <div class="explanation">
                        <i class="fas fa-exclamation-triangle"></i>
                        <strong>Error:</strong> Invalid result structure received from API
                    </div>
                </div>
            `;
            return div;
        }
        
        const verdict = result.result.verdict ? result.result.verdict.toLowerCase() : 'unknown';
        const verdictClass = this.getVerdictClass(verdict);
        
        div.className = `claim-result ${verdictClass}`;
        
        // Format the explanation nicely instead of showing raw JSON
        let explanation = result.result.explanation || 'No explanation provided';
        let extractedSources = result.result.sources || [];
        
        const sourcesHtml = this.renderSources(extractedSources);
        
        if (typeof explanation === 'string') {
            // Check if explanation contains JSON-like content
            if (explanation.includes('"verdict"') || explanation.includes('"confidence"') || explanation.includes('"explanation"')) {
                try {
                    // Try to extract JSON from the explanation
                    let jsonStr = explanation;
                    
                    // Remove "json " prefix if present
                    if (explanation.startsWith('json ')) {
                        jsonStr = explanation.substring(5);
                    }
                    
                    // Try to parse as JSON
                    const parsed = JSON.parse(jsonStr);
                    if (parsed.explanation) {
                        explanation = parsed.explanation;
                    } else if (parsed.verdict) {
                        // If no explanation field, create one from other fields
                        explanation = `Verdict: ${parsed.verdict}`;
                        if (parsed.confidence) {
                            explanation += ` (Confidence: ${parsed.confidence}%)`;
                        }
                    }
                    
                    // Extract sources from the parsed JSON if available
                    if (parsed.sources && Array.isArray(parsed.sources) && parsed.sources.length > 0) {
                        extractedSources = parsed.sources;
                    }
                } catch (e) {
                    // If parsing fails, clean up the explanation by removing JSON artifacts
                    explanation = explanation
                        .replace(/^json\s*/, '') // Remove "json " prefix
                        .replace(/[{}"]/g, '') // Remove braces and quotes
                        .replace(/,/g, ', ') // Replace commas with comma + space
                        .replace(/verdict:\s*/gi, '') // Remove "verdict:" labels
                        .replace(/confidence:\s*\d+/gi, '') // Remove confidence labels
                        .replace(/sources:\s*\[.*?\]/gi, '') // Remove sources array
                        .replace(/\s+/g, ' ') // Normalize whitespace
                        .trim();
                    
                    // Try to extract URLs from the cleaned explanation as fallback sources
                    const urlMatches = explanation.match(/https?:\/\/[^\s]+/g);
                    if (urlMatches && urlMatches.length > 0) {
                        extractedSources = urlMatches;
                    }
                }
            }
        }
        
        div.innerHTML = `
            <div class="claim-text">
                <strong>Claim ${index}:</strong> ${this.escapeHtml(result.claim || 'Unknown claim')}
            </div>
            

            
            <div class="verdict ${verdictClass}">
                ${this.escapeHtml(result.result.verdict || 'UNKNOWN')}
            </div>
            
            <div class="confidence">
                <i class="fas fa-chart-bar"></i>
                <strong>Confidence:</strong> ${this.escapeHtml(String(result.result.confidence || 'N/A'))}%
            </div>
            
            <div class="explanation">
                <i class="fas fa-info-circle"></i>
                <strong>Analysis:</strong> ${this.escapeHtml(explanation)}
            </div>
            ${sourcesHtml}
        `;
        
        return div;
    }

    getVerdictClass(verdict) {
        if (verdict.includes('true') && !verdict.includes('false')) {
            return 'true';
        } else if (verdict.includes('false')) {
            return 'false';
        } else if (verdict.includes('partial')) {
            return 'partial';
        }
        return 'partial';
    }

    escapeHtml(str) {
        if (str == null) return '';
        return String(str)
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#039;');
    }

    renderSources(sources) {
        if (!Array.isArray(sources) || sources.length === 0) return '';
        const items = sources
            .map(s => typeof s === 'string' ? s.trim() : '')
            .filter(Boolean)
            .map((url, i) => {
                const safeUrl = this.escapeAttribute(url);
                const label = this.humanizeSource(url, i + 1);
                return `<a href="${safeUrl}" target="_blank" rel="noopener" class="source-link">${label}</a>`;
            })
            .join(', ');
        return `
            <div class="sources">
                <i class="fas fa-link"></i>
                <strong>Sources:</strong> ${items}
            </div>
        `;
    }

    escapeAttribute(str) {
        return this.escapeHtml(str).replaceAll('"', '&quot;');
    }

    humanizeSource(url, index) {
        try {
            const u = new URL(url);
            const host = u.hostname.replace(/^www\./, '');
            let path = u.pathname.replace(/\/$/, '');
            if (path.length > 28) path = path.slice(0, 25) + '…';
            return `${host}${path ? ' ' + path : ''}`;
        } catch (_) {
            return `Source ${index}`;
        }
    }

    showError(message) {
        this.resultsContainer.innerHTML = `
            <div class="claim-result false">
                <div class="explanation">
                    <i class="fas fa-exclamation-triangle"></i>
                    <strong>Error:</strong> ${message}
                </div>
            </div>
        `;
        this.resultsSection.classList.remove('hidden');
    }
}

// Initialize the app when page loads
document.addEventListener('DOMContentLoaded', () => {
    new FactCheckerApp();
});
