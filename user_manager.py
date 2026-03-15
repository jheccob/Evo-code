import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class UserManager:
    def __init__(self, db_file: Optional[str] = None):
        self.db_file = db_file or self._get_default_db_path()
        self.use_json_backend = self.db_file.lower().endswith(".json")
        self.free_daily_limit = 1

        if self.use_json_backend:
            self.users = self.load_users()
        else:
            self.users = {}
            self._init_sqlite_storage()
            self._migrate_legacy_json_if_needed()

        self.admin_ids = self._load_admin_ids()

    def _get_default_db_path(self) -> str:
        try:
            from config import AppConfig

            return AppConfig.DB_PATH
        except Exception:
            return "data/trading_bot.db"

    # =========================
    # STORAGE
    # =========================

    def _get_connection(self):
        os.makedirs(os.path.dirname(self.db_file) or ".", exist_ok=True)
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sqlite_storage(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                plan TEXT NOT NULL DEFAULT 'free',
                is_admin INTEGER NOT NULL DEFAULT 0,
                joined_date TEXT NOT NULL,
                analysis_count_today INTEGER NOT NULL DEFAULT 0,
                last_reset TEXT NOT NULL,
                last_analysis TEXT
            )
            """
        )
        conn.commit()
        conn.close()

    def _count_sqlite_users(self) -> int:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS total FROM telegram_users")
        total = int(cursor.fetchone()["total"])
        conn.close()
        return total

    def _migrate_legacy_json_if_needed(self):
        legacy_file = "users.json"
        if self.use_json_backend:
            return

        if os.path.abspath(self.db_file) != os.path.abspath(self._get_default_db_path()):
            return

        if not os.path.exists(legacy_file) or self._count_sqlite_users() > 0:
            return

        try:
            with open(legacy_file, "r", encoding="utf-8") as file_handle:
                legacy_users = json.load(file_handle)
        except Exception as exc:
            logger.warning("Falha ao ler users.json legado para migracao: %s", exc)
            return

        migrated = 0
        for raw_user in legacy_users.values():
            user = self._normalize_user(raw_user)
            self._save_user_sqlite(user)
            migrated += 1

        if migrated:
            logger.info("Migrados %s usuarios de users.json para %s", migrated, self.db_file)

    def _normalize_user(self, user: Dict) -> Dict:
        today = datetime.now().date().isoformat()
        user_id = int(user["id"])
        return {
            "id": user_id,
            "username": user.get("username"),
            "first_name": user.get("first_name"),
            "plan": "premium" if user.get("plan") == "premium" else "free",
            "is_admin": bool(user.get("is_admin", False)),
            "joined_date": user.get("joined_date") or datetime.now().isoformat(),
            "analysis_count_today": int(user.get("analysis_count_today", 0) or 0),
            "last_reset": user.get("last_reset") or today,
            "last_analysis": user.get("last_analysis"),
        }

    def _row_to_user(self, row: sqlite3.Row) -> Dict:
        return {
            "id": int(row["telegram_id"]),
            "username": row["username"],
            "first_name": row["first_name"],
            "plan": row["plan"],
            "is_admin": bool(row["is_admin"]),
            "joined_date": row["joined_date"],
            "analysis_count_today": int(row["analysis_count_today"] or 0),
            "last_reset": row["last_reset"],
            "last_analysis": row["last_analysis"],
        }

    def _fetch_user_sqlite(self, user_id: int) -> Optional[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT telegram_id, username, first_name, plan, is_admin, joined_date,
                   analysis_count_today, last_reset, last_analysis
            FROM telegram_users
            WHERE telegram_id = ?
            """,
            (int(user_id),),
        )
        row = cursor.fetchone()
        conn.close()
        return self._row_to_user(row) if row else None

    def _save_user_sqlite(self, user: Dict):
        normalized = self._normalize_user(user)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO telegram_users (
                telegram_id, username, first_name, plan, is_admin, joined_date,
                analysis_count_today, last_reset, last_analysis
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                plan = excluded.plan,
                is_admin = excluded.is_admin,
                joined_date = excluded.joined_date,
                analysis_count_today = excluded.analysis_count_today,
                last_reset = excluded.last_reset,
                last_analysis = excluded.last_analysis
            """,
            (
                normalized["id"],
                normalized["username"],
                normalized["first_name"],
                normalized["plan"],
                int(normalized["is_admin"]),
                normalized["joined_date"],
                normalized["analysis_count_today"],
                normalized["last_reset"],
                normalized["last_analysis"],
            ),
        )
        conn.commit()
        conn.close()

    def _load_all_users(self) -> Dict[str, Dict]:
        if self.use_json_backend:
            return dict(self.users)

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT telegram_id, username, first_name, plan, is_admin, joined_date,
                   analysis_count_today, last_reset, last_analysis
            FROM telegram_users
            ORDER BY joined_date ASC
            """
        )
        rows = cursor.fetchall()
        conn.close()
        return {str(row["telegram_id"]): self._row_to_user(row) for row in rows}

    # =========================
    # FILE
    # =========================

    def load_users(self) -> Dict:
        if not self.use_json_backend:
            return {}

        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, "r", encoding="utf-8") as file_handle:
                    return json.load(file_handle)
            except Exception as exc:
                logger.warning("Falha ao carregar users JSON: %s", exc)
                return {}

        return {}

    def save_users(self):
        if not self.use_json_backend:
            return

        try:
            with open(self.db_file, "w", encoding="utf-8") as file_handle:
                json.dump(self.users, file_handle, indent=2, default=str)
        except Exception as exc:
            logger.error("Erro salvando users: %s", exc)

    def _load_admin_ids(self) -> List[int]:
        admin_ids = {123456789, 2081890738}

        try:
            from config import ProductionConfig

            admin_ids.update(ProductionConfig.ADMIN_USERS)
        except Exception:
            pass

        for user in self._load_all_users().values():
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
        user = self.get_user(user_id)
        if user is not None:
            return user

        user = {
            "id": int(user_id),
            "username": username,
            "first_name": first_name,
            "plan": "premium" if user_id in self.admin_ids else "free",
            "is_admin": user_id in self.admin_ids,
            "joined_date": datetime.now().isoformat(),
            "analysis_count_today": 0,
            "last_reset": datetime.now().date().isoformat(),
            "last_analysis": None,
        }

        if self.use_json_backend:
            self.users[str(user_id)] = user
            self.save_users()
        else:
            self._save_user_sqlite(user)

        return user

    def get_user(self, user_id: int) -> Optional[Dict]:
        if self.use_json_backend:
            return self.users.get(str(user_id))
        return self._fetch_user_sqlite(user_id)

    def get_or_create_user(self, user_id: int, username=None, first_name=None):
        user = self.get_user(user_id)
        if user is None:
            return self.add_user(user_id, username=username, first_name=first_name)

        updated = False
        if username and user.get("username") != username:
            user["username"] = username
            updated = True
        if first_name and user.get("first_name") != first_name:
            user["first_name"] = first_name
            updated = True

        if updated:
            if self.use_json_backend:
                self.users[str(user_id)] = user
                self.save_users()
            else:
                self._save_user_sqlite(user)

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

    def _persist_user(self, user: Dict):
        if self.use_json_backend:
            self.users[str(user["id"])] = user
            self.save_users()
        else:
            self._save_user_sqlite(user)

    def can_analyze(self, user_id: int):
        user = self.get_or_create_user(user_id)
        if user["plan"] == "premium":
            return True

        today = datetime.now().date().isoformat()
        if user["last_reset"] != today:
            user["analysis_count_today"] = 0
            user["last_reset"] = today
            self._persist_user(user)

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
            raise ValueError("Plano invalido")

        user = self.get_or_create_user(user_id)
        user["plan"] = plan
        self._persist_user(user)
        return user

    def record_analysis(self, user_id: int):
        user = self.get_or_create_user(user_id)
        user["last_analysis"] = datetime.now().isoformat()

        if user["plan"] != "premium":
            user["analysis_count_today"] += 1

        self._persist_user(user)

    # =========================
    # PREMIUM
    # =========================

    def upgrade_to_premium(self, user_id: int):
        user = self.get_or_create_user(user_id)
        user["plan"] = "premium"
        self._persist_user(user)
        return True

    # =========================
    # STATS
    # =========================

    def get_user_stats(self):
        users = self._load_all_users()
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

        total = len(users)
        free = sum(1 for user in users.values() if user["plan"] == "free")
        premium = sum(1 for user in users.values() if user["plan"] == "premium")
        active_today = sum(1 for user in users.values() if _is_active_today(user))

        return {
            "total_users": total,
            "free_users": free,
            "premium_users": premium,
            "active_today": active_today,
        }

    def get_stats(self):
        users = self._load_all_users()
        stats = self.get_user_stats()
        analyses_today = sum(user.get("analysis_count_today", 0) for user in users.values())
        stats["analyses_today"] = analyses_today
        stats["total_analyses"] = analyses_today
        return stats

    # =========================
    # ADMIN
    # =========================

    def list_users(self, limit=50):
        result = []
        for user in list(self._load_all_users().values())[:limit]:
            result.append(
                {
                    "id": user["id"],
                    "username": user["username"],
                    "plan": user["plan"],
                    "analyses_today": user["analysis_count_today"],
                    "is_admin": user.get("is_admin", False),
                    "last_analysis": user.get("last_analysis"),
                }
            )

        return result

    def add_admin(self, user_id: int):
        user = self.get_or_create_user(user_id)
        user["is_admin"] = True
        user["plan"] = "premium"

        if user_id not in self.admin_ids:
            self.admin_ids.append(user_id)
            self.admin_ids.sort()

        self._persist_user(user)
        return True

    def get_all_user_ids(self):
        return [int(user_id) for user_id in self._load_all_users().keys()]
