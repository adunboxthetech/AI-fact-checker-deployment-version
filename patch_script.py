import sys

with open('script.js', 'r') as f:
    content = f.read()

# 1. Add ambientGradient and welcomeSection
content = content.replace(
    "this.imagePreview = document.getElementById('imagePreview');\n        this.analyzeImageBtn = null;\n    }",
    "this.imagePreview = document.getElementById('imagePreview');\n        this.ambientGradient = document.getElementById('ambientGradient');\n        this.welcomeSection = document.getElementById('welcomeSection');\n        this.analyzeImageBtn = null;\n    }"
)

# 2. Add gradient interaction logic
content = content.replace(
    "        // Allow Enter+Ctrl to trigger fact check\n        this.textInput.addEventListener('keydown', (e) => {\n            if (e.ctrlKey && e.key === 'Enter') {\n                this.handleFactCheck();\n            }\n        });\n    }",
    "        // Allow Enter+Ctrl to trigger fact check\n        this.textInput.addEventListener('keydown', (e) => {\n            if (e.ctrlKey && e.key === 'Enter') {\n                this.handleFactCheck();\n            }\n        });\n\n        // Ambient gradient interaction & auto-resize textarea\n        const updateGradient = () => {\n            if (this.ambientGradient) {\n                if (this.textInput.value.trim().length > 0 || document.activeElement === this.textInput) {\n                    this.ambientGradient.classList.add('active');\n                } else {\n                    this.ambientGradient.classList.remove('active');\n                }\n            }\n        };\n        this.textInput.addEventListener('input', function() {\n            this.style.height = 'auto';\n            this.style.height = (Math.min(this.scrollHeight, 200)) + 'px';\n            updateGradient();\n        });\n        this.textInput.addEventListener('focus', updateGradient);\n        this.textInput.addEventListener('blur', updateGradient);\n    }"
)

# 3. Update button state logic
content = content.replace(
    "     updateFactCheckButtonState() {\n        if (!this.factCheckBtn) return;\n        const hasImage = Boolean(this.imageDataUrl);\n        const icon = this.factCheckBtn.querySelector('i');\n        const label = this.factCheckBtn.querySelector('.btn-label');\n        if (icon) icon.className = `fas ${hasImage ? 'fa-photo-film' : 'fa-magnifying-glass'}`;\n        if (label) label.textContent = hasImage ? 'Analyze Image' : 'Fact Check Now';\n    }",
    "     updateFactCheckButtonState() {\n        if (!this.factCheckBtn) return;\n        const hasImage = Boolean(this.imageDataUrl);\n        const icon = this.factCheckBtn.querySelector('i');\n        const label = this.factCheckBtn.querySelector('.btn-label');\n        if (icon) icon.className = `fas fa-arrow-up`;\n        if (label) label.textContent = hasImage ? 'Analyze Image' : 'Fact Check Now';\n    }"
)

# 4. handleClear()
content = content.replace(
    "    handleClear() {\n        this.textInput.value = '';\n        this.hideResults();\n        this.textInput.focus();\n    }",
    "    handleClear() {\n        this.textInput.value = '';\n        this.textInput.style.height = 'auto';\n        this.hideResults();\n        if (this.welcomeSection) this.welcomeSection.classList.remove('hidden');\n        if (this.ambientGradient) this.ambientGradient.classList.remove('active');\n        this.textInput.focus();\n    }"
)

# 5. showLoading()
content = content.replace(
    "    showLoading() {\n        this.loadingSection.classList.remove('hidden');\n        this.resultsSection.classList.add('hidden');\n        this.factCheckBtn.disabled = true;\n    }",
    "    showLoading() {\n        if (this.welcomeSection) this.welcomeSection.classList.add('hidden');\n        this.loadingSection.classList.remove('hidden');\n        this.resultsSection.classList.add('hidden');\n        this.factCheckBtn.disabled = true;\n    }"
)

with open('script.js', 'w') as f:
    f.write(content)

print("Patched script.js")
