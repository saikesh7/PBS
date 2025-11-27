# extensions.py
from flask_pymongo import PyMongo
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail
from flask_bcrypt import Bcrypt


# Create instances of all extensions
mongo = PyMongo()
db = SQLAlchemy()  # Keep this for backward compatibility during transition
mail = Mail()
bcrypt = Bcrypt()