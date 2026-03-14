import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional


class UserManager:

    def __init__(self, db_file="users.json"):
        self.db_file = db_file
        self.users = self.load_users()

        # coloque aqui seu ID do telegram depois
        self.admin_ids = [123456789, 2081890738]

        # limite diário padrão para usuários free
        self.free_daily_limit = 1


    # =========================
    # FILE
    # =========================

    def load_users(self) -> Dict:
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, "r") as f:
                    return json.load(f)
            except:
                return {}

        return {}

    def save_users(self):

        try:
            with open(self.db_file, "w") as f:
                json.dump(self.users, f, indent=2, default=str)
        except Exception as e:
            print("Erro salvando users:", e)


    # =========================
    # USER BASIC
    # =========================

    def add_user(self, user_id: int, username=None, first_name=None):

        user_id_str = str(user_id)

        if user_id_str not in self.users:

            self.users[user_id_str] = {
                "id": user_id,
                "username": username,
                "first_name": first_name,
                "plan": "premium" if user_id in self.admin_ids else "free",
                "joined_date": datetime.now().isoformat(),
                "analysis_count_today": 0,
                "last_reset": datetime.now().date().isoformat(),
                "last_analysis": None,
            }

            self.save_users()

        return self.users[user_id_str]


    def get_user(self, user_id: int) -> Optional[Dict]:

        user_id_str = str(user_id)

        if user_id_str in self.users:
            return self.users[user_id_str]

        return None


    def get_or_create_user(self, user_id: int, username=None, first_name=None):

        user = self.get_user(user_id)

        if user is None:
            user = self.add_user(
                user_id,
                username=username,
                first_name=first_name
            )

        return user


    # =========================
    # PERMISSIONS
    # =========================

    def is_admin(self, user_id: int):

        return user_id in self.admin_ids


    def is_premium(self, user_id: int):

        user = self.get_user(user_id)

        if not user:
            return False

        return user.get("plan") == "premium"


    # =========================
    # ANALYSIS LIMIT
    # =========================

    def can_analyze(self, user_id: int):

        user = self.get_or_create_user(user_id)

        if user["plan"] == "premium":
            return True

        today = datetime.now().date().isoformat()

        if user["last_reset"] != today:

            user["analysis_count_today"] = 0
            user["last_reset"] = today

            self.save_users()

        return user["analysis_count_today"] < self.free_daily_limit


    def set_free_daily_limit(self, limit: int):
        if limit < 1:
            raise ValueError("Limit deve ser >= 1")

        self.free_daily_limit = int(limit)
        return self.free_daily_limit


    def get_free_daily_limit(self):
        return self.free_daily_limit


    def set_user_plan(self, user_id: int, plan: str):
        if plan not in ["free", "premium"]:
            raise ValueError("Plano inválido")

        user = self.get_or_create_user(user_id)
        user["plan"] = plan
        self.save_users()
        return user


    def record_analysis(self, user_id: int):

        user = self.get_or_create_user(user_id)

        user["last_analysis"] = datetime.now().isoformat()

        if user["plan"] != "premium":
            user["analysis_count_today"] += 1

        self.save_users()


    # =========================
    # PREMIUM
    # =========================

    def upgrade_to_premium(self, user_id: int):

        user = self.get_or_create_user(user_id)

        user["plan"] = "premium"

        self.save_users()

        return True


    # =========================
    # STATS
    # =========================

    def get_user_stats(self):

        total = len(self.users)

        free = sum(
            1 for u in self.users.values()
            if u["plan"] == "free"
        )

        premium = sum(
            1 for u in self.users.values()
            if u["plan"] == "premium"
        )

        return {
            "total_users": total,
            "free_users": free,
            "premium_users": premium,
        }


    def get_stats(self):

        stats = self.get_user_stats()

        analyses_today = sum(
            u.get("analysis_count_today", 0)
            for u in self.users.values()
        )

        stats["analyses_today"] = analyses_today
        stats["total_analyses"] = analyses_today

        return stats


    # =========================
    # ADMIN
    # =========================

    def list_users(self, limit=50):

        result = []

        for u in list(self.users.values())[:limit]:

            result.append({
                "id": u["id"],
                "username": u["username"],
                "plan": u["plan"],
                "analyses_today": u["analysis_count_today"]
            })

        return result


    def get_all_user_ids(self):

        return [int(x) for x in self.users.keys()]