# 公開APIリファレンス

本書は、プラグインが本体へ要求を送るために使用できる公開APIを定義する。

本書に記載された API のみを、プラグインから依存可能な本体APIとして扱う。

## 基本方針

- 公開APIは `core.api` を通して提供する
- 本書にない `core.*` は本体内部実装であり、プラグインから依存しない
- 公開APIには、要求APIとイベント購読APIが含まれる

## API の種類

### 要求API

プラグインが本体へ何かを依頼するための入口。

例:

- `open_tab(...)`
- `show_message(...)`
- `set_progress(...)`

### イベント購読API

プラグインが本体の状態変化を購読するための入口。

例:

- `subscribe_event("project_path_changed", ...)`
- `subscribe_event("loc_changed", ...)`
- `subscribe_event("file_saved", ...)`

これらは「本体内部配線」ではなく、プラグインが依存してよい公開イベント購読APIとして扱う。

## プロジェクト

### `get_project_path() -> str`

現在開いているプロジェクトのルートパスを返す。

### `subscribe_event(event_name: str, handler: callable)`

イベントを購読する公開API。

- `event_name`
  例: `project_path_changed`, `loc_changed`, `file_saved`
- `handler`
  イベント発生時に呼ばれる関数

既存イベントの引数は次のとおり。

- `project_path_changed`
  `handler(path: str)`
- `loc_changed`
  `handler()`
- `file_saved`
  `handler(file_path: str)`

## メッセージ

### `show_message(text: str, timeout: int = 3000)`

ステータスバーにメッセージを表示する。

- `text`: 表示する文字列
- `timeout`: 表示時間（ミリ秒）

## 進捗

### `set_progress(value: int, text: str = "")`

進捗表示を更新する。

- `value`: `0` から `100`
- `text`: 進捗ラベル

## タブ

### `open_tab(file_path: str, editor_id: str = None, params: dict = None)`

指定したファイルをタブで開く。既に同じ `file_path` と `editor_id` の組み合わせで開いている場合はそのタブへ切り替える。

- `params`: エディタへ渡す任意パラメータ

### `open_untitled_tab(name: str, content: str = "", editor_id: str = "core.plain_text")`

メモリ上にだけ存在する未保存タブを開く。

### `get_active_tab() -> dict | None`

現在アクティブなタブ情報を返す。アクティブなタブがなければ `None` を返す。

戻り値の辞書は次のキーを持つ。

- `tab_id`
- `path`
- `editor_id`
- `is_dirty`
- `plugin_id`

### `get_tab_plugin_id(tab_id = None)`

指定した `tab_id` に属するプラグインIDを返す。`tab_id` を省略した場合は現在アクティブなタブを対象にする。

## エディタ状態

### `notify_editor_ready(tab_id)`

カスタムエディタが初期化完了を `tab_id` で本体へ通知する。

## イベント購読

### `emit_event(event_name: str, *args, **kwargs)`

イベントを発火する公開API。

通常は本体またはプラグイン内部処理から使う通知側である。

## プラグイン文脈

### `get_active_plugin_id()`

現在アクティブなプラグインIDを返す。

### `plugin_translate(plugin_id, key: str, fallback: str = None, language: str = None, context: str = None, metadata: dict = None) -> str`

プラグインの任意 i18n フックを通して文字列を解決する。

## 診断

### `register_diagnostics_provider(extension: str, provider_func)`

ファイル拡張子に対応する診断関数を登録する。

- `provider_func(file_path: str, content: str) -> list`

### `get_diagnostics(file_path: str, content: str) -> list`

指定ファイルの診断結果を取得する。

## 定数

### `BUILTIN_TEXT_EDITOR_ID`

本体標準テキストエディタの `editor_id`。現在は `core.plain_text`。

## 関連文書

- プラグイン全体方針: [plugin_model.md](./plugin_model.md)
- 公開フック: [plugin_hooks_reference.md](./plugin_hooks_reference.md)
- 保存結果仕様: [save_result_spec.md](./specs/save_result_spec.md)
- マニフェスト仕様: [plugin_manifest_spec.md](./specs/plugin_manifest_spec.md)
