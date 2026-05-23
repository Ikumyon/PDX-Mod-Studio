# カスタムタブ仕様

本書は、`gfx` エディタの実装を基準として、PDX Mod Studio におけるカスタムタブの公開仕様を定義する。

ここでいうカスタムタブとは、標準テキストエディタ (`core.plain_text`) ではなく、プラグイン定義の `form` / `logic` から生成されるエディタタブを指す。

## 1. 目的

- プラグインが独自 UI を持つ編集タブを本体上で開けるようにする
- 本体とプラグインの責務境界を明確にする
- `gfx` エディタ以外でも同一ライフサイクルを共有できるようにする

## 2. 登録条件

カスタムタブとして扱われるには、対象エレメントが次を満たすこと。

- `config.json` に `editor_id` がある
- `config.json` に `form` がある
- `config.json` に `logic` がある
- `form` と `logic` が実在する

本体はこれらを満たすエレメントを `EditorRegistry` に登録し、`editor_id` ごとのエディタ定義として扱う。

## 3. タブ生成

### 3.1 ファイルタブ

`core.api.open_tab(file_path, editor_id=None, params=None)` で開く。

- `file_path` と `editor_id` の組み合わせが既に開かれている場合は、その既存タブへ切り替える
- 既存タブへ切り替えた場合、`params` があり、かつ `widget.set_params` があれば即時適用する
- 新規タブ生成時、本体は対象ファイルを UTF-8 系設定で読み込み、`setup(widget, file_path, content)` を呼ぶ

### 3.2 無題タブ

`core.api.open_untitled_tab(name, content="", editor_id=...)` で開く。

- 無題タブの内部パスは `untitled:{n}` 形式の仮想パスとする
- カスタムタブの無題タブ名は `[E] {name}` とする
- 保存前は実ファイルに紐付かない

## 4. 本体が付与するタブ状態

本体はタブ widget に少なくとも次を設定する。

- `widget.tab_id`
  タブ単位の一意ID。形式は `tab:{n}`
- `widget.editor_id`
  現在のエディタID
- `widget.file_path`
  実ファイルパス、または `untitled:{n}`
- `widget.content`
  タブが保持する現在内容
- `widget.available_editors`
  対象ファイルに対して切り替え可能なエディタ一覧
- `widget.is_dirty`
  未保存変更有無
- `widget.save_plan`
  保存計画。未設定時は `None`

必要に応じて本体は `widget.active_plugin` も設定する。

## 5. UI 表示規則

- カスタムタブのタブ名は `[E] ` プレフィックス付きとする
- タブのツールチップには現在の `file_path` を入れる
- 保存後に実パスが確定した場合、本体はタブ名を保存先ファイル名へ更新する
- 未保存変更がある場合、本体はタブ名先頭に `*` を付ける

表示例:

- `*[E] example.gfx`
- `[E] New GFX`
- `notes.txt`（標準テキストエディタ）

## 6. プラグイン側の必須入口

カスタムタブの `logic` 側は、公開フックとして `setup(widget, file_path, content)` を提供する。

`setup(...)` は少なくとも次を行うこと。

- UI と状態管理クラスを結び付ける
- `widget.content` と UI 表示を同期できる状態にする
- 本体から呼ばれる公開メソッドを widget に生やす
- 初期化完了後に `core.api.notify_editor_ready(widget.tab_id)` を呼ぶ

`gfx` エディタでは `setup(...)` の中で次を公開している。

- `widget.toPlainText`
- `widget.setPlainText`
- `widget.on_save_triggered`
- `widget.on_save_as_triggered`
- `widget.on_write_save_plan`
- `widget.set_params`
- `widget.setParams`

## 7. `params` 適用仕様

`open_tab(..., params=...)` の `params` は、対象タブへ任意の初期化パラメータを渡すための辞書である。

