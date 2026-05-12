# PDX-Mod-Studio Core API Reference Guide

プラグインから本体側の機能へアクセスするための `core.api` リファレンスです。

```python
import core.api
```

## プロジェクト

#### `core.api.get_project_path() -> str | None`

現在開いているMOD/プロジェクトフォルダの絶対パスを返します。

戻り値:

- `str`: プロジェクトが開かれている場合
- `None`: 未オープンの場合

#### `core.api.register_project_path_handler(handler)`

プロジェクトパス変更時に呼ばれるハンドラを登録します。

ハンドラ形式:

```python
def handler(path: str):
    ...
```

## UI

#### `core.api.show_message(text: str, timeout: int = 3000)`

ステータスバーに一時メッセージを表示します。

#### `core.api.set_progress(value: int, text: str = "")`

進捗表示を更新します。

- `value`: `0` から `100`
- `text`: 進捗バー横の表示テキスト

## タブ

#### `core.api.get_open_tabs() -> list[dict]`

現在開いているタブ情報を返します。

主なキー:

- `index`
- `name`
- `path`
- `widget`
- `is_dirty`

#### `core.api.open_tab(file_path: str)`

指定ファイルをタブで開きます。既に開いている場合はそのタブへ切り替えます。

## モード

#### `core.api.get_element_for_file(file_path: str)`

指定ファイルに対応するプラグイン要素を返します。

戻り値は `ModElement` または `None` です。

#### `core.api.get_modes_for_file(file_path: str, include_script: bool = True) -> list[dict]`

指定ファイルで利用できるモード一覧を返します。

戻り値例:

```python
[
    {"id": "events:event_file:form", "name": "Event Editor"},
    {"id": "script_mode", "name": "スクリプトモード"},
]
```

#### `core.api.get_current_mode(file_path: str | None = None) -> str | None`

指定ファイル、または `file_path` 省略時は現在タブのモードIDを返します。

戻り値例:

```python
"events:event_file:form"
"script_mode"
```

#### `core.api.switch_mode(mode_id: str, file_path: str | None = None) -> bool`

指定ファイル、または `file_path` 省略時は現在タブを指定モードへ切り替えます。

戻り値:

- `True`: 切り替え成功、または既に指定モード
- `False`: 対象タブがない、または指定モードが利用不可

#### `core.api.refresh_modes(file_path: str | None = None) -> int`

開いているタブの利用可能モードを再評価します。

- `file_path` 指定あり: そのファイルのタブだけ再評価
- `file_path` 省略: 全タブを再評価

戻り値は再評価したタブ数です。

#### `core.api.register_mode_changed_handler(handler)`

モード変更時に呼ばれるハンドラを登録します。

ハンドラ形式:

```python
def handler(file_path: str, mode_id: str):
    ...
```

## プラグイン

#### `core.api.get_active_plugin()`

現在選択中のプラグインオブジェクトを返します。

戻り値は `Plugin` または `None` です。

## ローカライズ更新通知

#### `core.api.register_loc_changed_handler(handler)`

ローカライズレジストリ更新時に呼ばれるハンドラを登録します。

ハンドラ形式:

```python
def handler():
    ...
```

## 内部向け登録API

以下は主に本体側が利用する登録口です。通常のプラグイン実装では直接呼ぶ必要はありません。

- `core.api.register_tabs_handler(handler_dict)`
- `core.api.register_mode_handler(handler_dict)`
- `core.api.register_active_plugin_handler(handler)`
- `core.api.register_message_handler(handler)`
- `core.api.register_progress_handler(handler)`
- `core.api.notify_loc_changed()`
- `core.api.notify_mode_changed(file_path, mode_id)`

## 使用例

### 現在ファイルのモード一覧を取得する

```python
import core.api

tabs = core.api.get_open_tabs()
if tabs:
    file_path = tabs[0]["path"]
    modes = core.api.get_modes_for_file(file_path)
    core.api.show_message(str(modes))
```

### 現在タブをスクリプトモードへ切り替える

```python
import core.api

ok = core.api.switch_mode("script_mode")
if ok:
    core.api.show_message("スクリプトモードへ切り替えました")
```

### モード変更を監視する

```python
import core.api

def on_mode_changed(file_path, mode_id):
    print(f"{file_path}: {mode_id}")

core.api.register_mode_changed_handler(on_mode_changed)
```
