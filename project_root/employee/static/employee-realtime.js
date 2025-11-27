
document.addEventListener('DOMContentLoaded', function() {
    var socket = io(); // Connect to the Socket.IO server

    // Function to update the leaderboard UI
    function updateLeaderboardUI(data) {
        console.log("Updating leaderboard UI with data:", data);

        // Update Your Rank section
        if (data.user_rank_details) {
            document.getElementById('currentUserRankValue').textContent = data.user_rank_details.rank;
            document.getElementById('currentUserPointsValue').textContent = data.user_rank_details.points;
            document.getElementById('currentUserDetails').textContent = `Dept: ${data.user_rank_details.department} | Grade: ${data.user_rank_details.grade}`;
        } else {
            document.getElementById('currentUserRankValue').textContent = 'N/A';
            document.getElementById('currentUserPointsValue').textContent = 'N/A';
            document.getElementById('currentUserDetails').textContent = 'Dept: N/A | Grade: N/A';
        }

        // Update Next Rank section
        const nextRankInfo = document.getElementById('nextRankInfo');
        const atTopRankInfo = document.getElementById('atTopRankInfo');
        const noRankInfo = document.getElementById('noRankInfo');

        if (data.user_rank_details && data.user_rank_details.rank === 1) {
            atTopRankInfo.style.display = 'block';
            nextRankInfo.style.display = 'none';
            noRankInfo.style.display = 'none';
        } else if (data.person_above) {
            atTopRankInfo.style.display = 'none';
            nextRankInfo.style.display = 'block';
            noRankInfo.style.display = 'none';
            document.getElementById('nextRankMessage').textContent = `Needs ${data.points_to_next_rank} points to reach next rank`;
            document.getElementById('personAboveName').textContent = data.person_above.name;
        } else {
            atTopRankInfo.style.display = 'none';
            nextRankInfo.style.display = 'none';
            noRankInfo.style.display = 'block';
        }

        // Update Top Performers section
        const topPerformersRow = document.getElementById('topPerformersRow');
        const noTopPerformers = document.getElementById('noTopPerformers');
        
        // Hide all performer cards initially
        for (let i = 1; i <= 3; i++) {
            document.getElementById(`performerCard${i}`).style.display = 'none';
        }

        if (data.top_3_employees && data.top_3_employees.length > 0) {
            noTopPerformers.style.display = 'none';
            data.top_3_employees.forEach((performer, index) => {
                const cardIndex = index + 1;
                if (cardIndex <= 3) {
                    document.getElementById(`performerCard${cardIndex}`).style.display = 'block';
                    document.getElementById(`performerName${cardIndex}`).textContent = performer.name;
                    document.getElementById(`performerDept${cardIndex}`).textContent = performer.department;
                    document.getElementById(`performerGrade${cardIndex}`).textContent = performer.grade;
                    document.getElementById(`performerPoints${cardIndex}`).textContent = performer.points;
                }
            });
        } else {
            noTopPerformers.style.display = 'block';
        }

        // Update Detailed Rankings table
        const leaderboardTableBody = document.getElementById('leaderboardTableBody');
        leaderboardTableBody.innerHTML = ''; // Clear existing rows

        if (data.leaderboard_table_data && data.leaderboard_table_data.length > 0) {
            document.getElementById('leaderboardNoData').style.display = 'none';
            data.leaderboard_table_data.forEach(entry => {
                const row = leaderboardTableBody.insertRow();
                row.insertCell().textContent = entry.rank;
                row.insertCell().textContent = entry.name;
                row.insertCell().textContent = entry.department;
                row.insertCell().textContent = entry.grade;
                row.insertCell().textContent = entry.points;
            });
        } else {
            document.getElementById('leaderboardNoData').style.display = 'block';
        }
    }

    // Initial load of leaderboard data
    if (typeof initialLeaderboardData !== 'undefined' && initialLeaderboardData) {
        updateLeaderboardUI(initialLeaderboardData);
    }

    // Listen for real-time leaderboard updates
    socket.on('leaderboard_update', function(data) {
        console.log("Received real-time leaderboard update:", data);
        updateLeaderboardUI(data);
    });

    // Listen for individual points update (e.g., after a request is approved)
    // This might trigger a full leaderboard refresh from the server
    socket.on('points_awarded', function(data) {
        console.log("Received points awarded event:", data);
        // Request updated leaderboard data from the server
        socket.emit('request_leaderboard_update', { user_id: data.user_id });
    });

    // Handle filter changes and apply button click
    const applyLeaderboardFiltersBtn = document.getElementById('applyLeaderboardFilters');
    const resetLeaderboardFiltersBtn = document.getElementById('resetLeaderboardFilters');
    const leaderboardDepartmentFilter = document.getElementById('leaderboardDepartmentFilter');
    const leaderboardGradeFilter = document.getElementById('leaderboardGradeFilter');
    const leaderboardCategoryFilter = document.getElementById('leaderboardCategoryFilter');
    const leaderboardQuarterFilter = document.getElementById('leaderboardQuarterFilter');

    function applyFilters() {
        const filters = {
            department: leaderboardDepartmentFilter.value,
            grade: leaderboardGradeFilter.value,
            category: leaderboardCategoryFilter.value,
            quarter: leaderboardQuarterFilter.value
        };
        console.log("Applying leaderboard filters:", filters);
        socket.emit('request_leaderboard_update', { filters: filters });
    }

    if (applyLeaderboardFiltersBtn) {
        applyLeaderboardFiltersBtn.addEventListener('click', applyFilters);
    }

    if (resetLeaderboardFiltersBtn) {
        resetLeaderboardFiltersBtn.addEventListener('click', function() {
            leaderboardDepartmentFilter.value = 'all';
            leaderboardGradeFilter.value = 'all';
            leaderboardCategoryFilter.value = 'all';
            leaderboardQuarterFilter.value = 'all';
            applyFilters(); // Apply filters after resetting
        });
    }

    // Initial filter application on tab show (if leaderboard tab is active)
    $('a[data-bs-toggle="tab"]').on('shown.bs.tab', function (e) {
        const target = $(e.target).attr("data-bs-target");
        if (target === '#leaderboard') {
            // Ensure filters are applied when the leaderboard tab becomes active
            applyFilters();
        }
    });

    // If leaderboard tab is active on initial load, apply filters
    if ($('#leaderboard').hasClass('active')) {
        applyFilters();
    }
});
