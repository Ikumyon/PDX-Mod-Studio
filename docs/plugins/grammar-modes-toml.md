[&larr; 戻る](./../plugin-specification.md)
# 文脈定義ファイル (Modes TOML)

この文書は、プラグインにおける文脈（モード）定義や共通設定を行う `grammar_modes.toml` および翻訳アセットの書き方を定義する。

## 概要

`grammar_modes.toml` は、文法定義機能を提供するプラグインにおいて以下の役割を果たす。

1.  プラグイン共通の構文解析ルール（`syntax.toml`）や型判定ルール（`values.toml`）の指定。
2.  多言語翻訳辞書の登録。
3.  開いたファイルのパスや拡張子に応じて、適用する JSON スキーマを切り替える文脈ルール（`grammar_modes`）の定義。

本ファイルへの相対パスは、[マニフェストファイル](../plugin-specification.md)（`plugin_manifest.json`）の `grammar_modes` キーに記述される。

---

## 最小・完整な構造例

```toml
[grammar]
syntax = "grammar/syntax.toml"
values = "grammar/values.toml"

[i18n]
default = "en-US"
en-US = "translations/en-US.json"
ja-JP = "translations/ja-JP.json"

[[grammar_modes]]
id = "decision_categories"
name_key = "grammar_modes.decision_categories.name"
path = "common/decisions/categories/*.txt"
schema = "grammar/schemas/decision_category.schema.json"
extension = ".txt"
encoding = "utf-8"

[[grammar_modes]]
id = "decisions"
name_key = "grammar_modes.decisions.name"
path = "common/decisions/*.txt"
exclude = ["common/decisions/categories/*.txt"]
schema = "grammar/schemas/decision.schema.json"
extension = ".txt"
encoding = "utf-8"
```

---

## 設定項目一覧

### `[grammar]` (共通構文定義)

このプラグインが使用する構文規則と型定義ファイルを指定する。

*   **`syntax`** (文字列, 必須):
    共通の構文解析規則ファイルへのプラグインルートからの相対パス。
    *   仕様詳細は [Grammar Syntax TOML](./grammar-syntax-toml.md) を参照。
*   **`values`** (文字列, 必須):
    共通の型判定パターン定義ファイルへのプラグインルートからの相対パス。
    *   仕様詳細は [Grammar Values TOML](./grammar-values-toml.md) を参照。

### `[i18n]` (多言語翻訳定義)

UI表示やエラーメッセージで使用する多言語翻訳ファイルを登録する。

*   **`default`** (文字列, 必須):
    既定のロケールキー（例: `en-US`）。
*   **各言語キー** (ロケールキー = パス文字列, 任意):
    ロケールキー（例: `en-US`, `ja-JP`）に対応する、翻訳用 JSON ファイルへの相対パス。

### `[[grammar_modes]]` (スキーマ適用ルール)

エディタで開いたファイルがどの文脈（モード）に属するかを、ファイルパスのパターンマッチ等で判定し、適用するスキーマを決定する。複数個の定義を配列として記述できる。

*   **`id`** (文字列, 必須):
    このモードを識別するユニークID。
*   **`name_key`** (文字列, 必須):
    このモードの表示名の翻訳キー。
*   **`path`** (文字列, 必須):
    適用対象となるファイルのワイルドカードパス（ゲームのワークスペースルートからの相対パス）。
*   **`exclude`** (文字列の配列, 任意):
    除外対象とするファイルのワイルドカードパスのリスト。
*   **`schema`** (文字列, 必須):
    適用する JSON スキーマファイルへの相対パス。
    *   仕様詳細は [Grammar Schema JSON](./grammar-schema-json.md) を参照。
*   **`extension`** (文字列, 必須):
    対象ファイルの拡張子（例: `.txt`）。
*   **`encoding`** (文字列, 必須):
    対象ファイルのテキストエンコーディング（例: `utf-8`）。

---

## 翻訳 (i18n) の記述とフォールバック規則

多言語翻訳ファイルは、プラグイン配下に JSON 形式で作成する。

### 記述例 (`translations/ja-JP.json`)

```json
{
  "hoi4.name": "Hearts of Iron IV プラグイン",
  "hoi4.desc": "Hearts of Iron IV の Mod 開発支援プラグインです。",
  "grammar_modes.decisions.name": "デシジョン定義"
}
```

### フォールバックに関する厳格な仕様

本体は翻訳の解決に関して、曖昧さや憶測を排除するために非常に厳格な挙動を行う。

*   **キーそのものの表示**:
    デフォルトのロケールで、指定された翻訳キーに対応する翻訳が存在しない場合、**「翻訳キーの文字列そのもの」**をそのままUIや画面上に表示する。
    *   例: `"grammar.error.exclusive_cost"` に対応する翻訳が存在しない場合、フォールバックして `"grammar.error.exclusive_cost"` とそのまま表示する。
