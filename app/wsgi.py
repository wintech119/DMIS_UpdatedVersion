from app import require_flask_runtime_rollback_only

require_flask_runtime_rollback_only("app.wsgi")

import app.main as main

flask_app = main.app
