# プラグインAPIリファレンス

`core.api` モジュールは、プラグインがアプリケーション本体の機能にアクセスするための主要なインターフェースを提供します。

## メッセージ表示
ユーザーに通知を表示します。

### `show_message(text: str, timeout: int = 3000)`
ステータスバーにメッセージを表示します。
- `text`: 表示する文字列。
- `timeout`: メッセージが消えるまでの時間（ミリ秒）。

## 進捗管理
バックグラウンド処理などの進捗状況を表示します。

### `set_progress(value: int, text: str = "")`
ステータスバーにプログレスバーを表示します。
- `value`: 進捗率（0-100）。100を指定すると非表示になります。
- `text`: プログレスバーに併記するラベル。

## タブ操作
エディタタブの取得や操作を行います。

### `get_open_tabs() -> list`
現在開いているすべてのタブ情報のリストを返します。各要素は以下のキーを持つ辞書です：
- `index`, `name`, `path`, `is_dirty`, `editor_id`

### `open_tab(file_path: str, editor_id: str = None)`
指定したファイルを新しいタブで開きます。既に開いている場合はそのタブに切り替わります。

### `open_untitled_tab(name: str, content: str = "", editor_id: str = "core.plain_text")`
メモリ上にのみ存在する新規タブを開きます。

## プロジェクト情報
### `get_project_path() -> str`
現在開いているプロジェクトのルートパスを返します。

## イベント購読
アプリケーションのイベントを購読するための関数です。

### `register_loc_changed_handler(handler: callable)`
ローカライズデータが変更されたときに呼び出される関数を登録します。

### `register_file_saved_handler(handler: callable)`
ファイルが保存されたときに呼び出される関数を登録します。
- `handler(file_path: str)`: 保存されたファイルのパスを受け取ります。

## アクティブプラグイン
### `get_active_plugin()`
現在選択されているプラグインオブジェクトを返します。
