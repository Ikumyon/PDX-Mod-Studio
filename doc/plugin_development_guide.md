# プラグイン開発ガイド

PDX Mod Studioの機能を拡張するためのプラグイン作成方法について説明します。

## プラグインの構造
各プラグインは `plugins/` ディレクトリ内の独自のフォルダに配置されます。

```
plugins/
  my_plugin/
    plugin_manifest.json  # 必須：プラグインの定義
    main.py               # 推奨：エントリーポイント
    icon.png              # 任意：アイコン
    editors/              # 任意：カスタムエディタ定義
      my_editor.ui
      my_editor.py
```

## `plugin_manifest.json`
プラグインのメタデータを記述します。

```json
{
    "id": "my.plugin.id",
    "name": "My Plugin",
    "version": "1.0.0",
    "entry_point": "main.py",
    "icon": "icon.png"
}
```

## エントリーポイント (`main.py`)
`initialize` 関数を定義する必要があります。この関数はプラグインのロード時に呼び出されます。

```python
import core.api

def initialize(plugin):
    print(f"{plugin.name} が初期化されました。")
    core.api.show_message("プラグインがロードされました")

def show_settings(plugin, parent, project_path):
    # 設定画面の表示ロジック（任意）
    pass
```

## カスタムエディタの作成
特定のファイル形式に対してカスタムUIを提供できます。マニフェストに `elements` を定義し、`.ui` ファイルとロジック `.py` ファイルを用意します。

### ロジックファイルの実装
ロジックファイルには `setup(widget, file_path, content)` 関数が必要です。

```python
def setup(widget, file_path, content):
    # widget は .ui からロードされた QWidget です
    # ここでシグナルの接続などを行います
    widget.myButton.clicked.connect(lambda: print("Clicked!"))
```
