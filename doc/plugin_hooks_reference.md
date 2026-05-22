# 公開フックリファレンス

本書は、本体がプラグインを呼び出すための公開フックを定義する。

公開フックは、プラグインが実装してよい入口である。

補足として、`subscribe_event(...)` / `emit_event(...)` も広い意味では hook 的な役割を持つ。

本書では「本体が直接呼ぶ固定入口」を中心に扱う。

## プラグイン初期化

### `initialize(plugin)`

プラグインロード時に本体から呼ばれる初期化入口。

このフックは、現行の Python ローダが提供する入口である。

将来的に `.exe` や native 実体を読む場合でも、本体の他の箇所から見た役割は「プラグイン初期化」で変えない。

## カスタムエディタ

### `setup(widget, file_path, content)`

カスタムエディタの初期化入口。

本体は次を渡す。

- `widget`
  エディタ UI のルート widget
- `file_path`
  対象ファイルパス
- `content`
  初期内容

関連ファイルの読み込みや UI 反映はプラグイン側の責務とする。

### `widget.set_params(params: dict)`

`open_tab(..., params=...)` で渡されたパラメータを処理する入口。

`notify_editor_ready(tab_id)` のあとに呼ばれることを前提とする。

本体は、エディタ初期化中に届いた `params` を一時保留し、準備完了後にこの入口へ渡しうる。

## 保存

### `widget.on_save_triggered()`

`File > Save` から呼ばれる保存入口。

### `widget.on_save_as_triggered()`

`File > Save As` から呼ばれる保存入口。

### `widget.on_write_save_plan()`

確定済み `save_plan` に従って実ファイルを書き込む入口。

## 追加UI

### `create_assistant_widget(parent) -> dict | None`

補助UIを本体へ追加するための公開フック。

現行実装では `Plugin.create_assistant_widget(parent)` の形で本体から呼ばれる。

戻り値は次のキーを持つ辞書、または `None`。

- `widget`
  追加する widget
- `name`
  セクション表示名
- `collapsible`
  折りたたみ可否

`parent` は本体が渡す親 widget であり、追加UIは本体単体でも動作を壊さない補助機能として実装する。

## プロジェクト保存

### `export_project_data(plugin, context) -> dict`

プロジェクト保存時に呼ばれる。

### `import_project_data(plugin, context, data) -> None`

プロジェクト読み込み時に呼ばれる。

## 任意フック

### `hook_i18n_translate(plugin, payload)`

`core.api.plugin_translate()` から参照される任意の翻訳フック。

## 関連文書

- プラグイン全体方針: [plugin_model.md](./plugin_model.md)
- 公開API: [plugin_api_reference.md](./plugin_api_reference.md)
- 保存仕様: [save_result_spec.md](./specs/save_result_spec.md)
- マニフェスト仕様: [plugin_manifest_spec.md](./specs/plugin_manifest_spec.md)
