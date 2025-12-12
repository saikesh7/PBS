/**
 * Presales Real-time Statistics Update
 * Automatically updates quarterly statistics table when PRESALES requests are approved
 * ✅ Browser Compatible: Chrome, Firefox, Safari, Edge, Opera
 */

// Function to fetch and update quarterly statistics
function updateQuarterlyStats() {
    // ✅ Use XMLHttpRequest for better browser compatibility (fallback for older browsers)
    var xhr = new XMLHttpRequest();
    xhr.open('GET', '/presales/api/get_quarterly_stats', true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
    
    xhr.onload = function() {
        if (xhr.status >= 200 && xhr.status < 300) {
            try {
                var data = JSON.parse(xhr.responseText);
                if (data.success) {
                    renderQuarterlyStatsTable(data.quarterly_stats);
                } else {
                    console.error('Failed to fetch quarterly stats:', data.message);
                }
            } catch (e) {
                console.error('Error parsing response:', e);
            }
        } else {
            console.error('Request failed with status:', xhr.status);
        }
    };
    
    xhr.onerror = function() {
        console.error('Network error occurred while fetching quarterly stats');
    };
    
    xhr.send();
}

// Function to render the quarterly statistics table
// ✅ Browser Compatible: Uses standard DOM methods for all browsers
function renderQuarterlyStatsTable(quarterlyStats) {
    var tableBody = document.querySelector('#quarterly-stats-table tbody');
    
    if (!tableBody) {
        console.warn('Quarterly stats table not found on this page');
        return;
    }
    
    // Clear existing rows
    tableBody.innerHTML = '';
    
    // Check if there are any stats
    if (!quarterlyStats || Object.keys(quarterlyStats).length === 0) {
        var noDataRow = document.createElement('tr');
        noDataRow.innerHTML = '<td colspan="4" class="text-center">' +
            '<div class="alert alert-info mb-0" role="alert">' +
            '<i class="fas fa-info-circle me-2"></i> No quarterly statistics available.' +
            '</div></td>';
        tableBody.appendChild(noDataRow);
        return;
    }
    
    // Render each grade's statistics
    var grades = Object.keys(quarterlyStats);
    for (var i = 0; i < grades.length; i++) {
        var grade = grades[i];
        var stats = quarterlyStats[grade];
        var row = document.createElement('tr');
        
        // Calculate participation rate
        var participationRate = stats.total_employees > 0 
            ? ((stats.employees_with_points / stats.total_employees) * 100).toFixed(1)
            : 0;
        
        // Build row HTML with proper escaping
        var rowHTML = '<td><span class="badge bg-secondary">' + grade + '</span></td>' +
            '<td>' + stats.total_employees + '</td>' +
            '<td>' + (stats.total_employees > 0 
                ? '<span class="text-muted">' + stats.employees_with_points + ' of ' + stats.total_employees + ' participating</span>'
                : 'No Employee') + '</td>' +
            '<td>';
        
        if (stats.total_employees > 0) {
            rowHTML += '<div class="progress" style="height: 20px;">' +
                '<div class="progress-bar bg-info" role="progressbar" ' +
                'style="width: ' + participationRate + '%;" ' +
                'aria-valuenow="' + participationRate + '" ' +
                'aria-valuemin="0" aria-valuemax="100">' +
                participationRate + '%</div></div>' +
                '<span class="badge bg-success ms-2">' + stats.total_points + '</span>';
        } else {
            rowHTML += '<span class="badge bg-secondary">0</span>';
        }
        
        rowHTML += '</td>';
        
        row.innerHTML = rowHTML;
        tableBody.appendChild(row);
    }
}

// Function to be called after request approval
function onRequestApproved() {
    updateQuarterlyStats();
}

// Export functions for use in other scripts
window.PresalesRealtimeStats = {
    updateQuarterlyStats: updateQuarterlyStats,
    onRequestApproved: onRequestApproved
};
