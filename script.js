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
        this.ambientGradient = document.getElementById('ambientGradient');
        this.welcomeSection = document.getElementById('welcomeSection');
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

        // Ambient gradient interaction & auto-resize textarea
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
        this.textInput.addEventListener('blur', updateGradient);
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
        if (icon) icon.className = `fas fa-arrow-up`;
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
                
                const url = `${this.apiUrl}/fact-check-image`;
                console.log('Calling URL:', url);
                console.log('API URL base:', this.apiUrl);
                
                response = await fetch(url, {
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
        const trimmed = input.trim();
        if (!trimmed) return { text: '' };

        const hasScheme = /^https?:\/\//i.test(trimmed);
        const noSpaces = !/\s/.test(trimmed);
        const looksLikeDomain = /^[\w.-]+\.[a-z]{2,}(?::\d+)?(?:[\/?#].*)?$/i.test(trimmed);

        if (hasScheme || (noSpaces && looksLikeDomain)) {
            const url = hasScheme ? trimmed : `https://${trimmed}`;
            return { url };
        }

        return { text: trimmed };
    }

    handleClear() {
        this.textInput.value = '';
        this.textInput.style.height = 'auto';
        this.hideResults();
        if (this.welcomeSection) this.welcomeSection.classList.remove('hidden');
        if (this.ambientGradient) this.ambientGradient.classList.remove('active');
        this.textInput.focus();
    }

    showLoading() {
        if (this.welcomeSection) this.welcomeSection.classList.add('hidden');
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
            if (typeof data.images_detected === 'number' && data.images_detected >= 0) {
                const imgInfo = document.createElement('div');
                imgInfo.style.margin = '4px 0 12px';
                imgInfo.style.color = 'var(--muted)';
                imgInfo.style.fontSize = '0.9rem';
                
                // Check if images were detected but not accessible
                if (data.images_detected === 0 && data.image_detection_info && data.image_detection_info.image_detected) {
                    imgInfo.innerHTML = `<i class="fas fa-image"></i> <strong>Images detected:</strong> Images found in this post, but they cannot be accessed directly from the URL.`;
                    imgInfo.style.color = 'var(--warning)';
                } else if (data.image_analysis_skipped_reason) {
                    imgInfo.innerHTML = `<i class="fas fa-image"></i> <strong>Images detected:</strong> ${data.images_detected}. Visual analysis skipped.`;
                } else if (data.image_analysis_error) {
                    imgInfo.innerHTML = `<i class="fas fa-image"></i> <strong>Images detected:</strong> ${data.images_detected}. Visual analysis could not complete.`;
                    imgInfo.style.color = 'var(--warning)';
                } else {
                    imgInfo.innerHTML = `<i class="fas fa-image"></i> <strong>Images detected:</strong> ${data.images_detected}. ${data.images_detected > 0 ? 'Visual content was considered in the analysis.' : 'No images detected.'}`;
                }
                this.resultsContainer.appendChild(imgInfo);
                
                const imageMessage = data.image_analysis_error || data.image_detection_message || data.image_analysis_skipped_reason;
                if (imageMessage) {
                    const msgDiv = document.createElement('div');
                    msgDiv.style.margin = '8px 0 12px';
                    msgDiv.style.padding = '8px 12px';
                    msgDiv.style.backgroundColor = data.image_analysis_skipped_reason ? 'rgba(255,255,255,0.04)' : 'var(--warning-bg)';
                    msgDiv.style.border = data.image_analysis_skipped_reason ? '1px solid var(--border)' : '1px solid var(--warning)';
                    msgDiv.style.borderRadius = '6px';
                    msgDiv.style.color = data.image_analysis_skipped_reason ? 'var(--muted)' : 'var(--warning)';
                    msgDiv.style.fontSize = '0.9rem';
                    msgDiv.innerHTML = `<i class="fas fa-info-circle"></i> ${this.escapeHtml(imageMessage)}`;
                    this.resultsContainer.appendChild(msgDiv);
                }
            }
            const selected = data.selected_image_url || (Array.isArray(data.debug_image_urls) && data.debug_image_urls.length ? data.debug_image_urls[0] : null);
            if (selected) {
                const thumbWrap = document.createElement('div');
                thumbWrap.style.margin = '6px 0 14px';
                thumbWrap.innerHTML = `
                    <div style="display:flex;align-items:center;gap:10px;">
                        <img src="${this.escapeAttribute(selected)}" alt="Analyzed image" style="max-height:80px;border-radius:6px;border:1px solid var(--border);"/>
                        <a href="${this.escapeAttribute(selected)}" target="_blank" rel="noopener" class="source-link">
                            <i class="fas fa-up-right-from-square"></i> Open analyzed image
                        </a>
                    </div>
                `;
                this.resultsContainer.appendChild(thumbWrap);
            }
        }

        if (data.analysis_error) {
            const msgDiv = document.createElement('div');
            msgDiv.style.margin = '8px 0 12px';
            msgDiv.style.padding = '8px 12px';
            msgDiv.style.backgroundColor = 'var(--warning-bg)';
            msgDiv.style.border = '1px solid var(--warning)';
            msgDiv.style.borderRadius = '6px';
            msgDiv.style.color = 'var(--warning)';
            msgDiv.style.fontSize = '0.9rem';
            msgDiv.innerHTML = `<i class="fas fa-info-circle"></i> ${this.escapeHtml(data.analysis_error)}`;
            this.resultsContainer.appendChild(msgDiv);
        }

        if (!data.fact_check_results || data.fact_check_results.length === 0) {
            const empty = document.createElement('p');
            empty.textContent = data.analysis_error ? 'Analysis could not complete.' : 'No factual claims found to verify.';
            this.resultsContainer.appendChild(empty);
        } else {
            let allClaims = [];
            data.fact_check_results.forEach((result) => {
                const subClaims = this.extractSubClaims(result);
                if (subClaims && subClaims.length > 0) {
                    allClaims.push(...subClaims);
                } else {
                    allClaims.push(result);
                }
            });

            allClaims.forEach((result, index) => {
                const claimElement = this.createClaimElement(result, index + 1);
                this.resultsContainer.appendChild(claimElement);
            });
        }
        
        this.resultsSection.classList.remove('hidden');
        this.resultsSection.scrollIntoView({ behavior: 'smooth' });
    }

    extractSubClaims(result) {
        if (!result || !result.result || !result.result.explanation) return null;
        
        let exp = result.result.explanation;
        if (typeof exp !== 'string') return null;

        try {
            let jsonStr = exp;
            
            if (jsonStr.includes('```')) {
                const match = jsonStr.match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
                if (match && match[1]) {
                    jsonStr = match[1];
                }
            }
            
            if (jsonStr.trim().startsWith('json ')) {
                jsonStr = jsonStr.trim().substring(5);
            }

            const processParsedJson = (parsed) => {
                let claimsArray = null;
                if (Array.isArray(parsed)) {
                    claimsArray = parsed;
                } else if (parsed.claims && Array.isArray(parsed.claims)) {
                    claimsArray = parsed.claims;
                } else if (parsed.fact_check_results && Array.isArray(parsed.fact_check_results)) {
                    claimsArray = parsed.fact_check_results;
                }
                
                if (claimsArray && claimsArray.length > 0 && claimsArray[0].claim) {
                    return claimsArray.map(c => {
                        return {
                            claim: c.claim,
                            result: {
                                verdict: c.verdict || (c.result && c.result.verdict) || 'UNKNOWN',
                                explanation: c.explanation || (c.result && c.result.explanation) || '',
                                confidence: c.confidence || (c.result && c.result.confidence) || result.result.confidence || null,
                                sources: c.sources || (c.result && c.result.sources) || result.result.sources || []
                            }
                        };
                    });
                }
                return null;
            };

            try {
                return processParsedJson(JSON.parse(jsonStr));
            } catch (e) {
                let firstBrace = jsonStr.indexOf('{');
                let firstBracket = jsonStr.indexOf('[');
                let startIdx = -1;
                
                if (firstBrace !== -1 && firstBracket !== -1) startIdx = Math.min(firstBrace, firstBracket);
                else if (firstBrace !== -1) startIdx = firstBrace;
                else if (firstBracket !== -1) startIdx = firstBracket;
                
                if (startIdx !== -1) {
                    let lastBrace = jsonStr.lastIndexOf('}');
                    let lastBracket = jsonStr.lastIndexOf(']');
                    let endIdx = -1;
                    
                    if (lastBrace !== -1 && lastBracket !== -1) endIdx = Math.max(lastBrace, lastBracket);
                    else if (lastBrace !== -1) endIdx = lastBrace;
                    else if (lastBracket !== -1) endIdx = lastBracket;
                    
                    if (endIdx > startIdx) {
                        let cleanJson = jsonStr.substring(startIdx, endIdx + 1);
                        cleanJson = cleanJson.replace(/\n/g, '\\n').replace(/\r/g, '\\r');
                        try {
                            return processParsedJson(JSON.parse(cleanJson));
                        } catch (innerE) {
                            try {
                                let fixedJson = cleanJson.replace(/,\s*([}\]])/g, '$1');
                                return processParsedJson(JSON.parse(fixedJson));
                            } catch (e3) {}
                        }
                    }
                }
            }
        } catch (e) {
            console.error("Error extracting sub-claims", e);
        }
        return null;
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
            if (explanation.trim().startsWith('{') || explanation.trim().startsWith('[')) {
                try {
                    let jsonStr = explanation;
                    if (explanation.startsWith('json ')) {
                        jsonStr = explanation.substring(5);
                    }
                    const parsed = JSON.parse(jsonStr);
                    if (parsed.explanation) {
                        explanation = parsed.explanation;
                    } else if (parsed.verdict) {
                        explanation = `Verdict: ${parsed.verdict}`;
                        if (parsed.confidence) {
                            explanation += ` (Confidence: ${parsed.confidence}%)`;
                        }
                    }
                    
                    if (parsed.sources && Array.isArray(parsed.sources) && parsed.sources.length > 0) {
                        extractedSources = parsed.sources;
                    }
                } catch (e) {
                    // Do not aggressively strip brackets and braces if JSON parse fails.
                    // Instead, keep the raw explanation as is, but remove any wrapping markdown.
                    explanation = explanation
                        .replace(/^```(?:json)?\s*/i, '')
                        .replace(/\s*```$/i, '')
                        .trim();
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
        verdict = verdict.toLowerCase();
        if (verdict.includes('partial')) {
            return 'partial';
        } else if (verdict.includes('true') && !verdict.includes('false')) {
            return 'true';
        } else if (verdict.includes('false')) {
            return 'false';
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
