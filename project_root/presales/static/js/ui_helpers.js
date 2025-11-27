/**
 * UI Helper Functions
 * Reusable UI components and utilities for presales dashboard
 */

const UIHelpers = {
    /**
     * Show loading spinner on button
     */
    showButtonLoading: function(button, text = 'Processing...') {
        const $btn = $(button);
        $btn.data('original-html', $btn.html());
        $btn.prop('disabled', true);
        $btn.html(`<span class="spinner-border spinner-border-sm me-2" role="status"></span>${text}`);
    },

    /**
     * Hide loading spinner on button
     */
    hideButtonLoading: function(button) {
        const $btn = $(button);
        const originalHtml = $btn.data('original-html');
        if (originalHtml) {
            $btn.html(originalHtml);
        }
        $btn.prop('disabled', false);
    },

    /**
     * Show toast notification
     */
    showToast: function(message, type = 'info', duration = 5000) {
        const iconMap = {
            'success': 'fa-check-circle',
            'error': 'fa-exclamation-circle',
            'warning': 'fa-exclamation-triangle',
            'info': 'fa-info-circle'
        };

        const bgMap = {
            'success': 'bg-success',
            'error': 'bg-danger',
            'warning': 'bg-warning',
            'info': 'bg-info'
        };

        const toast = $(`
            <div class="toast-notification ${bgMap[type]}" style="
                position: fixed;
                top: 80px;
                right: 20px;
                z-index: 9999;
                min-width: 350px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.2);
                animation: slideInRight 0.4s ease-out;
                border-radius: 8px;
                padding: 15px 20px;
                color: white;
            ">
                <div class="d-flex align-items-center">
                    <i class="fas ${iconMap[type]} me-3" style="font-size: 1.5rem;"></i>
                    <div class="flex-grow-1">${message}</div>
                    <button type="button" class="btn-close btn-close-white ms-3" onclick="$(this).parent().parent().remove()"></button>
                </div>
            </div>
        `);

        $('body').append(toast);
        
        setTimeout(() => {
            toast.fadeOut(300, function() { $(this).remove(); });
        }, duration);
    },

    /**
     * Show loading overlay
     */
    showLoadingOverlay: function(message = 'Loading...') {
        const overlay = $(`
            <div class="loading-overlay" style="
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0,0,0,0.5);
                z-index: 10000;
                display: flex;
                align-items: center;
                justify-content: center;
            ">
                <div class="text-center text-white">
                    <div class="spinner-border mb-3" role="status" style="width: 3rem; height: 3rem;">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <div style="font-size: 1.2rem;">${message}</div>
                </div>
            </div>
        `);
        
        $('body').append(overlay);
    },

    /**
     * Hide loading overlay
     */
    hideLoadingOverlay: function() {
        $('.loading-overlay').fadeOut(300, function() { $(this).remove(); });
    },

    /**
     * Confirm dialog with custom styling
     */
    confirm: function(message, onConfirm, onCancel) {
        const modal = $(`
            <div class="modal fade" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header bg-warning text-dark">
                            <h5 class="modal-title">
                                <i class="fas fa-exclamation-triangle me-2"></i>Confirm Action
                            </h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <p>${message}</p>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                            <button type="button" class="btn btn-primary confirm-btn">Confirm</button>
                        </div>
                    </div>
                </div>
            </div>
        `);

        modal.find('.confirm-btn').on('click', function() {
            if (onConfirm) onConfirm();
            bootstrap.Modal.getInstance(modal[0]).hide();
        });

        modal.on('hidden.bs.modal', function() {
            if (onCancel) onCancel();
            modal.remove();
        });

        $('body').append(modal);
        new bootstrap.Modal(modal[0]).show();
    },

    /**
     * Format date for display
     */
    formatDate: function(dateString) {
        if (!dateString) return 'N/A';
        const date = new Date(dateString);
        return date.toLocaleDateString('en-GB', { 
            day: '2-digit', 
            month: 'short', 
            year: 'numeric' 
        });
    },

    /**
     * Format file size
     */
    formatFileSize: function(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
    },

    /**
     * Debounce function for search inputs
     */
    debounce: function(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }
};

// Export for use in other scripts
window.UIHelpers = UIHelpers;
