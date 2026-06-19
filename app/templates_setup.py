from fastapi.templating import Jinja2Templates

from app.auth import current_user_sync

templates = Jinja2Templates(directory="app/templates")

templates.env.globals["current_user"] = current_user_sync
