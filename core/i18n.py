import os
from PySide6.QtCore import QTranslator, QLocale, QCoreApplication, QObject

class I18nManager(QObject):
    """
    アプリケーションの国際化（i18n）を管理するクラス。
    QTranslator のロードと適用を担当します。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(I18nManager, cls).__new__(cls)
            cls._instance._initialized = False
            cls._instance.translator = QTranslator()
        return cls._instance

    def init_translation(self, app):
        """
        アプリケーションに翻訳を適用します。
        """
        if self._initialized:
            return

        # プロジェクトルートの localisation フォルダを探す
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        loc_dir = os.path.join(base_dir, "localisation")

        if not os.path.exists(loc_dir):
            # フォルダがなければ作成（初回用）
            try:
                os.makedirs(loc_dir, exist_ok=True)
            except Exception:
                pass

        # システムロケールに基づいて .qm ファイルをロード
        # ファイル名の形式例: pdx_mod_studio_ja_JP.qm
        if self.translator.load(QLocale.system(), "pdx_mod_studio", "_", loc_dir):
            app.installTranslator(self.translator)
            print(f"Loaded translation for {QLocale.system().name()}")
        else:
            print(f"No translation found for {QLocale.system().name()} in {loc_dir}")

        self._initialized = True

def tr(text, context="Generic"):
    """
    翻訳用のショートカット関数。
    """
    return QCoreApplication.translate(context, text)
