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
        this.bottomArea = document.querySelector('.bottom-area');
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
        
        // Allow Enter to trigger fact check
        this.textInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.handleFactCheck();
            }
        });

        // Also allow Enter to send if focus is on the prompt container
        // when image is loaded and textarea is hidden
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey && this.imageDataUrl) {
                const active = document.activeElement;
                if (active && (active.classList.contains('remove') || active.id === 'clearBtn' || active.id === 'themeToggle')) {
                    return; // Let the focused button handle its own click
                }
                e.preventDefault();
                this.handleFactCheck();
            }
        });

        // Handle pasting images
        document.addEventListener('paste', (e) => {
            // Ignore if pasting into a specific input that might want text
            // But actually we want to catch it globally if it's an image.
            const items = (e.clipboardData || e.originalEvent.clipboardData).items;
            const files = [];
            for (let index in items) {
                const item = items[index];
                if (item.kind === 'file' && item.type.startsWith('image/')) {
                    files.push(item.getAsFile());
                }
            }
            if (files.length > 0) {
                e.preventDefault();
                this.loadImages(files);
            }
        });

        // Auto-resize textarea
        this.textInput.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = (Math.min(this.scrollHeight, 200)) + 'px';
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
        this.imagePreview.style.opacity = '';
        this.imagePreview.style.transition = '';
        this.imagePreview.classList.remove('hidden');
        if (this.textInput) {
            this.textInput.style.display = 'none';
        }
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
            if (this.textInput) {
                this.textInput.style.display = '';
            }
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

        // Trigger the magical text shatter animation first
        if (hasImage && typeof mysticalEngine !== 'undefined') {
            const imgElement = this.imagePreview.querySelector('img');
            mysticalEngine.shatterImage(imgElement, () => this.executeFactCheck(text, hasImage));
        } else if (text && typeof mysticalEngine !== 'undefined') {
            mysticalEngine.shatterText(this.textInput, () => this.executeFactCheck(text, hasImage));
        } else {
            this.executeFactCheck(text, hasImage);
        }
    }
    
    async executeFactCheck(text, hasImage) {
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
        this.textInput.style.color = ''; // Restore text color after magical transition
        this.hideResults();
        if (this.welcomeSection) this.welcomeSection.classList.remove('hidden');
        // Exit results-mode: restore footer
        if (this.bottomArea) this.bottomArea.classList.remove('results-mode');
        // Restore clear button to icon-only
        this.clearBtn.innerHTML = '<i class="fas fa-eraser"></i>';
        
        // Remove image
        this.imageDataUrl = null;
        if (this.imagePreview) {
            this.imagePreview.classList.add('hidden');
            this.imagePreview.innerHTML = '';
        }
        if (this.textInput) {
            this.textInput.style.display = '';
        }
        this.updateFactCheckButtonState();

        if (typeof mysticalEngine !== 'undefined') {
            mysticalEngine.resetInput();
        }
        this.textInput.focus();
    }

    showLoading() {
        if (this.welcomeSection) this.welcomeSection.classList.add('hidden');
        this.loadingSection.classList.remove('hidden');
        this.resultsSection.classList.add('hidden');
        this.factCheckBtn.disabled = true;
        // Start cloud morph animation
        if (typeof mysticalEngine !== 'undefined') {
            mysticalEngine.startCloudLoading();
        }
    }

    hideLoading() {
        this.factCheckBtn.disabled = false;
        this.updateFactCheckButtonState();
        // Disperse cloud then hide loading section
        if (typeof mysticalEngine !== 'undefined') {
            mysticalEngine.disperseCloud(() => {
                this.loadingSection.classList.add('hidden');
            });
        } else {
            this.loadingSection.classList.add('hidden');
        }
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
                    const friendlyImageMsg = this.getFriendlyErrorMessage(imageMessage);
                    msgDiv.innerHTML = `<i class="fas fa-info-circle"></i> ${this.escapeHtml(friendlyImageMsg)}`;
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
            const friendlyMsg = this.getFriendlyErrorMessage(data.analysis_error);
            msgDiv.innerHTML = `<i class="fas fa-info-circle"></i> ${this.escapeHtml(friendlyMsg)}`;
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
        
        // Trigger cinematic reveal
        if (typeof mysticalEngine !== 'undefined') {
            mysticalEngine.triggerReveal();
        }
        
        // Enter results-mode: centered clear button, hide attach/send
        if (this.bottomArea) this.bottomArea.classList.add('results-mode');
        this.clearBtn.innerHTML = '<i class="fas fa-eraser"></i><span class="clear-label">New Check</span>';
        
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
                    // Shrink from the right to find a valid JSON block
                    for (let endIdx = jsonStr.length - 1; endIdx >= startIdx; endIdx--) {
                        if (jsonStr[endIdx] === '}' || jsonStr[endIdx] === ']') {
                            let cleanJson = jsonStr.substring(startIdx, endIdx + 1);
                            
                            try {
                                let result = processParsedJson(JSON.parse(cleanJson));
                                if (result) return result;
                            } catch (innerE) {
                                try {
                                    let fixedJson = cleanJson.replace(/\n/g, '\\n').replace(/\r/g, '\\r');
                                    let result = processParsedJson(JSON.parse(fixedJson));
                                    if (result) return result;
                                } catch (e3) {
                                    try {
                                        let fixedJson = cleanJson.replace(/,\s*([}\]])/g, '$1');
                                        let result = processParsedJson(JSON.parse(fixedJson));
                                        if (result) return result;
                                    } catch (e4) {
                                        // Continue trying shorter substrings
                                    }
                                }
                            }
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
            let trimmedExp = explanation.trim();
            if (trimmedExp.startsWith('{') || trimmedExp.startsWith('[')) {
                try {
                    let jsonStr = trimmedExp;
                    if (jsonStr.startsWith('json ')) {
                        jsonStr = jsonStr.substring(5);
                    }
                    
                    let parsed = null;
                    try {
                        parsed = JSON.parse(jsonStr);
                    } catch (e) {
                        // Try to find valid JSON block by shrinking from the end
                        let startIdx = 0;
                        for (let endIdx = jsonStr.length - 1; endIdx >= startIdx; endIdx--) {
                            if (jsonStr[endIdx] === '}' || jsonStr[endIdx] === ']') {
                                try {
                                    parsed = JSON.parse(jsonStr.substring(startIdx, endIdx + 1));
                                    break; // Successfully parsed
                                } catch(e2) {}
                            }
                        }
                    }
                    
                    if (parsed) {
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
                    } else {
                        throw new Error("Could not parse JSON");
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

    getFriendlyErrorMessage(message) {
        if (!message) return "";
        const lowerMsg = message.toLowerCase();
        if (lowerMsg.includes('quota') || lowerMsg.includes('rate limit') || lowerMsg.includes('429') || lowerMsg.includes('too many requests')) {
            return "The system is currently experiencing high traffic and cannot process your request right now. Please wait a few moments and try again.";
        }
        if (lowerMsg.includes('api key') || lowerMsg.includes('unauthorized') || lowerMsg.includes('401')) {
            return "The system is experiencing configuration issues with the AI provider.";
        }
        if (lowerMsg.includes('failed to fetch') || lowerMsg.includes('network error')) {
            return "Unable to connect to the server. Please check your internet connection and try again.";
        }
        if (message.length > 150) {
            return "An unexpected error occurred while analyzing the claim. Please try again or rephrase your prompt.";
        }
        return message;
    }

    showError(message) {
        const friendlyMessage = this.getFriendlyErrorMessage(message);
        this.resultsContainer.innerHTML = `
            <div class="claim-result false">
                <div class="explanation">
                    <i class="fas fa-exclamation-triangle"></i>
                    <strong>Error:</strong> ${this.escapeHtml(friendlyMessage)}
                </div>
            </div>
        `;
        this.resultsSection.classList.remove('hidden');
    }
}


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
        
        const fragmentShader = `
            uniform float iTime;
            uniform vec2 iResolution;
            uniform float intensity;
            uniform float loadingState;
            
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
                vec2 centeredUv = uv - vec2(0.5, 0.5);
                centeredUv.x *= iResolution.x/iResolution.y;
                
                float baseTime = iTime * 0.2;
                float rotAngle = iTime * 0.8; // Always rotate to prevent phase jumps
                mat2 rot = mat2(cos(rotAngle), -sin(rotAngle), sin(rotAngle), cos(rotAngle));
                
                vec2 ruv = mix(uv, centeredUv * rot + vec2(0.5), loadingState);
                
                float t = iTime * 0.3; // Constant time scale to prevent phase jumps
                
                // Multilayer noise
                float n1 = snoise(ruv * 1.5 + vec2(t, t * 0.5));
                float n2 = snoise(ruv * 3.0 - vec2(t * 1.2, t * 0.8));
                float n3 = snoise(ruv * 5.0 + vec2(t * 0.5, -t));
                
                float n = n1 * 0.5 + n2 * 0.25 + n3 * 0.125;
                n = n * 0.5 + 0.5; // map to 0-1
                
                // Colors (Deep mystical purple/blue/cyan to ethereal white)
                vec3 col1 = vec3(0.28, 0.3, 0.84); // Indigo
                vec3 col2 = vec3(0.46, 0.23, 0.86); // Purple
                vec3 col3 = vec3(0.85, 0.95, 1.0);  // Ethereal White/Cyan
                
                vec3 finalCol = mix(col1, col2, smoothstep(0.2, 0.8, n));
                finalCol = mix(finalCol, col3, smoothstep(0.5, 1.0, n) * (0.5 + intensity * 0.5));
                
                // Ambient mask: dense at bottom, fading up
                float ambientMask = smoothstep(0.8, 0.0, fragCoord.y/iResolution.y);
                ambientMask = pow(ambientMask, 1.5) * (n * 0.5 + 0.5);
                
                // Loading mask: circular in the center
                float dist = length(centeredUv);
                float loadingMask = smoothstep(0.35, 0.05, dist);
                loadingMask = pow(loadingMask, 1.2) * (n * 0.7 + 0.3);
                
                float mask = mix(ambientMask, loadingMask, loadingState);
                
                fragColor = vec4(finalCol, mask * mix(0.8, 1.0, loadingState));
            }
            
            void main() {
                mainImage(gl_FragColor, gl_FragCoord.xy);
            }
        `;
        
        this.uniforms = {
            iTime: { value: 0 },
            iResolution: { value: new THREE.Vector2() },
            intensity: { value: 0.2 },
            loadingState: { value: 0.0 }
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
        
        this.resizeWebGL();
        
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
        const rect = textElement.getBoundingClientRect();
        const computed = window.getComputedStyle(textElement);
        
        // Save the color before we hide it
        const textColor = computed.color;
        
        if (this.floatingPrompt) {
            this.floatingPrompt.classList.add('shattering');
        }
        
        this.setCloudIntensity(true); // Intensify cloud during processing
        
        // Create a ghost div to hold the characters
        const ghost = document.createElement('div');
        document.body.appendChild(ghost);
        
        // Match styles precisely
        ghost.style.position = 'absolute';
        ghost.style.left = rect.left + 'px';
        ghost.style.top = rect.top + 'px';
        ghost.style.width = rect.width + 'px';
        ghost.style.height = rect.height + 'px';
        ghost.style.fontFamily = computed.fontFamily;
        ghost.style.fontSize = computed.fontSize;
        ghost.style.fontWeight = computed.fontWeight;
        ghost.style.lineHeight = computed.lineHeight;
        ghost.style.letterSpacing = computed.letterSpacing;
        ghost.style.padding = computed.padding;
        ghost.style.boxSizing = computed.boxSizing;
        ghost.style.whiteSpace = 'pre-wrap';
        ghost.style.wordWrap = 'break-word';
        ghost.style.color = textColor; // Use the saved visible color
        ghost.style.pointerEvents = 'none';
        ghost.style.zIndex = '1000';
        
        const text = textElement.value;
        textElement.style.color = 'transparent'; // hide real text
        
        // Wrap each character in a span
        const spans = [];
        for (let i = 0; i < text.length; i++) {
            const char = text[i];
            const span = document.createElement('span');
            span.innerHTML = char === ' ' ? '&nbsp;' : char;
            span.style.display = 'inline-block';
            span.style.transition = 'transform 1.8s cubic-bezier(0.4, 0, 0.2, 1), opacity 1.8s ease, filter 1.8s ease';
            ghost.appendChild(span);
            spans.push(span);
        }
        
        // Force reflow to calculate positions
        ghost.getBoundingClientRect();
        
        // Record starting absolute positions
        const positions = spans.map(span => {
            const r = span.getBoundingClientRect();
            return { left: r.left, top: r.top, width: r.width, height: r.height };
        });
        
        // Switch to fixed positioning for independent animation
        spans.forEach((span, i) => {
            span.style.position = 'fixed';
            span.style.left = positions[i].left + 'px';
            span.style.top = positions[i].top + 'px';
            span.style.margin = '0';
        });
        
        const cx = window.innerWidth / 2;
        const cy = window.innerHeight / 2;
        
        // Animate each character
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                spans.forEach((span, i) => {
                    const dx = cx - positions[i].left - (positions[i].width / 2);
                    const dy = cy - positions[i].top - (positions[i].height / 2);
                    
                    // Wave effect: slight delay based on index
                    const delay = i * 15; 
                    span.style.transitionDelay = `${delay}ms`;
                    
                    // Calm, magical scatter: translate to center, scale down slightly, slight rotation
                    const rX = (Math.random() - 0.5) * 40;
                    const rY = (Math.random() - 0.5) * 40;
                    const rRot = (Math.random() - 0.5) * 60;
                    
                    span.style.transform = `translate(${dx + rX}px, ${dy + rY}px) scale(0.3) rotate(${rRot}deg)`;
                    span.style.opacity = '0';
                    span.style.filter = 'blur(3px)';
                });
            });
        });
        
        // Cleanup
        setTimeout(() => {
            ghost.remove();
        }, 2000 + text.length * 15);
        
        // Allow API call to proceed
        if (onComplete) setTimeout(onComplete, 500); 
    }
    
    shatterImage(imageElement, onComplete) {
        if (!imageElement) {
            if (onComplete) onComplete();
            return;
        }
        
        const rect = imageElement.getBoundingClientRect();
        
        if (this.floatingPrompt) {
            this.floatingPrompt.classList.add('shattering');
        }
        
        this.setCloudIntensity(true); // Intensify cloud during processing
        
        // Hide entire image preview container smoothly
        const previewContainer = imageElement.closest('.image-preview');
        if (previewContainer) {
            previewContainer.style.transition = 'opacity 0.5s ease';
            previewContainer.style.opacity = '0';
        } else {
            imageElement.style.transition = 'opacity 0.5s ease';
            imageElement.style.opacity = '0';
        }
        
        const ghost = document.createElement('img');
        ghost.src = imageElement.src;
        document.body.appendChild(ghost);
        
        ghost.style.position = 'fixed';
        ghost.style.left = rect.left + 'px';
        ghost.style.top = rect.top + 'px';
        ghost.style.width = rect.width + 'px';
        ghost.style.height = rect.height + 'px';
        ghost.style.pointerEvents = 'none';
        ghost.style.zIndex = '1000';
        ghost.style.transition = 'transform 1.5s cubic-bezier(0.4, 0, 0.2, 1), opacity 1.5s ease, filter 1.5s ease';
        ghost.style.borderRadius = window.getComputedStyle(imageElement).borderRadius;
        ghost.style.objectFit = 'cover';
        
        // Force reflow
        ghost.getBoundingClientRect();
        
        const cx = window.innerWidth / 2;
        const cy = window.innerHeight / 2;
        
        requestAnimationFrame(() => {
            const dx = cx - rect.left - (rect.width / 2);
            const dy = cy - rect.top - (rect.height / 2);
            
            const rRot = (Math.random() - 0.5) * 60;
            ghost.style.transform = `translate(${dx}px, ${dy}px) scale(0.1) rotate(${rRot}deg)`;
            ghost.style.opacity = '0';
            ghost.style.filter = 'blur(10px)';
        });
        
        setTimeout(() => {
            ghost.remove();
        }, 1600);
        
        if (onComplete) setTimeout(onComplete, 500);
    }
    
    animateParticles() {
        // Obsolete: canvas particle engine is replaced by DOM character animation
        return;
    }
    
    // --- CLOUD LOADING ANIMATION ---
    setLoadingState(target) {
        if (!this.uniforms) return;
        
        // Stop any existing tween
        if (this.loadingTween) {
            cancelAnimationFrame(this.loadingTween);
        }
        
        const current = this.uniforms.loadingState.value;
        const step = (target - current) * 0.04; // Smooth transition speed
        
        const tween = () => {
            this.uniforms.loadingState.value += step;
            if (Math.abs(this.uniforms.loadingState.value - target) > 0.01) {
                this.loadingTween = requestAnimationFrame(tween);
            } else {
                this.uniforms.loadingState.value = target;
                this.loadingTween = null;
            }
        };
        tween();
    }

    startCloudLoading() {
        this.thoughtContainer = document.getElementById('thoughtBubbles');
        this.cloudOverlay = document.getElementById('cloudLoadingOverlay');
        if (!this.thoughtContainer) return;

        // Transition main WebGL cloud loading state
        this.setLoadingState(1.0);
        this.cloudRunning = true;

        // Thought bubble cycling
        this.bubbleMessages = [
            'Analyzing claims...',
            'Cross-referencing sources...',
            'Evaluating evidence...',
            'Verifying credibility...',
            'Checking global databases...',
            'Comparing perspectives...'
        ];
        this.bubblePositions = [
            { top: '5%', left: '55%', cls: 'pos-top-right' },
            { top: '25%', right: '2%', cls: 'pos-right' },
            { bottom: '20%', right: '5%', cls: 'pos-bottom-right' },
            { bottom: '5%', left: '10%', cls: 'pos-bottom-left' },
            { top: '30%', left: '2%', cls: 'pos-left' },
            { top: '2%', left: '10%', cls: 'pos-top-left' }
        ];
        this.bubbleIndex = 0;
        this.thoughtContainer.innerHTML = '';
        this._spawnBubble();
        this.bubbleInterval = setInterval(() => {
            if (!this.cloudRunning) return;
            this._spawnBubble();
        }, 2200);
    }

    _spawnBubble() {
        if (!this.thoughtContainer) return;
        // Fade previous bubbles
        const old = this.thoughtContainer.querySelectorAll('.thought-bubble:not(.fading)');
        old.forEach(b => { b.classList.add('fading'); setTimeout(() => b.remove(), 400); });

        const msg = this.bubbleMessages[this.bubbleIndex % this.bubbleMessages.length];
        const pos = this.bubblePositions[this.bubbleIndex % this.bubblePositions.length];
        this.bubbleIndex++;

        const bubble = document.createElement('div');
        bubble.className = `thought-bubble ${pos.cls}`;
        bubble.textContent = msg;
        if (pos.top) bubble.style.top = pos.top;
        if (pos.bottom) bubble.style.bottom = pos.bottom;
        if (pos.left) bubble.style.left = pos.left;
        if (pos.right) bubble.style.right = pos.right;
        this.thoughtContainer.appendChild(bubble);
    }

    disperseCloud(onComplete) {
        this.cloudRunning = false;
        if (this.bubbleInterval) { clearInterval(this.bubbleInterval); this.bubbleInterval = null; }
        // Fade out bubbles
        if (this.thoughtContainer) {
            this.thoughtContainer.querySelectorAll('.thought-bubble').forEach(b => {
                b.classList.add('fading');
                setTimeout(() => b.remove(), 400);
            });
        }
        
        // Return main WebGL cloud to ambient state
        this.setLoadingState(0.0);

        setTimeout(() => {
            if (onComplete) onComplete();
        }, 800);
    }

    triggerReveal() {
        this.setCloudIntensity(false);
        if (this.resultsSection) {
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

// Initialize the app when page loads
document.addEventListener('DOMContentLoaded', () => {
    new FactCheckerApp();
});
