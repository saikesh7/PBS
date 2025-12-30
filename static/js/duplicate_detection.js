/**
 * Duplicate Detection JavaScript Module
 * Handles duplicate checking and warning popups for all modules
 * Compatible with ALL browsers: Chrome, Edge, Safari, Firefox, Opera Mini, IE11
 * Compatible with ALL systems: Windows, macOS, Linux, Mobile, Desktop
 * 
 * Features:
 * - Single request duplicate detection
 * - Bulk upload duplicate detection
 * - Validator approval/rejection duplicate warnings
 */

(function() {
    'use strict';

    // Polyfill for older browsers (IE11, Opera Mini)
    if (!Array.prototype.forEach) {
        Array.prototype.forEach = function(callback) {
            for (var i = 0; i < this.length; i++) {
                callback(this[i], i, this);
            }
        };
    }

    if (!String.prototype.trim) {
        String.prototype.trim = function() {
            return this.replace(/^[\s\uFEFF\xA0]+|[\s\uFEFF\xA0]+$/g, '');
        };
    }

    if (!Array.prototype.filter) {
        Array.prototype.filter = function(callback) {
            var arr = [];
            for (var i = 0; i < this.length; i++) {
                if (callback(this[i], i, this)) {
                    arr.push(this[i]);
                }
            }
            return arr;
        };
    }

    // Duplicate Detection Manager
    window.DuplicateDetection = {
        
        pendingSubmission: null,
        bulkDuplicates: [],
        
        /**
         * Check for duplicate in single request flow
         * @param {string} employeeId - Employee ID
         * @param {string} categoryId - Category Object ID
         * @param {string} eventDate - Event date in YYYY-MM-DD or DD-MM-YYYY format
         * @param {function} callback - Callback function(isDuplicate, duplicateInfo)
         */
        checkSingleRequest: function(employeeId, categoryId, eventDate, callback) {
            if (!employeeId || !categoryId || !eventDate) {
                callback(false, null);
                return;
            }

            // Use XMLHttpRequest for maximum browser compatibility
            var xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/duplicate/check-single', true);
            xhr.setRequestHeader('Content-Type', 'application/json');
            
            xhr.onreadystatechange = function() {
                if (xhr.readyState === 4) {
                    if (xhr.status === 200) {
                        try {
                            var response = JSON.parse(xhr.responseText);
                            callback(response.isDuplicate, response.duplicateInfo);
                        } catch (e) {
                            console.error('Error parsing duplicate check response:', e);
                            callback(false, null);
                        }
                    } else {
                        console.error('Duplicate check failed:', xhr.status);
                        callback(false, null);
                    }
                }
            };
            
            var payload = JSON.stringify({
                employee_id: employeeId,
                category_id: categoryId,
                event_date: eventDate
            });
            
            xhr.send(payload);
        },
        
        /**
         * Show duplicate warning popup
         * @param {object} duplicateInfo - Information about the duplicate
         * @param {function} onConfirm - Callback when user confirms to proceed
         * @param {function} onCancel - Callback when user cancels
         */
        showDuplicateWarning: function(duplicateInfo, onConfirm, onCancel) {
            var self = this;
            
            // Create modal overlay
            var overlay = document.createElement('div');
            overlay.id = 'duplicate-warning-overlay';
            overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center;';
            
            // Create modal
            var modal = document.createElement('div');
            modal.id = 'duplicate-warning-modal';
            modal.style.cssText = 'background:white;border-radius:8px;padding:24px;max-width:500px;width:90%;box-shadow:0 4px 20px rgba(0,0,0,0.3);';
            
            // Modal content
            var html = '<div style="text-align:center;">';
            html += '<div style="font-size:48px;color:#ff9800;margin-bottom:16px;">⚠️</div>';
            html += '<h3 style="margin:0 0 16px 0;color:#333;font-size:20px;">Duplicate Request Detected</h3>';
            
            // ✅ Use custom message if available (for validator actions)
            if (duplicateInfo.message) {
                html += '<p style="color:#666;margin:0 0 20px 0;line-height:1.5;">';
                html += this.escapeHtml(duplicateInfo.message);
                html += '</p>';
            } else {
                // Default message for updater actions
                html += '<p style="color:#666;margin:0 0 20px 0;line-height:1.5;">';
                html += 'A request for <strong>' + this.escapeHtml(duplicateInfo.employeeName) + '</strong> ';
                html += 'under category <strong>' + this.escapeHtml(duplicateInfo.categoryName) + '</strong> ';
                html += 'with event date <strong>' + this.escapeHtml(duplicateInfo.eventDate) + '</strong> ';
                html += 'already exists with status: <strong>' + this.escapeHtml(duplicateInfo.status) + '</strong>.';
                html += '</p>';
            }
            
            html += '<p style="color:#666;margin:0 0 24px 0;">Do you want to proceed anyway?</p>';
            html += '<div style="display:flex;gap:12px;justify-content:center;">';
            html += '<button id="duplicate-cancel-btn" style="padding:10px 24px;border:1px solid #ddd;background:white;color:#333;border-radius:4px;cursor:pointer;font-size:14px;">Cancel</button>';
            html += '<button id="duplicate-proceed-btn" style="padding:10px 24px;border:none;background:#ff9800;color:white;border-radius:4px;cursor:pointer;font-size:14px;">Proceed Anyway</button>';
            html += '</div>';
            html += '</div>';
            
            modal.innerHTML = html;
            overlay.appendChild(modal);
            document.body.appendChild(overlay);
            
            // Button handlers
            var proceedBtn = document.getElementById('duplicate-proceed-btn');
            var cancelBtn = document.getElementById('duplicate-cancel-btn');
            
            proceedBtn.onclick = function() {
                self.closeModal();
                if (onConfirm) onConfirm();
            };
            
            cancelBtn.onclick = function() {
                self.closeModal();
                self.resetAllForms();
                if (onCancel) onCancel();
            };
            
            // Close on overlay click
            overlay.onclick = function(e) {
                if (e.target === overlay) {
                    self.closeModal();
                    self.resetAllForms();
                    if (onCancel) onCancel();
                }
            };
            
            // ESC key support
            document.addEventListener('keydown', this.handleEscKey);
        },
        
        /**
         * Close the duplicate warning modal
         */
        closeModal: function() {
            var overlay = document.getElementById('duplicate-warning-overlay');
            if (overlay) {
                document.body.removeChild(overlay);
            }
            document.removeEventListener('keydown', this.handleEscKey);
        },
        
        /**
         * Reset all forms on the page - clears form data when Cancel is clicked
         * Compatible with ALL browsers: Chrome, Edge, Safari, Firefox, Opera Mini, IE11
         */
        resetAllForms: function() {
            // Common form IDs across all dashboards (TA, PMO, HR, L&D)
            var formIds = [
                'singleRequestForm',      // TA, PMO, HR, L&D single request forms
                'bulkUploadForm',         // Bulk upload forms
                'assignPointsForm',       // Alternative form name
                'pointsForm'              // Alternative form name
            ];
            
            // Reset forms by ID
            for (var i = 0; i < formIds.length; i++) {
                var form = document.getElementById(formIds[i]);
                if (form) {
                    form.reset();
                }
            }
            
            // Also reset any form with common action patterns
            var allForms = document.getElementsByTagName('form');
            for (var j = 0; j < allForms.length; j++) {
                var formAction = allForms[j].getAttribute('action') || '';
                // Check if it's an updater form (TA, PMO, HR, L&D)
                if (formAction.indexOf('updater') !== -1 || 
                    formAction.indexOf('assign') !== -1 ||
                    formAction.indexOf('points') !== -1) {
                    allForms[j].reset();
                }
            }
            
            // Reset dependent dropdowns (employee, grade) - common across dashboards
            var employeeSelect = document.getElementById('employee_id');
            var gradeSelect = document.getElementById('grade');
            
            if (employeeSelect) {
                employeeSelect.innerHTML = '<option value="">-- Select Grade First --</option>';
                employeeSelect.disabled = true;
            }
            
            if (gradeSelect) {
                gradeSelect.innerHTML = '<option value="">-- Select Department First --</option>';
                gradeSelect.disabled = true;
            }
            
            // Reset points preview if exists
            var pointsPreview = document.getElementById('points_preview');
            if (pointsPreview) {
                pointsPreview.textContent = 'Total points: 0';
            }
            
            // Reset file input for bulk upload
            var csvFile = document.getElementById('csv_file');
            if (csvFile) {
                csvFile.value = '';
            }
            
            // Reset review button state
            var reviewBtn = document.getElementById('reviewBulkButton');
            if (reviewBtn) {
                reviewBtn.disabled = true;
            }
            
            // Clear any validation results
            var validationResults = document.getElementById('validationResults');
            if (validationResults) {
                validationResults.innerHTML = '';
                validationResults.style.display = 'none';
            }
        },
        
        /**
         * Handle ESC key press
         */
        handleEscKey: function(e) {
            if (e.keyCode === 27 || e.key === 'Escape') {
                window.DuplicateDetection.closeModal();
                window.DuplicateDetection.resetAllForms();
            }
        },
        
        /**
         * Escape HTML to prevent XSS
         */
        escapeHtml: function(text) {
            var div = document.createElement('div');
            div.textContent = text || '';
            return div.innerHTML;
        },
        
        /**
         * Check bulk upload for duplicates
         * @param {Array} rows - Array of {employee_id, category_id, event_date}
         * @param {function} callback - Callback function(duplicates)
         */
        checkBulkUpload: function(rows, callback) {
            if (!rows || rows.length === 0) {
                console.log('DuplicateDetection.checkBulkUpload: No rows to check');
                callback([]);
                return;
            }

            console.log('DuplicateDetection.checkBulkUpload: Checking', rows.length, 'rows');
            console.log('DuplicateDetection.checkBulkUpload: Sample row:', rows[0]);

            var xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/duplicate/check-bulk', true);
            xhr.setRequestHeader('Content-Type', 'application/json');
            
            xhr.onreadystatechange = function() {
                if (xhr.readyState === 4) {
                    console.log('DuplicateDetection.checkBulkUpload: Response status:', xhr.status);
                    if (xhr.status === 200) {
                        try {
                            var response = JSON.parse(xhr.responseText);
                            console.log('DuplicateDetection.checkBulkUpload: Response:', response);
                            callback(response.duplicates || []);
                        } catch (e) {
                            console.error('Error parsing bulk duplicate check response:', e);
                            callback([]);
                        }
                    } else {
                        console.error('Bulk duplicate check failed:', xhr.status, xhr.responseText);
                        callback([]);
                    }
                }
            };
            
            var payload = JSON.stringify({ rows: rows });
            console.log('DuplicateDetection.checkBulkUpload: Sending payload:', payload);
            xhr.send(payload);
        },
        
        /**
         * Check if validator is approving/rejecting a duplicate
         * @param {string} requestId - Request ID being approved/rejected
         * @param {string} action - 'approve' or 'reject'
         * @param {function} callback - Callback function(isDuplicate, duplicateInfo)
         */
        checkValidatorAction: function(requestId, action, callback) {
            if (!requestId) {
                callback(false, null);
                return;
            }

            var xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/duplicate/check-validator-action', true);
            xhr.setRequestHeader('Content-Type', 'application/json');
            
            xhr.onreadystatechange = function() {
                if (xhr.readyState === 4) {
                    if (xhr.status === 200) {
                        try {
                            var response = JSON.parse(xhr.responseText);
                            callback(response.isDuplicate, response.duplicateInfo);
                        } catch (e) {
                            console.error('Error parsing validator action check:', e);
                            callback(false, null);
                        }
                    } else {
                        callback(false, null);
                    }
                }
            };
            
            xhr.send(JSON.stringify({ request_id: requestId, action: action }));
        },
        
        /**
         * Check bulk validator actions for duplicates
         * @param {Array} requestIds - Array of request IDs
         * @param {string} actionType - 'bulk_approve' or 'bulk_reject'
         * @param {function} callback - Callback function(duplicates)
         */
        checkBulkValidatorAction: function(requestIds, actionType, callback) {
            if (!requestIds || requestIds.length === 0) {
                callback([]);
                return;
            }

            var xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/duplicate/check-bulk-validator-action', true);
            xhr.setRequestHeader('Content-Type', 'application/json');
            
            xhr.onreadystatechange = function() {
                if (xhr.readyState === 4) {
                    if (xhr.status === 200) {
                        try {
                            var response = JSON.parse(xhr.responseText);
                            callback(response.duplicates || []);
                        } catch (e) {
                            console.error('Error parsing bulk validator action check:', e);
                            callback([]);
                        }
                    } else {
                        console.error('Bulk validator action check failed:', xhr.status);
                        callback([]);
                    }
                }
            };
            
            xhr.send(JSON.stringify({ request_ids: requestIds, action_type: actionType }));
        },
        
        /**
         * Show bulk duplicates warning
         * @param {Array} duplicates - Array of duplicate info
         * @param {function} onConfirm - Callback when user confirms
         * @param {function} onCancel - Callback when user cancels
         * @param {object} options - Optional configuration {actionType: 'bulk_approve'|'bulk_reject'|'bulk_upload'}
         */
        showBulkDuplicatesWarning: function(duplicates, onConfirm, onCancel, options) {
            var self = this;
            options = options || {};
            var actionType = options.actionType || 'bulk_upload';
            
            var overlay = document.createElement('div');
            overlay.id = 'duplicate-warning-overlay';
            overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center;overflow:auto;';
            
            var modal = document.createElement('div');
            modal.id = 'duplicate-warning-modal';
            modal.style.cssText = 'background:white;border-radius:8px;padding:24px;max-width:850px;width:95%;max-height:85vh;overflow:auto;box-shadow:0 4px 20px rgba(0,0,0,0.3);';
            
            // Determine title and button text based on action type
            var title = 'Bulk Upload - Duplicates Detected';
            var cancelText = 'Cancel';
            var proceedText = 'Proceed Anyway';
            var proceedColor = '#ff9800';
            
            if (actionType === 'bulk_approve') {
                title = 'Bulk Approve - Duplicates Detected';
                proceedText = 'Bulk Approve';
                proceedColor = '#28a745';
            } else if (actionType === 'bulk_reject') {
                title = 'Bulk Reject - Duplicates Detected';
                proceedText = 'Bulk Reject';
                proceedColor = '#dc3545';
            }
            
            // ✅ Group duplicates by employee+category+date to show unique rows
            var grouped = {};
            for (var i = 0; i < duplicates.length; i++) {
                var dup = duplicates[i];
                var key = (dup.employeeName || '') + '_' + (dup.categoryName || '') + '_' + (dup.eventDate || '');
                
                if (!grouped[key]) {
                    grouped[key] = {
                        employeeName: dup.employeeName,
                        categoryName: dup.categoryName,
                        eventDate: dup.eventDate,
                        rows: [],
                        status: dup.status,
                        approvedCount: dup.approvedCount || 0,
                        pendingCount: dup.pendingCount || 0,
                        pendingDetails: dup.pendingDetails || []
                    };
                }
                grouped[key].rows.push(dup.rowNumber || (i + 1));
                // Update counts if this duplicate has higher values
                if (dup.approvedCount > grouped[key].approvedCount) {
                    grouped[key].approvedCount = dup.approvedCount;
                }
                if (dup.pendingCount > grouped[key].pendingCount) {
                    grouped[key].pendingCount = dup.pendingCount;
                    grouped[key].pendingDetails = dup.pendingDetails || [];
                }
                // Keep the most informative status
                if (dup.status !== 'Duplicate in Upload' && dup.status !== 'Duplicate in Selection') {
                    grouped[key].status = dup.status;
                }
            }
            
            // Convert grouped object to array and sort row numbers
            var groupedList = [];
            for (var k in grouped) {
                if (grouped.hasOwnProperty(k)) {
                    // Sort row numbers numerically
                    grouped[k].rows.sort(function(a, b) { return a - b; });
                    
                    // Store the first row number for sorting purposes
                    grouped[k].firstRowNumber = grouped[k].rows[0];
                    
                    // ✅ FIXED: First row is unique, only subsequent rows are duplicates
                    // For bulk upload/selection, the first occurrence is the "original"
                    // Only show the 2nd, 3rd, etc. rows as duplicates
                    if (grouped[k].rows.length > 1) {
                        grouped[k].originalRow = grouped[k].rows[0]; // Store first row (unique)
                        grouped[k].rows = grouped[k].rows.slice(1);  // Remove first row, keep only duplicates
                    }
                    
                    // Only add to list if there are duplicate rows to show
                    // (either internal duplicates after removing first, or database duplicates)
                    if (grouped[k].rows.length > 0 || grouped[k].approvedCount > 0 || grouped[k].pendingCount > 0) {
                        groupedList.push(grouped[k]);
                    }
                }
            }
            
            // Sort groupedList by the first row number so they appear in order
            groupedList.sort(function(a, b) {
                // Use firstRowNumber which was stored before any modifications
                var aFirst = a.firstRowNumber || 999999;
                var bFirst = b.firstRowNumber || 999999;
                return aFirst - bFirst;
            });
            
            // ✅ Calculate total duplicate rows (only the duplicate rows, not the first/unique ones)
            var totalDuplicateRows = 0;
            for (var j = 0; j < groupedList.length; j++) {
                totalDuplicateRows += groupedList[j].rows.length;
            }
            
            // If no duplicates to show, don't display the modal
            if (groupedList.length === 0) {
                if (onConfirm) onConfirm();
                return;
            }
            
            var html = '<div style="text-align:center;">';
            html += '<div style="font-size:48px;color:#ff9800;margin-bottom:16px;">⚠️</div>';
            html += '<h3 style="margin:0 0 16px 0;color:#333;font-size:20px;">' + this.escapeHtml(title) + '</h3>';
            html += '<p style="color:#666;margin:0 0 20px 0;">Found ' + totalDuplicateRows + ' duplicate row(s) in ' + groupedList.length + ' group(s):</p>';
            html += '<div style="max-height:300px;overflow:auto;text-align:left;margin-bottom:20px;">';
            html += '<table style="width:100%;border-collapse:collapse;font-size:13px;">';
            html += '<thead><tr style="background:#f5f5f5;"><th style="padding:8px;border:1px solid #ddd;">Duplicate Row(s)</th><th style="padding:8px;border:1px solid #ddd;">Employee</th><th style="padding:8px;border:1px solid #ddd;">Category</th><th style="padding:8px;border:1px solid #ddd;">Date</th><th style="padding:8px;border:1px solid #ddd;">Existing Status</th></tr></thead>';
            html += '<tbody>';
            for (var i = 0; i < groupedList.length; i++) {
                var grp = groupedList[i];
                html += '<tr>';
                // Show row numbers - use firstRowNumber if rows array is empty (for "Already Approved" only items)
                var rowDisplay = grp.rows.length > 0 ? grp.rows.join(', ') : (grp.firstRowNumber || '');
                html += '<td style="padding:8px;border:1px solid #ddd;">' + rowDisplay + '</td>';
                html += '<td style="padding:8px;border:1px solid #ddd;">' + this.escapeHtml(grp.employeeName) + '</td>';
                html += '<td style="padding:8px;border:1px solid #ddd;">' + this.escapeHtml(grp.categoryName) + '</td>';
                html += '<td style="padding:8px;border:1px solid #ddd;">' + this.escapeHtml(grp.eventDate) + '</td>';
                
                // ✅ Build status display
                var statusHtml = '';
                // Check if this group has duplicates within upload/selection (originalRow exists means we had multiple rows)
                var hasDuplicateInUpload = grp.originalRow !== undefined || grp.status === 'Duplicate in Upload' || grp.status === 'Duplicate in Selection';
                var isValidatorAction = (actionType === 'bulk_approve' || actionType === 'bulk_reject');
                var duplicateLabel = isValidatorAction ? 'Duplicate in Selection' : 'Duplicate in Upload';
                
                if (isValidatorAction) {
                    // For validator actions (bulk approve/reject): show approved count and duplicate in selection
                    var parts = [];
                    if (grp.approvedCount > 0) {
                        parts.push('<strong style="color:#dc3545;">' + grp.approvedCount + ' Already Approved</strong>');
                    }
                    if (hasDuplicateInUpload) {
                        parts.push('<strong style="color:#ff9800;">' + duplicateLabel + '</strong>');
                    }
                    statusHtml = parts.join(' + ');
                } else {
                    // For bulk upload: show approved/pending counts first, then Duplicate in Upload
                    var parts = [];
                    
                    // ✅ Order: Already Approved → Already Pending → Duplicate in Upload
                    if (grp.approvedCount > 0) {
                        parts.push('<strong style="color:#dc3545;">' + grp.approvedCount + ' Already Approved</strong>');
                    }
                    if (grp.pendingCount > 0) {
                        parts.push('<strong style="color:#17a2b8;">' + grp.pendingCount + ' Already Pending</strong>');
                    }
                    if (hasDuplicateInUpload) {
                        parts.push('<strong style="color:#ff9800;">' + duplicateLabel + '</strong>');
                    }
                    
                    if (parts.length > 0) {
                        statusHtml = parts.join(' + ');
                    } else {
                        statusHtml = '<strong style="color:#333;">' + this.escapeHtml(grp.status) + '</strong>';
                    }
                }
                
                html += '<td style="padding:8px;border:1px solid #ddd;vertical-align:top;">' + statusHtml + '</td>';
                html += '</tr>';
            }
            html += '</tbody></table></div>';
            // ✅ Show custom message for validator actions
            var warningMessage = 'Do you want to proceed anyway?';
            if (duplicates.length > 0 && (actionType === 'bulk_approve' || actionType === 'bulk_reject')) {
                // Count different types of duplicates
                var approvedDuplicates = duplicates.filter(function(d) { return d.approvedCount > 0; });
                var internalDuplicates = duplicates.filter(function(d) { return d.status === 'Duplicate in Selection'; });
                
                if (internalDuplicates.length > 0 && approvedDuplicates.length > 0) {
                    warningMessage = 'Found duplicates within your selection AND records already approved in the system.<br><br>Do you want to proceed anyway?';
                } else if (internalDuplicates.length > 0) {
                    warningMessage = 'You have selected duplicate records (same employee, category, and date).<br><br>Do you want to proceed anyway?';
                } else if (approvedDuplicates.length > 0) {
                    warningMessage = 'These employees, categories, and event dates are already approved.<br><br>Do you want to proceed anyway?';
                } else {
                    warningMessage = 'Multiple pending records exist for these dates.<br><br>Do you want to proceed anyway?';
                }
            }
            html += '<p style="color:#666;margin:0 0 24px 0;">' + warningMessage + '</p>';
            html += '<div style="display:flex;gap:12px;justify-content:center;">';
            html += '<button id="duplicate-cancel-btn" style="padding:10px 24px;border:1px solid #ddd;background:white;color:#333;border-radius:4px;cursor:pointer;font-size:14px;">' + this.escapeHtml(cancelText) + '</button>';
            html += '<button id="duplicate-proceed-btn" style="padding:10px 24px;border:none;background:' + proceedColor + ';color:white;border-radius:4px;cursor:pointer;font-size:14px;">' + this.escapeHtml(proceedText) + '</button>';
            html += '</div></div>';
            
            modal.innerHTML = html;
            overlay.appendChild(modal);
            document.body.appendChild(overlay);
            
            document.getElementById('duplicate-proceed-btn').onclick = function() {
                self.closeModal();
                if (onConfirm) onConfirm();
            };
            
            document.getElementById('duplicate-cancel-btn').onclick = function() {
                self.closeModal();
                self.resetAllForms();
                if (onCancel) onCancel();
            };
            
            overlay.onclick = function(e) {
                if (e.target === overlay) {
                    self.closeModal();
                    self.resetAllForms();
                    if (onCancel) onCancel();
                }
            };
            
            document.addEventListener('keydown', this.handleEscKey);
        },
        
        /**
         * Intercept form submission and check for duplicates
         * @param {HTMLFormElement} form - The form element
         * @param {object} options - Configuration options
         */
        interceptFormSubmission: function(form, options) {
            var self = this;
            options = options || {};
            
            var originalSubmit = form.onsubmit;
            
            form.onsubmit = function(e) {
                // If already confirmed, proceed
                if (self.pendingSubmission && self.pendingSubmission.confirmed) {
                    self.pendingSubmission = null;
                    return true;
                }
                
                // Prevent default submission
                e.preventDefault();
                
                // Get form values
                var employeeId = options.getEmployeeId ? options.getEmployeeId(form) : form.querySelector('[name="employee_id"]').value;
                var categoryId = options.getCategoryId ? options.getCategoryId(form) : form.querySelector('[name="category_id"]').value;
                var eventDate = options.getEventDate ? options.getEventDate(form) : form.querySelector('[name="event_date"]').value;
                
                // Check for duplicates
                self.checkSingleRequest(employeeId, categoryId, eventDate, function(isDuplicate, duplicateInfo) {
                    if (isDuplicate) {
                        // Show warning popup
                        self.showDuplicateWarning(
                            duplicateInfo,
                            function() {
                                // User confirmed - proceed with submission
                                self.pendingSubmission = { confirmed: true };
                                form.submit();
                            },
                            function() {
                                // User cancelled
                                self.pendingSubmission = null;
                            }
                        );
                    } else {
                        // No duplicate - proceed with submission
                        form.submit();
                    }
                });
                
                return false;
            };
        },
        
        /**
         * Intercept validator action buttons
         * @param {string} buttonSelector - CSS selector for approve/reject buttons
         * @param {string} action - 'approve' or 'reject'
         */
        interceptValidatorAction: function(buttonSelector, action) {
            var self = this;
            var buttons = document.querySelectorAll(buttonSelector);
            
            buttons.forEach(function(button) {
                button.addEventListener('click', function(e) {
                    if (button.dataset.duplicateChecked === 'true') {
                        return true;
                    }
                    
                    e.preventDefault();
                    e.stopPropagation();
                    
                    var requestId = button.dataset.requestId || button.getAttribute('data-request-id');
                    
                    if (!requestId) {
                        return true;
                    }
                    
                    self.checkValidatorAction(requestId, action, function(isDuplicate, duplicateInfo) {
                        if (isDuplicate) {
                            var actionText = action === 'approve' ? 'approving' : 'rejecting';
                            duplicateInfo.message = 'You are ' + actionText + ' a request that already has an approved record.';
                            
                            self.showDuplicateWarning(
                                duplicateInfo,
                                function() {
                                    button.dataset.duplicateChecked = 'true';
                                    button.click();
                                },
                                function() {
                                    // User cancelled
                                }
                            );
                        } else {
                            button.dataset.duplicateChecked = 'true';
                            button.click();
                        }
                    });
                    
                    return false;
                });
            });
        }
    };
    
    // Auto-initialize for PMO and HR forms when DOM is ready
    // Note: TA and LD handle duplicate detection manually in their own scripts
    // to support their confirmation modal flow
    function initializeDuplicateDetection() {
        // PMO Single Request Form
        var pmoForm = document.querySelector('form[action*="pmo/updater"]');
        if (pmoForm) {
            window.DuplicateDetection.interceptFormSubmission(pmoForm);
        }
        
        // HR Single Request Form
        var hrForm = document.querySelector('form[action*="hr/updater"]');
        if (hrForm) {
            window.DuplicateDetection.interceptFormSubmission(hrForm);
        }
    }
    
    // Cross-browser DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeDuplicateDetection);
    } else {
        initializeDuplicateDetection();
    }
    
})();
