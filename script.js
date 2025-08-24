class FactCheckerApp {
    constructor() {
        this.apiUrl = '/api'; // Use API routes for Vercel serverless functions
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
        this.imageDataUrl = null;
    }

    bindEvents() {
        this.factCheckBtn.addEventListener('click', () => this.handleFactCheck());
        this.clearBtn.addEventListener('click', () => this.handleClear());
        
        if (this.themeToggle) {
            this.themeToggle.addEventListener('click', () => this.toggleTheme());
        }

        if (this.imageDrop) {
            this.imageDrop.addEventListener('click', () => this.imageInput.click());
            this.imageDrop.addEventListener('dragover', (e) => {
                e.preventDefault();
                this.imageDrop.style.borderColor = 'var(--accent)';
            });
            this.imageDrop.addEventListener('dragleave', (e) => {
                e.preventDefault();
                this.imageDrop.style.borderColor = 'var(--border)';
            });
            this.imageDrop.addEventListener('drop', (e) => {
                e.preventDefault();
                this.imageDrop.style.borderColor = 'var(--border)';
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
                <img src="${dataUrl}" alt="Preview" />
                <button class="remove" onclick="app.clearImagePreview()">&times;</button>
            </div>
            <button class="primary-btn" id="analyzeImageBtn" style="margin-top: 12px;">
                <i class="fas fa-search"></i>
                Analyze Image
            </button>
        `;

        // Bind the new analyze button
        this.analyzeImageBtn = document.getElementById('analyzeImageBtn');
        if (this.analyzeImageBtn) {
            this.analyzeImageBtn.addEventListener('click', () => this.handleImageFactCheck());
        }
    }

    clearImagePreview() {
        this.imageDataUrl = null;
        if (this.imagePreview) {
            this.imagePreview.innerHTML = '';
            this.imagePreview.classList.add('hidden');
        }
        if (this.imageInput) {
            this.imageInput.value = '';
        }
    }

    async handleFactCheck() {
        const text = this.textInput.value.trim();
        const url = this.extractUrl(text);

        if (!text && !this.imageDataUrl) {
            alert('Please enter some text, a URL, or upload an image to fact-check.');
            return;
        }

        this.showLoading();

        try {
            let response;
            
            if (this.imageDataUrl && !url) {
                // Image-only fact checking
                response = await this.factCheckImage();
            } else {
                // Text/URL fact checking
                const payload = url ? { url: url } : { text: text };
                response = await fetch(`${this.apiUrl}/fact-check`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(payload)
                });
            }

            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.error || 'Fact-check request failed');
            }

            this.renderResults(data);
        } catch (error) {
            console.error('Fact-check failed:', error);
            this.showError(error.message);
        } finally {
            this.hideLoading();
        }
    }

    async handleImageFactCheck() {
        if (!this.imageDataUrl) {
            alert('Please upload an image first.');
            return;
        }

        this.showLoading();

        try {
            const response = await this.factCheckImage();
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.error || 'Image fact-check failed');
            }

            this.renderResults(data);
        } catch (error) {
            console.error('Image fact-check failed:', error);
            this.showError(error.message);
        } finally {
            this.hideLoading();
        }
    }

    async factCheckImage() {
        return fetch(`${this.apiUrl}/fact-check-image`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                image_data_url: this.imageDataUrl
            })
        });
    }

    extractUrl(text) {
        const urlPattern = /https?:\/\/[^\s]+/g;
        const matches = text.match(urlPattern);
        return matches ? matches[0] : null;
    }

    showLoading() {
        this.loadingSection.classList.remove('hidden');
        this.resultsSection.classList.add('hidden');
        this.factCheckBtn.disabled = true;
        this.factCheckBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Analyzing...';
    }

    hideLoading() {
        this.loadingSection.classList.add('hidden');
        this.factCheckBtn.disabled = false;
        this.factCheckBtn.innerHTML = '<i class="fas fa-search"></i> Fact Check';
    }

    // In your script.js, replace the renderResults function with this enhanced version:

renderResults(data) {
    console.log('Rendering results:', data);
    
    this.resultsContainer.innerHTML = '';

    // Handle error cases
    if (data.error) {
        this.showError(data.error);
        return;
    }

    if (!data.fact_check_results || data.fact_check_results.length === 0) {
        this.resultsContainer.innerHTML = '<p class="no-results">No factual claims found to verify.</p>';
    } else {
        // Add source info if from URL
        if (data.source_url) {
            const sourceDiv = document.createElement('div');
            sourceDiv.className = 'source-banner';
            const imagesText = data.images_processed > 0 ? ` • ${data.images_processed} image${data.images_processed > 1 ? 's' : ''} analyzed` : '';
            sourceDiv.innerHTML = `
                <i class="fas fa-link"></i>
                <span>Source: <a href="${data.source_url}" target="_blank" rel="noopener">${data.platform || 'External'}</a>${imagesText}</span>
            `;
            this.resultsContainer.appendChild(sourceDiv);
        }

        // Group results by source type
        const textResults = data.fact_check_results.filter(r => r.source_type === 'text' || !r.source_type);
        const imageResults = data.fact_check_results.filter(r => r.source_type === 'image');

        // Render text results
        if (textResults.length > 0) {
            if (imageResults.length > 0) {
                const textHeader = document.createElement('h3');
                textHeader.textContent = 'Text Analysis';
                textHeader.className = 'analysis-section-header';
                textHeader.style.cssText = 'margin: 20px 0 15px 0; color: var(--text); font-size: 1.2em; border-bottom: 2px solid var(--accent); padding-bottom: 8px;';
                this.resultsContainer.appendChild(textHeader);
            }

            textResults.forEach((result, index) => {
                const claimElement = this.createClaimElement(result, index + 1, 'text');
                this.resultsContainer.appendChild(claimElement);
            });
        }

        // Render image results - ENHANCED ERROR HANDLING
        if (imageResults.length > 0) {
            const imageHeader = document.createElement('h3');
            imageHeader.textContent = 'Image Analysis';
            imageHeader.className = 'analysis-section-header';
            imageHeader.style.cssText = 'margin: 20px 0 15px 0; color: var(--text); font-size: 1.2em; border-bottom: 2px solid var(--accent-2); padding-bottom: 8px;';
            this.resultsContainer.appendChild(imageHeader);

            // Group image results by image URL
            const imageGroups = {};
            imageResults.forEach(result => {
                const imgUrl = result.image_url || 'unknown';
                if (!imageGroups[imgUrl]) {
                    imageGroups[imgUrl] = [];
                }
                imageGroups[imgUrl].push(result);
            });

            Object.entries(imageGroups).forEach(([imgUrl, results], groupIndex) => {
                // Add image preview container
                if (imgUrl !== 'unknown') {
                    const imgContainer = document.createElement('div');
                    imgContainer.className = 'image-analysis-container';
                    imgContainer.style.cssText = 'margin-bottom: 20px; padding: 15px; background: var(--elev); border-radius: 12px; border: 1px solid var(--border);';
                    
                    const imgPreview = document.createElement('div');
                    imgPreview.className = 'image-source-preview';
                    imgPreview.style.cssText = 'margin-bottom: 15px; text-align: center;';
                    
                    // Enhanced image loading with error handling
                    imgPreview.innerHTML = `
                        <img src="${imgUrl}" alt="Analyzed image" 
                             style="max-width: 300px; max-height: 200px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);"
                             onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
                        <div style="display: none; padding: 20px; background: var(--card); border-radius: 8px; color: var(--muted);">
                            <i class="fas fa-image" style="font-size: 24px; margin-bottom: 8px;"></i>
                            <p>Image could not be loaded</p>
                        </div>
                        <p style="margin-top: 8px; color: var(--muted); font-size: 0.9em;">Image ${groupIndex + 1}</p>
                    `;
                    imgContainer.appendChild(imgPreview);
                    
                    // Add claims for this image
                    results.forEach((result, index) => {
                        const claimElement = this.createClaimElement(result, index + 1, 'image');
                        imgContainer.appendChild(claimElement);
                    });
                    
                    this.resultsContainer.appendChild(imgContainer);
                } else {
                    // Handle results without image URL
                    results.forEach((result, index) => {
                        const claimElement = this.createClaimElement(result, index + 1, 'image');
                        this.resultsContainer.appendChild(claimElement);
                    });
                }
            });
        }
    }

    this.resultsSection.classList.remove('hidden');
    this.resultsSection.scrollIntoView({ behavior: 'smooth' });
}

    createClaimElement(result, index, sourceType = 'text') {
        const div = document.createElement('div');
        
        // Safety check for result structure
        if (!result || !result.result) {
            div.innerHTML = `
                <div class="claim-result">
                    <div class="claim-text">Analysis Error</div>
                    <div class="explanation">Unable to process this claim properly.</div>
                </div>
            `;
            return div;
        }

        const { claim, result: factCheckResult } = result;
        const verdict = factCheckResult.verdict || 'INSUFFICIENT EVIDENCE';
        const confidence = factCheckResult.confidence || 0;
        const explanation = factCheckResult.explanation || 'No explanation provided.';
        const sources = factCheckResult.sources || [];

        // Determine verdict class for styling
        const verdictClass = verdict.toLowerCase().replace(/\s+/g, '-').replace('partially-true', 'partial');
        const verdictColors = {
            'true': 'var(--true)',
            'false': 'var(--false)',
            'partially-true': 'var(--partial)',
            'partial': 'var(--partial)',
            'insufficient-evidence': 'var(--muted)',
            'no-factual-claims': 'var(--muted)'
        };

        const borderColor = verdictColors[verdictClass] || 'var(--border)';
        const sourceIcon = sourceType === 'image' ? 'fas fa-image' : 'fas fa-file-text';

        div.innerHTML = `
            <div class="claim-result ${verdictClass}" style="border-left-color: ${borderColor};">
                <div class="claim-header" style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px;">
                    <i class="${sourceIcon}" style="color: var(--accent); font-size: 14px;"></i>
                    <span style="color: var(--muted); font-size: 14px; font-weight: 500;">
                        ${sourceType === 'image' ? 'Image' : 'Text'} Claim ${index}
                    </span>
                </div>
                <div class="claim-text">${claim}</div>
                <div class="verdict-container" style="display: flex; align-items: center; gap: 12px; margin-bottom: 12px;">
                    <span class="verdict ${verdictClass}">${verdict}</span>
                    <span class="confidence">Confidence: ${confidence}%</span>
                </div>
                <div class="explanation">${explanation}</div>
                ${sources.length > 0 ? `
                    <div class="sources">
                        <strong>Sources:</strong>
                        ${sources.map(source => {
                            if (typeof source === 'string' && source.startsWith('http')) {
                                const domain = new URL(source).hostname.replace('www.', '');
                                return `<a href="${source}" target="_blank" rel="noopener" class="source-link">${domain}</a>`;
                            }
                            return `<span class="source-link">${source}</span>`;
                        }).join(' • ')}
                    </div>
                ` : ''}
            </div>
        `;

        return div;
    }

    handleClear() {
        this.textInput.value = '';
        this.clearImagePreview();
        this.resultsSection.classList.add('hidden');
        this.loadingSection.classList.add('hidden');
        this.textInput.focus();
    }

    showError(message) {
        this.resultsContainer.innerHTML = `
            <div class="error-message" style="
                padding: 20px; 
                background: linear-gradient(135deg, rgba(239, 68, 68, 0.1), rgba(220, 38, 38, 0.05)); 
                border: 1px solid rgba(239, 68, 68, 0.2); 
                border-radius: 12px; 
                color: var(--text);
            ">
                <i class="fas fa-exclamation-triangle" style="color: var(--false); margin-right: 8px;"></i>
                <strong>Error:</strong> ${message}
            </div>
        `;
        this.resultsSection.classList.remove('hidden');
    }

    initializeTheme() {
        // Check for saved theme preference or default to light mode
        const savedTheme = localStorage.getItem('theme') || 'light';
        document.documentElement.setAttribute('data-theme', savedTheme);
        this.updateThemeIcon(savedTheme);
    }

    toggleTheme() {
        const currentTheme = document.documentElement.getAttribute('data-theme');
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        
        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('theme', newTheme);
        this.updateThemeIcon(newTheme);
    }

    updateThemeIcon(theme) {
        if (this.themeToggle) {
            const icon = this.themeToggle.querySelector('i');
            if (icon) {
                icon.className = theme === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
            }
        }
    }
}

// Initialize the app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.app = new FactCheckerApp();
});

// Global function for clearing image preview (called from dynamically generated HTML)
function clearImagePreview() {
    if (window.app) {
        window.app.clearImagePreview();
    }
}
