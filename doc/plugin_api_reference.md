# プラグイン API リファレンス

`core.api` モジュールは、プラグインがアプリケーション本体の機能へアクセスするための主要なインターフェースです。

## メッセージ表示

### `show_message(text: str, timeout: int = 3000)`

ステータスバーにメッセージを表示します。

- `text`: 表示する文字列
- `timeout`: メッセージを表示する時間。ミリ秒単位

## 進捗表示

### `set_progress(value: int, text: str = "")`

ステータスバーに進捗を表示します。

- `value`: `0` から `100`。`0` 未満または `100` 以上を指定すると非表示
- `text`: 進捗バーに表示するラベル

## タブ操作

### `open_tab(file_path: str, editor_id: str = None, params: dict = None)`

指定したファイルをタブで開きます。

既に同じ `file_path` と `editor_id` の組み合わせで開いている場合は、そのタブへ切り替えます。

- `params`: エディタに渡す任意のパラメータ（例：`{"target_id": "my_id"}`）。新しくタブを開く場合、エディタの初期化（`notify_editor_ready`）を待ってから適用されます。

### `open_untitled_tab(name: str, content: str = "", editor_id: str = "core.plain_text")`

メモリ上にだけ存在する新規タブを開きます。

未保存タブは `untitled:` から始まる仮想パスを持ちます。初回保存時に保存先が確定します。

## エディタ状態通知

### `notify_editor_ready(widget)`

カスタムエディタが自身の初期化（パースや重いUI構築など）を完了したことを本体に通知します。

この通知を送ることで、`open_tab` 時の `params` が安全に `set_params()` へ流し込まれるようになります。非同期で初期化を行うエディタでは必須の処理です。

## カスタムエディタタブ契約

これは `core.api` の関数ではなく、カスタムエディタ widget が本体に提供する契約です。

### `setup(widget, file_path, content)`

カスタムエディタのロジックファイルに定義する読み込み入口です。

本体は `file_path` と `content` を渡します。プラグイン固有の関連ファイルは、カスタムタブ側で読み込みます。

```python
def setup(widget, file_path, content):
    controller = MyEditorController(widget, file_path, content)
    widget.plugin_controller = controller
    controller.bind()
```

### `widget.on_save_triggered() -> bool | None`

保存可能なタブが提供する `Save` の入口です。

本体メニューバーの `File > Save` は、現在アクティブなタブの `on_save_triggered()` を呼びます。

`on_save_triggered()` は `widget` 直下に定義しても、`widget.plugin_controller` に定義しても構いません。

戻り値:

- `True`: 保存計画の作成に成功
- `False`: 保存失敗またはキャンセル
- `None`: 非推奨。`True` / `False` を返してください

### `widget.on_save_as_triggered() -> bool | None`

保存可能なタブが提供する `Save As` の入口です。

本体メニューバーの `File > Save As` は、このメソッドが存在する場合に呼びます。

戻り値:

- `True`: 保存計画の作成に成功
- `False`: 保存失敗またはキャンセル

### `widget.save_plan`

保存計画ベースの保存に対応するタブが保持する状態です。

本体は `on_save_triggered()` または `on_save_as_triggered()` が `True` を返したあと、`widget.save_plan` を参照して書き込み段階へ進みます。

本体は `save_plan` の内部構造を詳細には解釈しませんが、少なくとも次の情報を含む想定です。

- `tab_kind`
- `dialog`
- `save_as`
- `targets`

`targets` は保存対象ごとの情報を持つ配列で、各要素は少なくとも次を持つ想定です。

- `role`
- `path`
- `format`

### `widget.on_write_save_plan() -> bool`

保存計画に従って実ファイルを書き込む入口です。

本体は `save_plan` が確定したあと、このメソッドを呼びます。書き込み内容、書き込み順序、複数ファイル間の整合性はタブまたはプラグイン側の責務です。

戻り値:

- `True`: 書き込み成功
- `False`: 書き込み失敗またはキャンセル

### 保存対応タブの実装例

```python
def setup(widget, file_path, content):
    controller = MyEditorController(widget, file_path, content)
    widget.plugin_controller = controller
    widget.on_save_triggered = controller.on_save_triggered
    widget.on_save_as_triggered = controller.on_save_as_triggered
    widget.on_write_save_plan = controller.on_write_save_plan
    controller.bind()

class MyEditorController:
    def on_save_triggered(self):
        self.widget.save_plan = {
            "tab_kind": "example",
            "dialog": None,
            "save_as": False,
            "targets": [
                {"role": "primary", "path": self.file_path, "format": "text"},
            ],
        }
        return True

    def on_save_as_triggered(self):
        # 保存ダイアログ等で save_plan を組み立てる
        return self.on_save_triggered()

    def on_write_save_plan(self):
        # save_plan に従って書き込む
        return True
```

### `widget.set_params(params: dict)`

外部（ナビゲーション等）から送られたパラメータを処理するための入口です。

`open_tab` 時に渡された `params` は、エディタが `notify_editor_ready()` を呼んだ後にこのメソッドを通じて渡されます。特定の項目へのスクロールや強調表示などに利用します。

## プロジェクト保存フック

これは `core.api` の関数ではなく、必須プラグインが任意で提供するプロジェクト保存契約です。

### `export_project_data(plugin, context) -> dict`

プロジェクト保存時に呼ばれます。

戻り値は `plugin_data[plugin.id]` として保存されます。本体は戻り値の中身を解釈しません。

内包型 `.pdxpkg` では、戻り値のトップレベルキーが `plugin_data/<plugin_id>/<key>.json` として保存されます。

### `import_project_data(plugin, context, data) -> None`

プロジェクト読み込み時に呼ばれます。

`data` は保存時に `export_project_data()` が返した内容です。欠落や破損がある場合、プラグイン側で再構築してください。

`context` は以下のキーを持ちます。

- `project_file`
- `project_type`: `reference` または `embedded`
- `mod_root`
- `required_plugins`
- `metadata`

## プロジェクト情報

### `get_project_path() -> str`

現在開いているプロジェクトのルートパスを返します。

### `load_svg_icon(path: str, color_hex: str) -> QIcon`

SVG ファイル内の `currentColor` を指定色に置換して `QIcon` を返します。

プラグイン側で本体内部の `core.utils` を直接参照せず、`core.api` 経由で利用してください。

## イベント購読

### `register_loc_changed_handler(handler: callable)`

ローカライズデータが変更されたときに呼び出される関数を登録します。

### `register_file_saved_handler(handler: callable)`

ファイルが保存されたときに呼び出される関数を登録します。

- `handler(file_path: str)`: 保存されたファイルのパスを受け取ります

## アクティブプラグイン

### `get_active_plugin()`

現在選択されているプラグインオブジェクトを返します。
