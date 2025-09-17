
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

class UserManager:
    def __init__(self, db_file="users.json"):
        self.db_file = db_file
        self.users = self.load_users()
        
        # Admin user IDs (configure with your Telegram ID)
        self.admin_ids = [123456789]  # Replace with actual admin Telegram IDs
    
    def load_users(self) -> Dict:
        """Load users from JSON file"""
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def save_users(self):
        """Save users to JSON file"""
        try:
            with open(self.db_file, 'w') as f:
                json.dump(self.users, f, indent=2, default=str)
        except Exception as e:
            print(f"Error saving users: {e}")
    
    def add_user(self, user_id: int, username: str = None, first_name: str = None):
        """Add new user to database"""
        user_id_str = str(user_id)
        if user_id_str not in self.users:
            self.users[user_id_str] = {
                'id': user_id,
                'username': username,
                'first_name': first_name,
                'plan': 'premium' if user_id in self.admin_ids else 'free',
                'joined_date': datetime.now().isoformat(),
                'last_analysis': None,
                'analysis_count_today': 0,
                'last_reset': datetime.now().date().isoformat()
            }
            self.save_users()
        return self.users[user_id_str]
    
    def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user data"""
        user_id_str = str(user_id)
        if user_id_str in self.users:
            return self.users[user_id_str]
        return None
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id in self.admin_ids
    
    def is_premium(self, user_id: int) -> bool:
        """Check if user is premium"""
        user = self.get_user(user_id)
        return user and user.get('plan') == 'premium'
    
    def can_analyze(self, user_id: int) -> bool:
        """Check if user can perform analysis (free: 1 per day, premium: unlimited)"""
        user = self.get_user(user_id)
        if not user:
            return False
        
        # Premium users have unlimited access
        if user.get('plan') == 'premium':
            return True
        
        # Check if it's a new day
        today = datetime.now().date().isoformat()
        if user.get('last_reset') != today:
            user['analysis_count_today'] = 0
            user['last_reset'] = today
            self.save_users()
        
        # Free users: 1 analysis per day
        return user.get('analysis_count_today', 0) < 1
    
    def record_analysis(self, user_id: int):
        """Record that user performed an analysis"""
        user = self.get_user(user_id)
        if user:
            user['last_analysis'] = datetime.now().isoformat()
            if user.get('plan') != 'premium':
                user['analysis_count_today'] = user.get('analysis_count_today', 0) + 1
            self.save_users()
    
    def upgrade_to_premium(self, user_id: int) -> bool:
        """Upgrade user to premium"""
        user = self.get_user(user_id)
        if user:
            user['plan'] = 'premium'
            self.save_users()
            return True
        return False
    
    def get_user_stats(self) -> Dict:
        """Get overall user statistics"""
        total_users = len(self.users)
        free_users = sum(1 for u in self.users.values() if u.get('plan') == 'free')
        premium_users = sum(1 for u in self.users.values() if u.get('plan') == 'premium')
        
        return {
            'total_users': total_users,
            'free_users': free_users,
            'premium_users': premium_users,
            'active_today': sum(1 for u in self.users.values() 
                              if u.get('last_reset') == datetime.now().date().isoformat())
        }
    
    def add_admin(self, user_id: int):
        """Add user as admin"""
        if user_id not in self.admin_ids:
            self.admin_ids.append(user_id)
        
        # Also upgrade to premium
        user = self.get_user(user_id)
        if user:
            user['plan'] = 'premium'
            self.save_users()
    
    def list_users(self, limit: int = 50) -> List[Dict]:
        """List users for admin panel"""
        users_list = []
        for user_data in list(self.users.values())[:limit]:
            users_list.append({
                'id': user_data.get('id'),
                'username': user_data.get('username', 'N/A'),
                'first_name': user_data.get('first_name', 'N/A'),
                'plan': user_data.get('plan'),
                'joined': user_data.get('joined_date'),
                'last_analysis': user_data.get('last_analysis'),
                'analyses_today': user_data.get('analysis_count_today', 0)
            })
        return users_list
