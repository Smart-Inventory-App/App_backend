"""
tRPC Procedures are defined here
Each procedure maps to a frontend query or mutation
"""
import inspect
from typing import get_type_hints
from app.routers import auth


class Router:
    """Simple router to hold procedures"""
    
    def __init__(self):
        self.auth_procedures = {
            'register': auth.register,
            'login': auth.login,
            'me': auth.me,
        }


router = Router()


class AppRouter:
    """Main app router - exported for frontend type-safety"""
    
    @staticmethod
    def get_procedures():
        """Get all procedures for type generation"""
        return {
            'auth': {
                'register': auth.register,
                'login': auth.login,
                'me': auth.me,
            }
        }
