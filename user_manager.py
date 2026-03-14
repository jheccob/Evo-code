import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class UserManager:

    def __init__(self, db_file="users.json"):
        self.db_file = db_file
        self.users = self.load_users()
        self.admin_ids = self._load_admin_ids()

        # limite diário padrão para usuários free
        self.free_daily_limit = 1


    # =========================
    # FILE
    # =========================

    def load_users(self) -> Dict:
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return {}

        return {}

    def save_users(self):

        try:
            with open(self.db_file, "w", encoding="utf-8") as f:
                json.dump(self.users, f, indent=2, default=str)
        except Exception as e:
            logger.error("Erro salvando users: %s", e)

    def _load_admin_ids(self) -> List[int]:
        admin_ids = {123456789, 2081890738}

        try:
            from config import ProductionConfig
            admin_ids.update(ProductionConfig.ADMIN_USERS)
        except Exception:
            pass

        for user in self.users.values():
            if user.get("is_admin"):
                try:
                    admin_ids.add(int(user["id"]))
                except (KeyError, TypeError, ValueError):
                    continue

        return sorted(admin_ids)


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
                "is_admin": user_id in self.admin_ids,
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
        user = self.get_user(user_id)
        return user_id in self.admin_ids or bool(user and user.get("is_admin"))


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
        today = datetime.now().date()

        def _is_active_today(user: Dict) -> bool:
            last_analysis = user.get("last_analysis")
            if last_analysis:
                try:
                    return datetime.fromisoformat(last_analysis).date() == today
                except ValueError:
                    pass

            if user.get("analysis_count_today", 0) > 0:
                return user.get("last_reset") == today.isoformat()

            return False

        total = len(self.users)

        free = sum(
            1 for u in self.users.values()
            if u["plan"] == "free"
        )

        premium = sum(
            1 for u in self.users.values()
            if u["plan"] == "premium"
        )

        active_today = sum(
            1 for u in self.users.values()
            if _is_active_today(u)
        )

        return {
            "total_users": total,
            "free_users": free,
            "premium_users": premium,
            "active_today": active_today,
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
                "analyses_today": u["analysis_count_today"],
                "is_admin": u.get("is_admin", False),
                "last_analysis": u.get("last_analysis")
            })

        return result

    def add_admin(self, user_id: int):
        user = self.get_or_create_user(user_id)
        user["is_admin"] = True
        user["plan"] = "premium"

        if user_id not in self.admin_ids:
            self.admin_ids.append(user_id)
            self.admin_ids.sort()

        self.save_users()
        return True


    def get_all_user_ids(self):

        return [int(x) for x in self.users.keys()]