- 新規タブ生成時、本体は `params` を `pending_params[tab_id]` に一時保留する
- プラグイン側が `notify_editor_ready(tab_id)` を呼んだあと、本体は `widget.set_params(params)` を呼べる
- 既に開いている同一タブへ再度 `open_tab(...)` した場合は、保留せず即時適用する
- `set_params` が未実装なら、本体は `widget.params = params` として保持してもよい

このため、カスタムエディタは「初期化中には `params` がまだ届かない」前提で実装すること。

## 8. dirty 管理

カスタムタブは標準テキストエディタと異なり、UI 操作から自動で dirty を検出する。

- 本体は定期的に `widget.content` を監視する
- 監視値が前回通知値と異なれば dirty とみなす
- dirty 化すると `widget.is_dirty = True` になり、タブ名に `*` が付く
- 保存成功後は本体が clean に戻す

したがって、カスタムエディタは内容変更時に `widget.content` を最新状態へ更新し続ける必要がある。

## 9. 保存仕様

### 9.1 呼び出し契約

本体は保存時に次の順でフックを呼ぶ。

1. `widget.on_save_triggered()` または `widget.on_save_as_triggered()`
2. 成功時に `widget.save_plan` があれば `widget.on_write_save_plan()`

### 9.2 保存の責務分担

- 保存対象の決定は `on_save_triggered` / `on_save_as_triggered` 側の責務
- 実ファイル書き込みは `on_write_save_plan` 側の責務
- 本体は保存結果を見て dirty 状態、タブ名、タブパスを更新する

### 9.3 `save_plan`

`gfx` エディタでは `widget.save_plan` に辞書を設定する。代表例:

```python
{
    "tab_kind": "gfx",
    "dialog": "custom" or None,
    "save_as": bool,
    "targets": [...]
}
```

`tab_kind` や `targets` の詳細はタブ種別ごとに拡張してよいが、本体が期待する最小契約は次の 2 点である。

- `widget.save_plan` が `None` でなければ追加書き込み工程がある
- `on_write_save_plan()` は保存結果辞書を返す

### 9.4 保存成功時

保存成功時、本体は次を行う。

- `primary_path` が返ればタブの実パスを更新する
- dirty を解除する
- `widget.save_plan` をクリアする

## 10. エディタ切り替え

同一ファイルは、利用可能ならカスタムエディタと標準テキストエディタを切り替えられる。

- 切り替え単位は `file_path` + `editor_id`
- つまり同じファイルでも、テキスト版とカスタム版は別タブとして共存しうる
- カスタム版タブは `[E]` プレフィックスで識別する

現行実装では、1 エレメントに対して登録されるカスタムエディタは 1 件である。

## 11. 失敗時の扱い

- カスタムエディタ widget の生成または `setup(...)` に失敗した場合、本体は標準テキストエディタへフォールバックしてよい
- 保存ダイアログがキャンセルされた場合、保存結果は `cancelled` とする
- 保存書き込み失敗時、タブは dirty のままとする

## 12. `gfx` エディタから見た実装上の要点

`gfx` エディタは、現行のカスタムタブ実装の参照例として次を満たしている。

- `setup(...)` 内で保存フックと `set_params` を公開する
- `notify_editor_ready(tab_id)` を明示的に呼ぶ
- 無題タブと実ファイルタブの両方で動作する
- `widget.content` を更新し、本体の dirty 監視に追従する
- `save_plan` を用いて `.gfx` 本体と関連 `.dds` をまとめて保存できる

## 13. 非目標

本仕様は次を定義しない。

- カスタムタブ内の具体的 UI レイアウト
- `params` の個別キー定義
- `targets` の詳細構造の共通化
- タブ復元、セッション永続化、分割ビュー

## 14. 関連文書

- [公開APIリファレンス](../plugin_api_reference.md)
- [公開フックリファレンス](../plugin_hooks_reference.md)
- [プラグインモデル](../plugin_model.md)
- [プラグインマニフェスト仕様](./plugin_manifest_spec.md)
