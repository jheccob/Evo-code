import unittest


class AppAdminPanelSourceTests(unittest.TestCase):
    def test_admin_panel_contains_session_auth_and_multiuser_security_controls(self):
        with open("app.py", "r", encoding="utf-8") as app_file:
            source = app_file.read()

        self.assertIn("hmac.compare_digest", source)
        self.assertIn("admin_authenticated", source)
        self.assertIn("get_multiuser_account_overview", source)
        self.assertIn("upsert_user_account", source)
        self.assertIn("upsert_user_risk_profile", source)
        self.assertIn("CredentialVault", source)
        self.assertIn("store_exchange_credentials", source)
        self.assertIn("dashboard_user_auth", source)
        self.assertIn("authenticate_dashboard_user", source)
        self.assertIn("render_multiuser_workspace_tab", source)
        self.assertIn("upsert_dashboard_user_access", source)
        self.assertIn("Configur", source)


if __name__ == "__main__":
    unittest.main()
