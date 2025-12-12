# Prowess Points Application

A comprehensive **Flask-based web application** for managing employee performance, points, awards, and multi-role dashboards. This enterprise-grade platform supports HR management, project tracking, employee analytics, and real-time notifications using WebSockets.

---

## 📋 Table of Contents

1. [About](#about)
2. [Features](#features)
3. [Tech Stack](#tech-stack)
4. [Project Structure](#project-structure)
5. [Folder Overview](#folder-overview)
6. [Requirements](#requirements)
7. [Installation](#installation)
8. [Configuration](#configuration)
9. [Running Locally](#running-locally)
10. [Database Setup](#database-setup)
11. [API Overview](#api-overview)
12. [Real-time Features](#real-time-features)
13. [Testing](#testing)
14. [Deployment](#deployment)
15. [Environment Variables](#environment-variables)
16. [Contributing](#contributing)
17. [License](#license)
18. [Contact](#contact)

---

## 📌 About

**Prowess Points Application** is an integrated employee performance and rewards management system. It enables organizations to:
- Track employee performance and achievements
- Manage points and awards distribution
- Generate analytics and reports
- Support multiple user roles with customized dashboards
- Enable real-time notifications and updates
- Manage employee raise requests and HR workflows

The platform is built for scalability and supports multiple teams, departments, and organizational hierarchies.

---

## ✨ Features

### Core Features
- **Multi-Role Dashboard System** – Customized views for PM, PMO, HR, TA, LD, Marketing, Presales, Central Admin
- **Points Management** – Award, validate, and track employee points
- **Employee Leaderboards** – Real-time ranking and performance metrics
- **Analytics & Reports** – Central analytics, bulk exports, category-wise insights
- **Email Notifications** – Automated alerts and updates via SMTP
- **Employee Management** – Registration, profile management, raise requests
- **Attachments** – Upload and manage file attachments
- **Real-time Updates** – WebSocket support for live notifications

### Advanced Features
- **Employee History Tracking** – Audit logs and change history
- **Raise Request Workflow** – Request, review, and approval process
- **Bonus Management** – Calculate and distribute bonuses
- **Batch Operations** – Bulk point updates and processing
- **OTP-Based Authentication** – Secure login via OTP
- **Session Management** – 365-day persistent sessions with "Remember Me"
- **Market Manager** – Role-based market and territory management

---

## 🛠️ Tech Stack

### Backend
| Component | Technology | Version |
|-----------|-----------|---------|
| **Framework** | Flask | 2.2.2 |
| **ORM/Database** | MongoDB + PyMongo | 3.12.1 |
| **Authentication** | Flask-Bcrypt | 1.0.1 |
| **Email** | Flask-Mail | 0.9.1 |
| **Real-time** | Flask-SocketIO + Eventlet | 5.3.6 + Latest |
| **CORS** | Flask-CORS | 3.1.1 |
| **Cache** | Redis | Latest |
| **Session Mgmt** | Flask Sessions | Built-in |

### Frontend
- **HTML/CSS/JavaScript** – Static templates
- **Bootstrap** – Responsive UI (if used)
- **WebSockets** – Real-time communication

### Utilities & Services
- **SMTP** – Outlook (pbs@prowesssoft.com)
- **File Upload** – Werkzeug (Secure uploads)
- **Database Migrations** – Alembic (if used)

### Development & Deployment
- **Task Queue** – Eventlet (async tasks)
- **Caching** – Redis service
- **Environment Config** – dotenv (recommended)

---

## 📁 Project Structure

```
project_root/
│
├── app.py                          # Main Flask application entry point
├── config.py                       # Configuration & environment settings
├── extensions.py                   # Flask extensions (Mongo, Mail, Bcrypt)
├── requirements.txt                # Python dependencies
├── dashboard_config.py             # Dashboard configuration
├── check_categories.py             # Category validation utilities
│
├── auth/                           # 🔐 Authentication Module
│   ├── routes.py                   # Login, registration, OTP, password reset
│   ├── templates/                  # Login & auth pages
│   └── static/                     # Auth-related assets
│
├── central/                        # 📊 Central Admin Dashboard
│   ├── central_routes.py           # Main central admin routes
│   ├── central_routes_optimized.py # Optimized queries with aggregation
│   ├── central_analytics.py        # Analytics & insights
│   ├── central_leaderboard.py      # Global leaderboard
│   ├── central_export.py           # Data export functionality
│   ├── central_bonus.py            # Bonus calculations
│   ├── central_batch_utils.py      # Batch operations
│   ├── central_config.py           # Central config settings
│   ├── central_email.py            # Email notifications
│   ├── central_utils.py            # Utility functions
│   ├── templates/                  # Central dashboard pages
│   └── static/                     # Central dashboard assets
│
├── employee/                       # 👤 Employee Module
│   ├── employee_dashboard.py       # Employee main dashboard
│   ├── employee_leaderboard.py     # Employee rankings
│   ├── employee_history.py         # Performance & transaction history
│   ├── employee_attachments.py     # File upload/download
│   ├── employee_filters.py         # Filter & search utilities
│   ├── employee_api.py             # Employee REST API endpoints
│   ├── employee_raise_request.py   # Raise request workflow
│   ├── employee_points_total.py    # Points summary & calculations
│   ├── templates/                  # Employee pages
│   └── static/                     # Employee assets
│
├── hr/                             # 👥 HR Module
│   ├── hr_main.py                  # HR dashboard main router
│   ├── hr_registration.py          # Employee registration
│   ├── hr_analytics.py             # HR analytics & reports
│   ├── hr_employee_management.py   # Employee profile management
│   ├── hr_points_management.py     # Points allocation & management
│   ├── hr_rr_review.py             # Raise request review workflow
│   ├── hr_categories.py            # Category management
│   ├── hr_email_service.py         # HR email notifications
│   ├── hr_updater_routes.py        # Update operations
│   ├── hr_validator_routes.py      # Validation operations
│   ├── hr_helpers.py               # Helper functions
│   ├── hr_utils.py                 # Utility functions
│   ├── pending_points_tracker.py   # Track pending point approvals
│   ├── templates/                  # HR pages
│   └── static/                     # HR assets
│
├── pm/                             # 📋 Project Manager Module
│   ├── pm_main.py                  # PM dashboard router
│   ├── pm_dashboard.py             # PM dashboard view
│   ├── pm_requests.py              # Point request handling
│   ├── pm_awards.py                # Award management
│   ├── pm_bulk.py                  # Bulk operations
│   ├── pm_employees.py             # Employee management for PM
│   ├── pm_attachments.py           # File attachments
│   ├── pm_api.py                   # PM API endpoints
│   ├── pm_helpers.py               # Helper functions
│   ├── pm_validators.py            # Validation logic
│   ├── pm_notifications.py         # PM notifications
│   ├── pm_pending_requests.py      # Track pending requests
│   ├── constants.py                # PM constants
│   ├── services/                   # PM-specific services
│   ├── templates/                  # PM pages
│   └── static/                     # PM assets
│
├── pmarch/                         # 🏛️ PM Architecture Module
│   ├── pmarch_main.py              # PMArch dashboard
│   ├── pmarch_dashboard.py         # Architecture dashboard
│   ├── pmarch_requests.py          # Request handling
│   ├── pmarch_api.py               # API endpoints
│   ├── pmarch_employees.py         # Employee data
│   ├── pmarch_attachments.py       # File management
│   ├── pmarch_helpers.py           # Utilities
│   ├── templates/                  # PMArch pages
│   └── static/                     # PMArch assets
│
├── pmo/                            # 📈 Portfolio Manager Office
│   ├── Similar structure to PM
│   ├── Dashboard & reporting
│   └── Portfolio-level operations
│
├── ta/                             # 🎯 Technical Architect Module
│   ├── Dashboard for TA role
│   └── TA-specific operations
│
├── ld/                             # 🏫 Leadership Development
│   ├── ld_main.py
│   ├── ld_helpers.py
│   ├── ld_email_service.py
│   ├── ld_updater_routes.py
│   ├── ld_validator_routes.py
│   └── Leadership-specific features
│
├── presales/                       # 💼 Presales Module
│   ├── Dashboard & order tracking
│   └── Presales-specific workflows
│
├── marketing/                      # 📢 Marketing Module
│   ├── marketing_dashboard.py      # Marketing analytics
│   ├── marketing_notifications.py  # Marketing alerts
│   ├── templates/                  # Marketing pages
│   └── static/                     # Marketing assets
│
├── dp/                             # 🎓 Development Program
│   ├── dp_dashboard.py             # Development program dashboard
│   ├── templates/                  # DP pages
│   └── static/                     # DP assets
│
├── manager/                        # 🛡️ Manager Utilities
│   ├── market_manager.py           # Market management
│   ├── pmarch.py                   # Architecture routing
│   ├── pmo_dashboard.py            # PMO specific
│   ├── ta_dashboard.py             # TA specific
│   ├── error_handling.py           # Error management
│   ├── dummy.py                    # Test/dummy routes
│   ├── utils/                      # Shared utilities
│   ├── templates/                  # Manager pages
│   └── static/                     # Manager assets
│
├── services/                       # 🔧 Shared Services
│   ├── redis_service.py            # Redis caching & sessions
│   ├── socketio_service.py         # WebSocket real-time events
│   ├── realtime_events.py          # Event broadcasting
│   └── __pycache__/
│
├── utils/                          # 🛠️ Global Utilities
│   ├── error_handling.py           # Error logging & handling
│   └── Common utilities
│
├── migrations/                     # 🗄️ Database Migrations
│   ├── alembic.ini                 # Alembic config
│   ├── env.py                      # Migration environment
│   └── versions/                   # Migration scripts
│
├── Uploads/                        # 📁 File Storage
│   └── User uploaded attachments
│
└── New folder/                     # 📦 Temporary/Archive
```

---

## 📂 Folder Overview

### **auth/** – Authentication Module 🔐
**Purpose:** Handles all user authentication and authorization.

**Key Files:**
- `routes.py` – Login, registration, OTP verification, password reset, email validation
- Uses Bcrypt for password hashing
- Supports OTP-based login with 10-minute expiry
- Validates email format and password strength
- Manages session with 365-day timeout for "Remember Me"

**Routes:**
- `POST /auth/login` – User login
- `POST /auth/register` – New user registration
- `POST /auth/verify-otp` – OTP verification
- `POST /auth/reset-password` – Password reset

---

### **central/** – Central Admin Dashboard 📊
**Purpose:** Global administration and analytics for entire organization.

**Key Files:**
- `central_routes.py` – Main admin dashboard routes
- `central_routes_optimized.py` – **Optimized queries using MongoDB aggregation pipeline** for performance
- `central_analytics.py` – Organization-wide analytics and insights
- `central_leaderboard.py` – Global employee rankings
- `central_export.py` – Data export (CSV, Excel)
- `central_bonus.py` – Bonus calculation and distribution
- `central_batch_utils.py` – Bulk operations (point updates, status changes)
- `central_email.py` – Mass email notifications
- `central_utils.py` – Shared utility functions
- `central_config.py` – Central settings

**Features:**
- Real-time statistics and KPIs
- Bulk point allocation
- Export employee data
- Bonus management
- Global leaderboard rankings
- Email campaigns
- Category management

---

### **employee/** – Employee Portal 👤
**Purpose:** Self-service platform for employees to view performance and request raises.

**Key Files:**
- `employee_dashboard.py` – Main dashboard (1300+ lines) with comprehensive analytics
- `employee_leaderboard.py` – Personal and team rankings
- `employee_history.py` – Transaction and approval history
- `employee_attachments.py` – File upload/download
- `employee_filters.py` – Search and filter utilities
- `employee_api.py` – REST API for frontend
- `employee_raise_request.py` – Raise request submission workflow
- `employee_points_total.py` – Points summary calculations

**Features:**
- Performance dashboard
- Points breakdown and history
- Leaderboard rankings
- Raise request submission
- File attachment uploads
- Real-time notifications

---

### **hr/** – Human Resources Module 👥
**Purpose:** HR team operations for employee management, registration, and approval workflows.

**Key Files:**
- `hr_main.py` – Main HR dashboard router
- `hr_registration.py` – Employee registration process
- `hr_analytics.py` – HR-level analytics and reporting
- `hr_employee_management.py` – Employee profile updates
- `hr_points_management.py` – Point allocation and corrections
- `hr_rr_review.py` – Raise request review and approval
- `hr_categories.py` – Category and role management
- `hr_updater_routes.py` – Update operations
- `hr_validator_routes.py` – Validation workflows
- `hr_helpers.py` – Helper utilities
- `pending_points_tracker.py` – Track pending point approvals

**Features:**
- Employee registration & onboarding
- Bulk employee uploads
- Points allocation
- Raise request approvals
- Employee profile management
- Category management
- Analytics & reporting

---

### **pm/** – Project Manager Module 📋
**Purpose:** Project-level point management and request handling.

**Key Files:**
- `pm_main.py` – PM dashboard router
- `pm_dashboard.py` – PM dashboard view
- `pm_requests.py` – Handle point requests from employees
- `pm_awards.py` – Award employees for achievements
- `pm_bulk.py` – Bulk operations (approve multiple requests)
- `pm_employees.py` – Manage team employees
- `pm_attachments.py` – File attachments
- `pm_api.py` – REST API endpoints
- `pm_helpers.py` – Utility functions
- `pm_validators.py` – Validation logic
- `pm_notifications.py` – PM-level notifications
- `pm_pending_requests.py` – Track pending requests

**Features:**
- Manage team members
- Award points for achievements
- Review and approve raise requests
- Bulk point allocation
- Team analytics
- Employee performance tracking

---

### **pmarch/** – PM Architecture Module 🏛️
**Purpose:** Architecture-level project management (senior PM role).

**Key Files:**
- `pmarch_main.py` – Architecture dashboard
- `pmarch_dashboard.py` – Architecture-specific views
- `pmarch_requests.py` – Request handling
- `pmarch_api.py` – API endpoints
- `pmarch_helpers.py` – Utilities
- `pmarch_employees.py` – Employee management
- `pmarch_attachments.py` – File management

**Features:**
- Architecture-level project oversight
- Portfolio management
- Strategic planning dashboard
- Cross-project analytics

---

### **pmo/** – Portfolio Manager Office 📈
**Purpose:** Portfolio-level management and reporting.

**Features:**
- Portfolio analytics
- Multi-project tracking
- Resource allocation
- Strategic reporting

---

### **ta/** – Technical Architect Role 🎯
**Purpose:** Technical architecture oversight and validation.

**Features:**
- Technical validation
- Architecture approval workflows
- Technical metrics and analytics

---

### **ld/** – Leadership Development 🏫
**Purpose:** Leadership development programs and tracking.

**Key Files:**
- `ld_main.py` – LD dashboard
- `ld_helpers.py` – Utilities
- `ld_email_service.py` – Notifications
- `ld_updater_routes.py` – Updates
- `ld_validator_routes.py` – Validations

**Features:**
- Development program tracking
- Leadership assessments
- Training management

---

### **presales/** – Presales Module 💼
**Purpose:** Presales operations and order management.

**Features:**
- Order pipeline tracking
- Presales team management
- Deal management

---

### **marketing/** – Marketing Module 📢
**Purpose:** Marketing team dashboards and campaign management.

**Key Files:**
- `marketing_dashboard.py` – Marketing analytics
- `marketing_notifications.py` – Campaign notifications

**Features:**
- Campaign tracking
- Marketing analytics
- Team performance
- Notification management

---

### **dp/** – Development Program 🎓
**Purpose:** Employee development program tracking.

**Key Files:**
- `dp_dashboard.py` – Development program dashboard

**Features:**
- Training and development
- Skill assessments
- Program tracking

---

### **manager/** – Manager Utilities 🛡️
**Purpose:** Shared manager utilities and market management.

**Key Files:**
- `market_manager.py` – Market and territory management
- `pmarch.py` – Architecture routing
- `pmo_dashboard.py` – PMO-specific views
- `ta_dashboard.py` – TA-specific views
- `error_handling.py` – Global error handling
- `utils/` – Shared utilities

**Features:**
- Market management
- Territory allocation
- Role-based routing
- Error handling

---

### **services/** – Shared Services 🔧
**Purpose:** Core services for real-time updates and caching.

**Key Files:**
- `redis_service.py` – Redis integration for caching and sessions
- `socketio_service.py` – WebSocket real-time event service
- `realtime_events.py` – Event broadcasting

**Features:**
- Real-time notifications via WebSocket
- Session caching with Redis
- Event broadcasting to connected clients
- Live updates on dashboards

---

### **utils/** – Global Utilities 🛠️
**Purpose:** Application-wide utilities and helpers.

**Key Files:**
- `error_handling.py` – Centralized error logging and handling

---

### **migrations/** – Database Migrations 🗄️
**Purpose:** Database schema version control using Alembic.

**Key Files:**
- `alembic.ini` – Migration configuration
- `env.py` – Migration environment setup
- `versions/` – Migration scripts

---

### **Uploads/** – File Storage 📁
**Purpose:** Directory for user-uploaded attachments.

---

## 📦 Requirements

### System Requirements
- **Python** ≥ 3.8
- **MongoDB** ≥ 4.0
- **Redis** (optional, for caching and sessions)
- **Git**

### Python Packages
All dependencies are listed in `requirements.txt`:

```
Flask==2.2.2                    # Web framework
Flask-Mail==0.9.1              # Email functionality
Flask-PyMongo==2.3.0           # MongoDB integration
Flask-Bcrypt==1.0.1            # Password hashing
flask-cors==3.1.1              # CORS support
pymongo==3.12.1                # MongoDB driver
Flask-SocketIO==5.3.6          # WebSocket support
python-socketio==5.8.0         # Socket.IO client
eventlet                        # Async worker (REQUIRED for SocketIO)
redis                           # Caching and sessions
```

---

## 🚀 Installation

### 1. Clone the Repository
```bash
git clone https://github.com/your-org/prowess-points-application.git
cd prowess-points-application
```

### 2. Create Virtual Environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure MongoDB
Ensure MongoDB is running:
```bash
# Windows
mongod.exe

# macOS/Linux
mongod
```

Or use MongoDB Atlas (cloud):
```bash
# Update MONGO_URI in config.py
MONGO_URI = 'mongodb+srv://user:password@cluster.mongodb.net/database'
```

### 5. (Optional) Setup Redis
```bash
# Windows - using WSL or Docker
docker run -d -p 6379:6379 redis:latest

# macOS
brew install redis
redis-server

# Linux
sudo apt-get install redis-server
redis-server
```

---

## ⚙️ Configuration

### Main Configuration File: `config.py`

```python
from datetime import timedelta

class Config:
    # Secret key for session management
    SECRET_KEY = 'prowess_points_application'
    
    # MongoDB connection
    MONGO_URI = 'mongodb://127.0.0.1:27017/prowess_points_application'
    # Or use MongoDB Atlas:
    # MONGO_URI = 'mongodb+srv://user:password@cluster.mongodb.net/database'
    
    # Email configuration (Outlook SMTP)
    MAIL_SERVER = 'smtp.outlook.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = 'your-email@outlook.com'
    MAIL_PASSWORD = 'your-app-password'
    
    # Session timeout (365 days)
    PERMANENT_SESSION_LIFETIME = timedelta(days=365)
```

### Create `.env` File (Recommended)
```bash
# Create .env file
touch .env
```

**`.env` contents:**
```
FLASK_ENV=development
FLASK_DEBUG=True
SECRET_KEY=prowess_points_application
MONGO_URI=mongodb://127.0.0.1:27017/prowess_points_application
MAIL_SERVER=smtp.outlook.com
MAIL_PORT=587
MAIL_USERNAME=your-email@outlook.com
MAIL_PASSWORD=your-app-password
REDIS_URL=redis://127.0.0.1:6379/0
SOCKETIO_MESSAGE_QUEUE=redis://127.0.0.1:6379/1
```

### Load Environment Variables
Update `config.py`:
```python
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'prowess_points_application')
    MONGO_URI = os.getenv('MONGO_URI', 'mongodb://127.0.0.1:27017/prowess_points_application')
    MAIL_SERVER = os.getenv('MAIL_SERVER', 'smtp.outlook.com')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USERNAME = os.getenv('MAIL_USERNAME')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
```

---

## ▶️ Running Locally

### Start the Application
```bash
python app.py
```

Or use Flask CLI:
```bash
flask run
```

The application will start at: **http://localhost:5000**

### With Custom Port
```bash
python app.py --port 8000
# Access at http://localhost:8000
```

### Development Mode (Hot Reload)
```bash
export FLASK_ENV=development
export FLASK_DEBUG=True
python app.py
```

### Access the Application
1. Open browser: **http://localhost:5000**
2. Redirect to login: **http://localhost:5000/auth/login**
3. Enter credentials to access dashboard

---

## 🗄️ Database Setup

### MongoDB Collections
The application uses the following MongoDB collections:

```
Database: prowess_points_application
├── users                 # User profiles & authentication
├── points                # Point transactions
├── categories            # Award categories
├── raise_requests        # Raise request records
├── awards                # Award records
├── leaderboard           # Leaderboard rankings
├── sessions              # Session data
├── attachments           # File attachment metadata
└── audit_logs            # Activity logs
```

### Create Indexes (Optional - for Performance)
```bash
# Connect to MongoDB and run:
db.users.createIndex({ "email": 1 })
db.points.createIndex({ "user_id": 1, "date": -1 })
db.points.createIndex({ "category": 1 })
db.raise_requests.createIndex({ "user_id": 1, "status": 1 })
```

---

## 🔌 API Overview

### Authentication Endpoints
```
POST   /auth/login                 # User login (OTP or password)
POST   /auth/register              # New user registration
POST   /auth/verify-otp            # OTP verification
POST   /auth/reset-password        # Password reset
GET    /auth/logout                # User logout
```

### Employee Endpoints
```
GET    /employee/dashboard         # Employee dashboard
GET    /employee/leaderboard       # Employee rankings
GET    /employee/history           # Transaction history
POST   /employee/raise-request     # Submit raise request
GET    /employee/points-summary    # Points breakdown
POST   /employee/attachments       # Upload files
```

### HR Endpoints
```
GET    /hr_roles/dashboard         # HR dashboard
POST   /hr_roles/register-employee # Register new employee
GET    /hr_roles/analytics         # HR analytics
POST   /hr_roles/points-allocation # Allocate points
GET    /hr_roles/pending-tracker   # Pending approvals
```

### PM Endpoints
```
GET    /pm/dashboard               # PM dashboard
POST   /pm/awards                  # Award employees
GET    /pm/requests                # View requests
POST   /pm/bulk-approve            # Bulk approval
```

### Central Admin Endpoints
```
GET    /central/dashboard          # Central admin dashboard
GET    /central/analytics          # Organization analytics
GET    /central/leaderboard        # Global leaderboard
POST   /central/export             # Export data
POST   /central/bonus              # Manage bonuses
```

---

## 🔄 Real-time Features

### WebSocket Events (SocketIO)

The application uses **Flask-SocketIO** with **Eventlet** for real-time updates.

**Events:**
```javascript
// Client Side
socket.emit('update_points', { user_id: 123, points: 50 });
socket.on('points_updated', (data) => { /* update UI */ });

socket.emit('new_award', { user_id: 123, category: 'performance' });
socket.on('award_received', (data) => { /* notify user */ });

socket.on('leaderboard_update', (data) => { /* refresh leaderboard */ });
```

**Server Side (`socketio_service.py`):**
```python
@socketio.on('update_points')
def handle_update_points(data):
    # Validate and update points
    socketio.emit('points_updated', {...}, broadcast=True)
```

### Redis Integration
- Caching user sessions
- Storing real-time event queues
- Broadcasting events across multiple workers

---

## 🧪 Testing

### Unit Tests (if available)
```bash
pytest tests/
pytest tests/ --cov=app
```

### Manual Testing
1. **Login**: Navigate to `/auth/login` and enter credentials
2. **Employee Dashboard**: View personal performance
3. **Point Awards**: Navigate to PM dashboard and award points
4. **Leaderboards**: Check real-time rankings
5. **Raise Requests**: Submit a raise request as employee
6. **HR Approvals**: Approve/reject as HR user

---

## 🐳 Docker Deployment

### Dockerfile Example
```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_APP=app.py
ENV FLASK_ENV=production

EXPOSE 5000

CMD ["python", "-m", "eventlet", "-m", "app"]
```

### Docker Compose Example
```yaml
version: '3.9'

services:
  app:
    build: .
    ports:
      - "5000:5000"
    environment:
      - MONGO_URI=mongodb://mongo:27017/prowess_points_application
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - mongo
      - redis
    volumes:
      - ./Uploads:/app/Uploads

  mongo:
    image: mongo:5.0
    ports:
      - "27017:27017"
    volumes:
      - mongo_data:/data/db

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  mongo_data:
```

### Run with Docker Compose
```bash
docker-compose up -d
docker-compose logs -f
docker-compose down
```

---

## 🌐 Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `FLASK_ENV` | Environment mode | `development` or `production` |
| `FLASK_DEBUG` | Enable debug mode | `True` or `False` |
| `SECRET_KEY` | Flask secret key | `prowess_points_application` |
| `MONGO_URI` | MongoDB connection | `mongodb://localhost:27017/dbname` |
| `MAIL_SERVER` | SMTP server | `smtp.outlook.com` |
| `MAIL_PORT` | SMTP port | `587` |
| `MAIL_USERNAME` | Email sender | `your-email@outlook.com` |
| `MAIL_PASSWORD` | Email password | `your-app-password` |
| `REDIS_URL` | Redis connection | `redis://localhost:6379/0` |
| `SOCKETIO_MESSAGE_QUEUE` | SocketIO queue | `redis://localhost:6379/1` |

---

## 📝 Contributing

### Branching Strategy
```bash
# Create feature branch
git checkout -b feature/your-feature-name

# Commit changes
git commit -m "feat: Add your feature"

# Push to remote
git push origin feature/your-feature-name

# Create Pull Request on GitHub
```

### Code Standards
- Follow PEP 8 for Python code
- Use meaningful variable names
- Add docstrings to functions
- Keep functions small and single-purpose
- Write comments for complex logic

### Testing Before Push
```bash
# Run linting
flake8 .

# Format code
black .

# Run tests
pytest
```

---

## 📜 License

This project is proprietary software owned by **Prowess Software**. 
All rights reserved. Unauthorized copying or distribution is prohibited.

---

## 📧 Contact

**Project Maintainers:**
- Email: pbs@prowesssoft.com
- Organization: Prowess Software

**Report Issues:**
- Create GitHub Issue with detailed description
- Include error logs and screenshots

**Support:**
- Email: support@prowesssoft.com
- Internal Wiki: [Company Wiki]

---

## 🙏 Acknowledgements

- **Flask & Python Community** – Web framework and ecosystem
- **MongoDB** – NoSQL database
- **Redis** – Caching and real-time support
- **Socket.IO** – Real-time communication
- **Eventlet** – Async worker support
- **Bootstrap** – Frontend framework (if used)

---

## 📌 Quick Reference

### Start Development Server
```bash
python app.py
```

### Access Application
```
http://localhost:5000
```

### View Logs
```bash
tail -f app.log
```

### Stop Server
```
Press Ctrl+C
```

### Reset Database
```bash
# WARNING: This will delete all data!
mongo prowess_points_application --eval "db.dropDatabase()"
```

---

**Last Updated:** December 12, 2025  
**Version:** 1.0.0  
**Status:** Production Ready ✅
