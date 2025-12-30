/**
 * PBS Authentication Security Module
 * Cross-browser compatible authentication security features
 * Supports: Chrome, Safari, Firefox, Edge, Opera, Opera Mini, Brave, UC Browser
 */

(function() {
    'use strict';

    // ============================================================================
    // BROWSER COMPATIBILITY DETECTION
    // ============================================================================
    const BrowserDetect = {
        isChrome: function() {
            return /Chrome/.test(navigator.userAgent) && /Google Inc/.test(navigator.vendor);
        },
        isSafari: function() {
            return /Safari/.test(navigator.userAgent) && /Apple Computer/.test(navigator.vendor);
        },
        isFirefox: function() {
            return /Firefox/.test(navigator.userAgent);
        },
        isEdge: function() {
            return /Edg/.test(navigator.userAgent);
        },
        isOpera: function() {
            return /OPR|Opera/.test(navigator.userAgent);
        },
        isBrave: function() {
            return navigator.brave && typeof navigator.brave.isBrave === 'function';
        },
        isUCBrowser: function() {
            return /UCBrowser/.test(navigator.userAgent);
        },
        isMobile: function() {
            return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
        }
    };

    // ============================================================================
    // INPUT SANITIZATION
    // ============================================================================
    const Sanitizer = {
        /**
         * Sanitize email input
         */
        sanitizeEmail: function(email) {
            if (!email) return '';
            
            // Remove whitespace
            email = email.trim().toLowerCase();
            
            // Remove dangerous characters
            email = email.replace(/[<>'"]/g, '');
            
            return email;
        },

        /**
         * Sanitize general text input
         */
        sanitizeText: function(text) {
            if (!text) return '';
            
            // Remove script tags and dangerous patterns
            text = text.replace(/<script[^>]*>.*?<\/script>/gi, '');
            text = text.replace(/javascript:/gi, '');
            text = text.replace(/on\w+\s*=/gi, '');
            
            return text.trim();
        },

        /**
         * Escape HTML to prevent XSS
         */
        escapeHtml: function(text) {
            const map = {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#039;'
            };
            return text.replace(/[&<>"']/g, function(m) { return map[m]; });
        }
    };

    // ============================================================================
    // EMAIL VALIDATION
    // ============================================================================
    const EmailValidator = {
        /**
         * Validate email format
         */
        isValid: function(email) {
            if (!email) return false;
            
            // RFC 5322 compliant email regex
            const emailRegex = /^[a-zA-Z0-9.!#$%&'*+\/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/;
            
            return emailRegex.test(email);
        },

        /**
         * Show validation error
         */
        showError: function(inputElement, message) {
            const errorDiv = document.createElement('div');
            errorDiv.className = 'validation-error';
            errorDiv.textContent = message;
            errorDiv.style.color = '#dc2626';
            errorDiv.style.fontSize = '13px';
            errorDiv.style.marginTop = '5px';
            
            // Remove existing error
            const existingError = inputElement.parentElement.querySelector('.validation-error');
            if (existingError) {
                existingError.remove();
            }
            
            inputElement.parentElement.appendChild(errorDiv);
            inputElement.style.borderColor = '#dc2626';
        },

        /**
         * Clear validation error
         */
        clearError: function(inputElement) {
            const existingError = inputElement.parentElement.querySelector('.validation-error');
            if (existingError) {
                existingError.remove();
            }
            inputElement.style.borderColor = '';
        }
    };

    // ============================================================================
    // PASSWORD VALIDATION
    // ============================================================================
    const PasswordValidator = {
        /**
         * Validate password strength
         */
        validate: function(password) {
            const requirements = {
                length: password.length >= 8,
                uppercase: /[A-Z]/.test(password),
                lowercase: /[a-z]/.test(password),
                number: /\d/.test(password),
                special: /[!@#$%^&*(),.?":{}|<>]/.test(password)
            };

            const strength = Object.values(requirements).filter(Boolean).length;
            
            return {
                isValid: Object.values(requirements).every(Boolean),
                requirements: requirements,
                strength: strength <= 2 ? 'weak' : strength <= 4 ? 'medium' : 'strong'
            };
        },

        /**
         * Check if passwords match
         */
        doPasswordsMatch: function(password, confirmPassword) {
            return password === confirmPassword && password.length > 0;
        }
    };

    // ============================================================================
    // FORM SECURITY
    // ============================================================================
    const FormSecurity = {
        /**
         * Prevent form double submission
         */
        preventDoubleSubmit: function(form) {
            let isSubmitting = false;
            
            form.addEventListener('submit', function(e) {
                if (isSubmitting) {
                    e.preventDefault();
                    return false;
                }
                
                isSubmitting = true;
                
                // Re-enable after 3 seconds (in case of validation errors)
                setTimeout(function() {
                    isSubmitting = false;
                }, 3000);
            });
        },

        /**
         * Add CSRF protection (if token is available)
         */
        addCSRFProtection: function(form) {
            const csrfToken = document.querySelector('meta[name="csrf-token"]');
            if (csrfToken) {
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'csrf_token';
                input.value = csrfToken.content;
                form.appendChild(input);
            }
        },

        /**
         * Disable autocomplete for sensitive fields
         */
        disableAutocomplete: function(inputElement) {
            inputElement.setAttribute('autocomplete', 'off');
            inputElement.setAttribute('autocorrect', 'off');
            inputElement.setAttribute('autocapitalize', 'off');
            inputElement.setAttribute('spellcheck', 'false');
        }
    };

    // ============================================================================
    // SESSION SECURITY
    // ============================================================================
    const SessionSecurity = {
        /**
         * Check if session is still valid
         */
        checkSession: function() {
            // Ping server to validate session
            fetch('/auth/ping', {
                method: 'GET',
                credentials: 'same-origin'
            }).catch(function() {
                // Session might be invalid
                console.warn('Session validation failed');
            });
        },

        /**
         * Start session monitoring
         */
        startMonitoring: function() {
            // Check session every 5 minutes
            setInterval(function() {
                SessionSecurity.checkSession();
            }, 5 * 60 * 1000);
        },

        /**
         * Clear sensitive data on page unload
         */
        clearOnUnload: function() {
            window.addEventListener('beforeunload', function() {
                // Clear any sensitive data from memory
                const passwordInputs = document.querySelectorAll('input[type="password"]');
                passwordInputs.forEach(function(input) {
                    input.value = '';
                });
            });
        }
    };

    // ============================================================================
    // RATE LIMITING (CLIENT-SIDE)
    // ============================================================================
    const RateLimiter = {
        attempts: {},

        /**
         * Check if action is rate limited
         */
        isLimited: function(action, maxAttempts, timeWindow) {
            const now = Date.now();
            const key = action;
            
            if (!this.attempts[key]) {
                this.attempts[key] = [];
            }
            
            // Remove old attempts outside time window
            this.attempts[key] = this.attempts[key].filter(function(timestamp) {
                return now - timestamp < timeWindow;
            });
            
            // Check if limit exceeded
            if (this.attempts[key].length >= maxAttempts) {
                return true;
            }
            
            // Add current attempt
            this.attempts[key].push(now);
            return false;
        }
    };

    // ============================================================================
    // INITIALIZE ON DOM READY
    // ============================================================================
    function initializeSecurity() {
        // Login form security
        const loginForm = document.querySelector('form[action*="login"]');
        if (loginForm) {
            const emailInput = loginForm.querySelector('input[type="email"]');
            const passwordInput = loginForm.querySelector('input[type="password"]');
            
            if (emailInput) {
                // Email validation on blur
                emailInput.addEventListener('blur', function() {
                    const email = Sanitizer.sanitizeEmail(this.value);
                    this.value = email;
                    
                    if (email && !EmailValidator.isValid(email)) {
                        EmailValidator.showError(this, 'Please enter a valid email address');
                    } else {
                        EmailValidator.clearError(this);
                    }
                });
            }
            
            // Form submission validation
            loginForm.addEventListener('submit', function(e) {
                let isValid = true;
                
                // Validate email
                if (emailInput) {
                    const email = Sanitizer.sanitizeEmail(emailInput.value);
                    emailInput.value = email;
                    
                    if (!EmailValidator.isValid(email)) {
                        EmailValidator.showError(emailInput, 'Please enter a valid email address');
                        isValid = false;
                    }
                }
                
                // Validate password
                if (passwordInput && !passwordInput.value) {
                    EmailValidator.showError(passwordInput, 'Password is required');
                    isValid = false;
                }
                
                // Check rate limiting
                if (RateLimiter.isLimited('login', 5, 60000)) {
                    alert('Too many login attempts. Please wait a moment before trying again.');
                    isValid = false;
                }
                
                if (!isValid) {
                    e.preventDefault();
                    return false;
                }
            });
            
            FormSecurity.preventDoubleSubmit(loginForm);
        }
        
        // Password reset forms
        const resetForms = document.querySelectorAll('form[action*="reset"]');
        resetForms.forEach(function(form) {
            FormSecurity.preventDoubleSubmit(form);
        });
        
        // Start session monitoring
        if (document.body.classList.contains('authenticated')) {
            SessionSecurity.startMonitoring();
        }
        
        // Clear sensitive data on unload
        SessionSecurity.clearOnUnload();
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeSecurity);
    } else {
        initializeSecurity();
    }

    // Export for global access if needed
    window.PBSAuthSecurity = {
        Sanitizer: Sanitizer,
        EmailValidator: EmailValidator,
        PasswordValidator: PasswordValidator,
        FormSecurity: FormSecurity,
        SessionSecurity: SessionSecurity,
        BrowserDetect: BrowserDetect
    };

})();
