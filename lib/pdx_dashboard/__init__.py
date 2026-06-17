from core.dashboard_tab_host import renderer_registry
from lib.pdx_dashboard.renderer import DashboardTextRenderer

# レンダラーのインスタンス化と登録
renderer_registry.register_renderer("pdx_dashboard_text", DashboardTextRenderer())
