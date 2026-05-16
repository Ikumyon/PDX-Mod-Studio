# プラグイン開発ガイド

PDX Mod Studio の機能を拡張するためのプラグイン作成方法を説明します。

## プラグインの構成

各プラグインは `plugins/` ディレクトリ内に、独自のフォルダとして配置します。

```text
plugins/
  my_plugin/
    plugin_manifest.json
    main.py
    icon.png
    editors/
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

## エントリーポイント

`main.py` には `initialize(plugin)` を定義します。この関数はプラグインのロード時に呼ばれます。

```python
import core.api

def initialize(plugin):
    print(f"{plugin.name} initialized")
    core.api.show_message("Plugin loaded")

def show_settings(plugin, parent, project_path):
    pass
```

## カスタムエディタ

特定のファイル形式に対して、プラグイン独自のタブ UI を提供できます。

カスタムエディタは `.ui` ファイルとロジック用 `.py` ファイルで構成します。ロジックファイルには `setup(widget, file_path, content)` を定義します。

```python
def setup(widget, file_path, content):
    # widget は .ui からロードされた QWidget
    # file_path は本体から渡された入口ファイル
    # content は入口ファイルのテキスト内容
    widget.myButton.clicked.connect(lambda: print("Clicked"))
```

## タブ読み込み契約

本体はカスタムタブに対して、「このファイルを、このエディタで開く」という要求だけを行います。

本体が行うこと:

- `file_path` を読む
- エディタを選ぶ
- `setup(widget, file_path, content)` を呼ぶ

プラグイン側が行うこと:

- `file_path` を入口として必要なデータを解釈する
- 必要なら関連ファイルを追加で読み込む
- UI に状態を反映する

たとえばイベントエディタは、イベント定義ファイルを入口として、ローカライズファイルやプラグイン設定を自分で読み込めます。本体はそれらの関連ファイルを知りません。

```python
def setup(widget, file_path, content):
    controller = MyEditorController(widget, file_path, content)
    widget.plugin_controller = controller

    widget.content = content
    widget.toPlainText = lambda: widget.content
    widget.setPlainText = controller.set_content

    controller.bind()
```

## タブ保存契約

保存メニューは本体のメニューバーにあります。ただし、保存処理の実体はアクティブなタブが担当します。

カスタムタブを保存可能にする場合は、タブ widget または `widget.plugin_controller` に `on_save_triggered()` を用意します。

```python
class MyEditorController:
    def on_save_triggered(self):
        # 入口ファイル、関連ファイル、ローカライズなどを必要に応じて保存する
        self.save_main_file()
        self.save_related_files()

        self.widget.is_dirty = False
        return True
```

本体の `File > Save` は、現在アクティブなタブの `on_save_triggered()` を呼びます。本体は、カスタムタブの保存先や保存形式を判断しません。

戻り値の扱い:

- `True`: 保存成功
- `False`: 保存失敗またはキャンセル
- `None`: 例外が発生していなければ保存成功として扱う

`File > Save As` に対応したい場合は、任意で `on_save_as_triggered()` を実装します。

```python
class MyEditorController:
    def on_save_as_triggered(self):
        path = self.ask_save_path()
        if not path:
            return False

        self.save_to(path)
        self.widget.file_path = path
        self.widget.is_dirty = False
        return True
```

## Dirty 状態

タブは `widget.is_dirty` を使って未保存状態を表します。

カスタムタブが `widget.content` を更新すると、本体側の監視で dirty 状態になります。複雑な UI 状態を持つ場合は、プラグイン側で明示的に `widget.is_dirty = True` を設定しても構いません。

保存に成功したら、タブ側で `widget.is_dirty = False` にしてください。

## プロジェクト保存フック

本体は `.pdxproj` / `.pdxpkg` の共通構造を保存します。プラグイン固有データは、プラグインが以下のフックで提供します。

```python
def export_project_data(plugin, context):
    return {
        "localisation_registry": {}
    }

def import_project_data(plugin, context, data):
    pass
```

`context` には以下が含まれます。

- `project_file`
- `project_type`: `reference` または `embedded`
- `mod_root`
- `required_plugins`
- `metadata`

本体は `plugin_data/<plugin_id>/` の中身を解釈しません。保存時に `export_project_data()` の戻り値を保存し、読み込み時に `import_project_data()` へ戻します。

内包型 `.pdxpkg` では、戻り値のトップレベルキーが JSON ファイル名になります。

```text
plugin_data/
  hoi4/
    localisation_registry.json
```

HOI4 プラグインでは、翻訳 `.yml` そのものではなく、メモリ上の `LocalisationRegistry` を `localisation_registry` として保存します。
