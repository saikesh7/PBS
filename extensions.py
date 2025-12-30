# extensions.py
from flask_pymongo import PyMongo
from flask_mail import Mail
from flask_bcrypt import Bcrypt

# Create instances of all extensions
mongo = PyMongo()
mail = Mail()
bcrypt = Bcrypt()