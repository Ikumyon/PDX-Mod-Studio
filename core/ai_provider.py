import json

class AIProvider:
    """AIモデルとの通信を担当する基底クラス"""
    def __init__(self, api_key=None):
        self.api_key = api_key

    def generate(self, prompt, system_instruction=None):
        """プロンプトを送信し、応答を返す（モック版）"""
        print(f"AI Prompt: {prompt}")
        
        # 実際にはここでAPIを叩く
        # モックとしてダミーの応答を返す
        return "これはAIからのダミー応答です。指示内容に基づいて提案を作成します。"

class StructuredAIProvider(AIProvider):
    """構造化データ（JSON）を返すAIプロバイダー"""
    def generate_json(self, prompt, system_instruction=None):
        raw_response = self.generate(prompt, system_instruction)
        # JSONをパースして返す
        try:
            # モック用のダミーJSON
            return {
                "title": "AI提案項目",
                "description": "AIによって生成された説明文です。",
                "data": {
                    "name": "生成された名前",
                    "desc": "生成された説明文の詳細です。"
                }
            }
        except:
            return None
