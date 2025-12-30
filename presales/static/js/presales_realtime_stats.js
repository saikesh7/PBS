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
        
        // Determine rate class for styling
        var rateClass = 'zero';
        if (participationRate >= 75) rateClass = 'excellent';
        else if (participationRate >= 50) rateClass = 'good';
        else if (participationRate >= 25) rateClass = 'average';
        else if (participationRate > 0) rateClass = 'low';
        
        // Build row HTML matching the template styling
        var rowHTML = '<td><span class="grade-badge">' + grade + '</span></td>' +
            '<td><strong style="font-size: 1.1rem; color: #1e293b;">' + stats.total_employees + '</strong></td>' +
            '<td class="participation-cell">';
        
        if (stats.total_employees > 0) {
            // Get icon based on rate
            var icon = '📈';
            if (participationRate >= 75) icon = '🔥';
            else if (participationRate >= 50) icon = '⭐';
            else if (participationRate >= 25) icon = '📊';
            
            rowHTML += '<div class="participation-wrapper">' +
                '<div class="participation-visual">' +
                '<div class="participation-progress">' +
                '<div class="participation-bar rate-' + rateClass + '" style="width: ' + participationRate + '%;" data-rate="' + participationRate + '">';
            
            if (participationRate >= 15) {
                rowHTML += '<span class="participation-icon">' + icon + '</span>' + participationRate + '%';
            }
            
            rowHTML += '</div></div>' +
                '<div class="participation-details">' +
                '<i class="fas fa-users" style="color: #3b82f6;"></i>' +
                '<span>' + stats.employees_with_points + ' of ' + stats.total_employees + ' participating</span>' +
                '</div></div>' +
                '<div class="participation-badge ' + rateClass + '">' + participationRate + '%</div>' +
                '</div>';
        } else {
            rowHTML += '<div class="text-muted fst-italic"><i class="fas fa-user-slash me-1"></i>No Employees</div>';
        }
        
        rowHTML += '</td><td>';
        
        if (stats.total_employees > 0) {
            rowHTML += '<span class="points-badge">' + stats.total_points + '</span>';
        } else {
            rowHTML += '<span class="badge bg-secondary">-</span>';
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

// ✅ Auto-update quarterly stats on page load
document.addEventListener('DOMContentLoaded', function() {
    // Update stats on page load to ensure fresh data
    updateQuarterlyStats();
});
