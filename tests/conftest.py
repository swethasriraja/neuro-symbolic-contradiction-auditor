"""
Global test configuration.
Ensures DISABLE_SQLALCHEMY_CEXT=1 is set before SQLAlchemy or Pydantic imports.
"""
import os
os.environ["DISABLE_SQLALCHEMY_CEXT"] = "1"
