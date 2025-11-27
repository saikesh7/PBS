/**
 * Presales Real-time Statistics Update
 * Automatically updates quarterly statistics table when requests are approved
 */

// Function to fetch and update quarterly statistics
function updateQuarterlyStats() {
    fetch('/presales/api/get_quarterly_stats', {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            renderQuarterlyStatsTable(data.quarterly_stats);
        } else {
            console.error('❌ Failed to fetch quarterly stats:', data.message);
        }
    })
    .catch(error => {
        console.error('❌ Error fetching quarterly stats:', error);
    });
}

// Function to render the quarterly statistics table
function renderQuarterlyStatsTable(quarterlyStats) {
    const tableBody = document.querySelector('#quarterly-stats-table tbody');
    
    if (!tableBody) {
        console.warn('⚠️ Quarterly stats table not found on this page');
        return;
    }
    
    // Clear existing rows
    tableBody.innerHTML = '';
    
    // Check if there are any stats
    if (!quarterlyStats || Object.keys(quarterlyStats).length === 0) {
        const noDataRow = document.createElement('tr');
        noDataRow.innerHTML = `
            <td colspan="6" class="text-center">
                <div class="alert alert-info mb-0" role="alert">
                    <i class="fas fa-info-circle me-2"></i> No quarterly statistics available.
                </div>
            </td>
        `;
        tableBody.appendChild(noDataRow);
        return;
    }
    
    // Render each grade's statistics
    Object.keys(quarterlyStats).forEach(grade => {
        const stats = quarterlyStats[grade];
        const row = document.createElement('tr');
        
        // Calculate participation rate
        const participationRate = stats.total_employees > 0 
            ? ((stats.employees_with_points / stats.total_employees) * 100).toFixed(1)
            : 0;
        
        row.innerHTML = `
            <td><span class="badge bg-secondary">${grade}</span></td>
            <td>${stats.total_employees}</td>
            <td>${stats.total_employees > 0 ? stats.employees_with_presales_rfp : 'No Employee'}</td>
            <td>
                ${stats.total_employees > 0 ? `
                    <div class="progress" style="height: 20px;">
                        <div class="progress-bar bg-info" role="progressbar" 
                             style="width: ${participationRate}%;" 
                             aria-valuenow="${participationRate}" 
                             aria-valuemin="0" 
                             aria-valuemax="100">
                            ${participationRate}%
                        </div>
                    </div>
                ` : 'No Employee'}
            </td>
            <td>${stats.total_employees > 0 ? stats.total_presales_rfp_points : 'No Employee'}</td>
            <td>
                ${stats.total_employees > 0 
                    ? `<span class="badge bg-success">${stats.total_points}</span>`
                    : `<span class="badge bg-secondary">No Employee</span>`
                }
            </td>
        `;
        
        tableBody.appendChild(row);
    });
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
