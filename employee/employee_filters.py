from flask import Blueprint, request, session, jsonify
from extensions import mongo
from datetime import datetime
import sys
import traceback
from bson.objectid import ObjectId

employee_filters_bp = Blueprint('employee_filters', __name__, url_prefix='/employee')



@employee_filters_bp.route('/get-total-points-filters', methods=['GET'])
def get_total_points_filters():
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        user_id_obj = ObjectId(user_id)
        
        utilization_category = mongo.db.categories.find_one({"code": "utilization_billable"})
        utilization_id = utilization_category["_id"] if utilization_category else None
        
        distinct_category_ids = set()
        
        pr_pipeline = [
            {"$match": {
                "user_id": user_id_obj,
                "status": "Approved",
                "category_id": {"$ne": utilization_id} if utilization_id else {"$exists": True, "$ne": None}
            }},
            {"$group": {"_id": "$category_id"}}
        ]
        for d in mongo.db.points_request.aggregate(pr_pipeline):
            if d.get("_id"):
                distinct_category_ids.add(d["_id"])
        
        p_pipeline = [
            {"$match": {
                "user_id": user_id_obj,
                "category_id": {"$ne": utilization_id} if utilization_id else {"$exists": True, "$ne": None}
            }},
            {"$group": {"_id": "$category_id"}}
        ]
        for d in mongo.db.points.aggregate(p_pipeline):
            if d.get("_id"):
                distinct_category_ids.add(d["_id"])
        
        categories = []
        if distinct_category_ids:
            categories = list(mongo.db.categories.find(
                {"_id": {"$in": list(distinct_category_ids)}},
                {"name": 1}
            ))
        
        possible_sources = ["employee", "manager", "ta", "pmo", "ld"]
        available_sources = []
        for s in possible_sources:
            count_pr = mongo.db.points_request.count_documents({"source": s, "user_id": user_id_obj})
            count_p = mongo.db.points.count_documents({"source": s, "user_id": user_id_obj})
            if count_pr + count_p > 0:
                available_sources.append(s)
        
        if 'employee' not in available_sources:
            available_sources.insert(0, 'employee')
        if 'manager' not in available_sources:
            if 'employee' in available_sources:
                available_sources.insert(1, 'manager')
            else:
                available_sources.insert(0, 'manager')
        
        return jsonify({
            "categories": [{"_id": str(c["_id"]), "name": c.get("name", "Unnamed")} for c in sorted(categories, key=lambda x: x.get('name', ''))],
            "sources": available_sources
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@employee_filters_bp.route('/get-utilization-by-month')
def get_utilization_by_month():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'User not authenticated'}), 401
    
    try:
        month = request.args.get('month')
        year = request.args.get('year')
        
        if not month or not year:
            return jsonify({'error': 'Month and year parameters are required'}), 400
        
        try:
            month_int = int(month)
            year_int = int(year)
        except ValueError:
            return jsonify({'error': 'Invalid month or year format'}), 400
        
        from datetime import timedelta
        start_date = datetime(year_int, month_int, 1)
        if month_int == 12:
            end_date = datetime(year_int + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = datetime(year_int, month_int + 1, 1) - timedelta(days=1)
        end_date = datetime.combine(end_date.date(), datetime.max.time())
        
        utilization_category = mongo.db.categories.find_one({"code": "utilization_billable"})
        current_utilization = None
        
        if utilization_category:
            utilization_request = mongo.db.points_request.find_one({
                "user_id": ObjectId(user_id),
                "status": "Approved",
                "request_date": {"$gte": start_date, "$lte": end_date},
                "category_id": utilization_category["_id"]
            }, sort=[("request_date", -1)])
            
            if utilization_request and "utilization_value" in utilization_request:
                utilization_value = utilization_request.get("utilization_value")
                if utilization_value is not None:
                    current_utilization = {
                        "numeric_value": round(utilization_value * 100),
                        "date": start_date.strftime('%b %Y')
                    }
            else:
                utilization_point = mongo.db.points.find_one({
                    "user_id": ObjectId(user_id),
                    "award_date": {"$gte": start_date, "$lte": end_date},
                    "category_id": utilization_category["_id"]
                }, sort=[("award_date", -1)])
                
                if utilization_point and "utilization_value" in utilization_point:
                    utilization_value = utilization_point.get("utilization_value")
                    if utilization_value is not None:
                        current_utilization = {
                            "numeric_value": round(utilization_value * 100),
                            "date": start_date.strftime('%b %Y')
                        }
        
        if not current_utilization:
            current_utilization = {
                "numeric_value": 0,
                "date": start_date.strftime('%b %Y')
            }
        
        return jsonify({
            'current_utilization': current_utilization
        })
    
    except Exception as e:
        return jsonify({'error': 'Server error'}), 500