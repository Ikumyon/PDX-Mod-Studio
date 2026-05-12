# PDX-Mod-Studio Core API Reference Guide

プラグインから本体（コアシステム）の機能にアクセスするための標準 API インフェースを提供します。

## 1. 導入方法
プラグイン内で `core.api` をインポートするだけで利用可能です。
※本体が .exe 化されている場合でも、自動的にインポートが解決されるようになっています。

```python
import core.api
```

---

## 2. API リファレンス

### 2.1. プロジェクト管理
#### `core.api.get_project_path() -> str | None`
現在開いている MOD フォルダの絶対パスを取得します。
- **戻り値**: フォルダの絶対パス（文字列）。プロジェクト未ロード時は `None`。

### 2.2. ユーザーインターフェース (UI)
#### `core.api.show_message(text: str, timeout: int = 3000)`
本体下部のステータスバーに一時的なメッセージを表示します。
- `text`: 表示するメッセージ。
- `timeout`: 表示時間（ミリ秒）。デフォルトは 3 秒。

#### `core.api.set_progress(value: int, text: str = "")`
ステータスバーにプログレスバーを表示し、進捗を更新します。
- `value`: 進捗率 (0〜100)。
    - `100` または `負の数` をセットすると、プログレスバーは自動的に非表示になります。
- `text`: 進捗バーの横に表示する補助テキスト。

### 2.3. タブ・エディタ操作
#### `core.api.get_open_tabs() -> list[dict]`
現在開いているすべてのエディタタブの情報を取得します。
- **戻り値**: 以下のキーを持つ辞書のリスト：
    - `index`: タブのインデックス
    - `name`: ファイル名
    - `path`: ファイルの絶対パス
    - `widget`: タブ内のウィジェットオブジェクト
    - `is_dirty`: 未保存の変更があるかどうか（`bool`）

#### `core.api.open_tab(file_path: str)`
指定したファイルを新しいタブで開きます。既に開かれている場合は、そのタブをアクティブにします。

---

## 3. 実践例

### スキャン処理中に進捗を出す
```python
import core.api

def scan_files(files):
    for i, f in enumerate(files):
        core.api.set_progress(int(i/len(files)*100), "スキャン中...")
        # 処理...
    core.api.set_progress(100)
    core.api.show_message("スキャン完了")
```
