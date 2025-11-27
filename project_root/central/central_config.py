from flask import render_template, request, redirect, url_for, flash
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
from . import central_bp
from .central_utils import check_central_access, error_print

@central_bp.route('/config', methods=['GET', 'POST'])
def reward_config():
    """Configuration page for reward targets and milestones"""
    has_access, user = check_central_access()
    
    if not has_access:
        if not user:
            flash('You need to log in first', 'warning')
        else:
            flash('You do not have permission to access the Central dashboard', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        # Get current configuration
        config = mongo.db.reward_config.find_one({}) or {
            "grade_targets": {
                "A1": 3650, "B1": 4350, "B2": 5250,
                "C1": 8100, "C2": 9100, "D1": 7300, "D2": 6800
            },
            "milestones": [
                {"name": "Milestone 1", "description": "100% of Qtr target", "percentage": 25, "bonus_points": {"Q1": 1000, "Q2": 1000, "Q3": 1000, "Q4": 1000}},
                {"name": "Milestone 2", "description": "50% of Yearly target", "percentage": 50, "bonus_points": {"Q1": 2000, "Q2": 2000, "Q3": 0, "Q4": 0}},
                {"name": "Milestone 3", "description": "75% of Yearly target", "percentage": 75, "bonus_points": {"Q1": 3000, "Q2": 2000, "Q3": 0, "Q4": 0}},
                {"name": "Milestone 4", "description": "100% of Yearly target", "percentage": 100, "bonus_points": {"Q1": 4000, "Q2": 3000, "Q3": 2000, "Q4": 0}}
            ],
            "utilization_threshold": 80,
            "yearly_bonus_limit": 10000,
            "last_updated": datetime.utcnow(),
            "updated_by": ObjectId(user["_id"])
        }
        
        # If no configuration exists, create it
        if '_id' not in config:
            mongo.db.reward_config.insert_one(config)
        
        # If POST request, update configuration
        if request.method == 'POST':
            if 'save_targets' in request.form:
                # Update grade targets
                new_targets = {}
                for grade in ["A1", "B1", "B2", "C1", "C2", "D1", "D2"]:
                    try:
                        target_value = int(request.form.get(f"target_{grade}", 0))
                        new_targets[grade] = target_value
                    except ValueError:
                        flash(f'Invalid target value for grade {grade}', 'danger')
                        return redirect(url_for('central.reward_config'))
                
                # Update utilization threshold
                try:
                    utilization_threshold = int(request.form.get("utilization_threshold", 80))
                except ValueError:
                    utilization_threshold = 80
                
                # Update yearly bonus points limit
                try:
                    yearly_bonus_limit = int(request.form.get("yearly_bonus_limit", 10000))
                except ValueError:
                    yearly_bonus_limit = 10000
                
                # Update configuration
                mongo.db.reward_config.update_one(
                    {"_id": config["_id"]},
                    {"$set": {
                        "grade_targets": new_targets,
                        "utilization_threshold": utilization_threshold,
                        "yearly_bonus_limit": yearly_bonus_limit,
                        "last_updated": datetime.utcnow(),
                        "updated_by": ObjectId(user["_id"])
                    }}
                )
                
                flash('Grade targets updated successfully', 'success')
                return redirect(url_for('central.reward_config'))
                
            elif 'save_milestone' in request.form:
                # Get milestone index
                milestone_idx = int(request.form.get('milestone_idx', 0))
                
                # Validate index
                if milestone_idx < 0 or milestone_idx >= len(config['milestones']):
                    flash('Invalid milestone index', 'danger')
                    return redirect(url_for('central.reward_config'))
                
                # Update milestone
                new_milestone = {
                    "name": request.form.get('milestone_name', ''),
                    "description": request.form.get('milestone_description', ''),
                    "percentage": int(request.form.get('milestone_percentage', 0)),
                    "bonus_points": {
                        "Q1": int(request.form.get('bonus_q1', 0)),
                        "Q2": int(request.form.get('bonus_q2', 0)),
                        "Q3": int(request.form.get('bonus_q3', 0)),
                        "Q4": int(request.form.get('bonus_q4', 0))
                    }
                }
                
                # Update milestone in config
                milestones = config['milestones']
                milestones[milestone_idx] = new_milestone
                
                # Update in database
                mongo.db.reward_config.update_one(
                    {"_id": config["_id"]},
                    {"$set": {
                        "milestones": milestones,
                        "last_updated": datetime.utcnow(),
                        "updated_by": ObjectId(user["_id"])
                    }}
                )
                
                flash('Milestone updated successfully', 'success')
                return redirect(url_for('central.reward_config'))
                
            elif 'add_milestone' in request.form:
                # Create new milestone
                new_milestone = {
                    "name": request.form.get('new_milestone_name', ''),
                    "description": request.form.get('new_milestone_description', ''),
                    "percentage": int(request.form.get('new_milestone_percentage', 0)),
                    "bonus_points": {
                        "Q1": int(request.form.get('new_bonus_q1', 0)),
                        "Q2": int(request.form.get('new_bonus_q2', 0)),
                        "Q3": int(request.form.get('new_bonus_q3', 0)),
                        "Q4": int(request.form.get('new_bonus_q4', 0))
                    }
                }
                
                # Add to config
                mongo.db.reward_config.update_one(
                    {"_id": config["_id"]},
                    {"$push": {
                        "milestones": new_milestone
                    },
                    "$set": {
                        "last_updated": datetime.utcnow(),
                        "updated_by": ObjectId(user["_id"])
                    }}
                )
                
                flash('New milestone added successfully', 'success')
                return redirect(url_for('central.reward_config'))
        
        # Get the user who last updated the config
        updater = None
        if 'updated_by' in config:
            updater = mongo.db.users.find_one({"_id": config["updated_by"]})
        
        return render_template(
            'central_config.html',
            config=config,
            updater=updater,
            user=user
        )
        
    except Exception as e:
        error_print("Error in reward configuration", e)
        flash('An error occurred while managing configuration', 'danger')
        return redirect(url_for('central.dashboard'))